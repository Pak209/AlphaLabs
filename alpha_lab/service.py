from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from paper_trader.alpaca_client import AlpacaAPIError, AlpacaClient, AlpacaSafetyError, load_credentials_from_env
from paper_trader.audit_log import AuditLog
from paper_trader.config import load_config
from paper_trader.decision_engine import evaluate_signal, serialize_decision
from paper_trader.models import Signal
from paper_trader.simulated_broker import SimulatedPaperBroker

from .analyst import build_market_briefing, build_trade_explanation, chat_reply
from .database import connect, init_db, resolve_db_path
from .models import normalize_idea_payload
from .options_selector import OptionSelectionError, select_atm_contract
from .catalysts import get_catalyst_radar, import_catalysts_payload
from .daily_brief import build_daily_market_brief
from .live_sources import fetch_polygon_intraday, fetch_yahoo_price
from .market_data import CRYPTO_COINS, build_trending_stock_signals, get_bitcoin_market, get_crypto_market, get_business_brief, get_liquidity_flows
from .repository import AlphaLabRepository
from .performance import build_performance_report
from .scoring_engine import (
    composite, score_catalyst, score_narrative, score_macro, score_price_volume,
    catalyst_inputs_from_idea, narrative_inputs_for_ticker,
)
from .scoring_models import MacroInputs, PriceVolumeInputs
from .options_flow import (
    OptionsFlowProvider, StubOptionsFlowProvider, PolygonOptionsFlowProvider, score_options_flow,
    component_from_signal as options_component_from_signal,
)
from .dark_pool import (
    DarkPoolProvider, StubDarkPoolProvider, score_institutional,
    component_from_signal as institutional_component_from_signal,
)
from .futures_pulse import (
    FuturesDataProvider, PolygonFuturesProvider, StubFuturesDataProvider,
    build_pulse_report, report_to_strategy_signals,
)


DEFAULT_RISK_CONFIG = "alpha_lab/config.example.json"
DEFAULT_AUDIT_LOG = "alpha_lab/data/audit.jsonl"
FALSE_ENV_VALUES = {"0", "false", "no", "off"}


class AlphaLabService:
    def __init__(
        self,
        db_path: str | None = None,
        risk_config_path: str = DEFAULT_RISK_CONFIG,
        audit_log_path: str = DEFAULT_AUDIT_LOG,
        options_flow_provider: OptionsFlowProvider | None = None,
        dark_pool_provider: DarkPoolProvider | None = None,
        futures_data_provider: FuturesDataProvider | None = None,
    ):
        # Resolve the DB path once, here: an explicit db_path (tests, callers)
        # wins; otherwise production entry points that loaded .env get
        # ALPHA_LAB_DB_PATH, and local dev falls back to the default. Every
        # method below uses self.db_path, so the whole service stays on one DB.
        self.db_path = resolve_db_path(db_path)
        self.risk_config_path = risk_config_path
        self.audit_log_path = audit_log_path
        # Signal-source providers default to stubs ("no data" -> neutral, no
        # conviction effect). Inject a live feed to activate the modifiers.
        self.options_flow_provider = options_flow_provider or StubOptionsFlowProvider()
        self.dark_pool_provider = dark_pool_provider or StubDarkPoolProvider()
        # Futures Pulse reads from Polygon/Massive Futures v1 when POLYGON_API_KEY
        # is set; otherwise the live provider returns no data (neutral) per call.
        self.futures_data_provider = futures_data_provider or PolygonFuturesProvider()
        init_db(self.db_path)
        with connect(self.db_path) as conn:
            AlphaLabRepository(conn).seed_defaults()

    # ----------------------------------------------------------------------- #
    # DB identity, heartbeat, and status — used by /api/health, the status
    # command, and the runtime verifier to PROVE the API and scheduler share one
    # database file (same path AND same inode/device), not just the same string.
    # ----------------------------------------------------------------------- #
    def db_identity(self) -> dict[str, Any]:
        """Resolved DB path plus filesystem identity (device:inode) when it exists.

        Two processes that report the same device:inode are demonstrably writing
        the SAME file even if symlinks or differing relative paths are involved.
        """
        path = Path(self.db_path).expanduser().resolve()
        identity: dict[str, Any] = {"db_path": str(path), "db_exists": path.exists()}
        if path.exists():
            st = path.stat()
            identity["db_inode"] = f"{st.st_dev}:{st.st_ino}"
            identity["db_size_bytes"] = st.st_size
            identity["db_modified"] = datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat()
        else:
            identity["db_inode"] = None
        return identity

    def record_scheduler_heartbeat(self, label: str = "scheduler") -> dict[str, Any]:
        """Upsert a single liveness row into app_config on the SHARED DB.

        The scheduler calls this on startup and on a periodic job, so the status
        command / dashboard can show that the always-on writer is alive AND prove
        it is writing the same database the dashboard reads (db_path is stamped).
        """
        beat = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "pid": os.getpid(),
            "label": label,
            "db_path": str(Path(self.db_path).expanduser().resolve()),
            "scheduler_mode": os.getenv("ALPHALAB_SCHEDULER_MODE", "dry_run").strip().lower() or "dry_run",
        }
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO app_config (key, value_json, updated_at) VALUES ('scheduler_heartbeat', ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP",
                (json.dumps(beat, sort_keys=True),),
            )
            conn.commit()
        return beat

    def get_scheduler_heartbeat(self) -> dict[str, Any] | None:
        """Return the last recorded scheduler heartbeat, or None if never written."""
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value_json, updated_at FROM app_config WHERE key='scheduler_heartbeat'"
            ).fetchone()
        if not row:
            return None
        try:
            beat = json.loads(row["value_json"])
        except (TypeError, ValueError):
            beat = {}
        beat.setdefault("updated_at", row["updated_at"])
        return beat

    def db_status(self) -> dict[str, Any]:
        """One-shot operational snapshot of the active database.

        Powers `python -m alpha_lab.db_status` and the /api/health summary:
        active path, existence, idea/trade counts, and the latest scheduler
        heartbeat + scanner-run timestamps (the scheduler's "is it alive" signal).
        """
        status = self.db_identity()
        with connect(self.db_path) as conn:
            status["ideas_count"] = int(conn.execute("SELECT COUNT(*) FROM alpha_ideas").fetchone()[0])
            status["trades_count"] = int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
            status["catalyst_events_count"] = int(
                conn.execute("SELECT COUNT(*) FROM catalyst_events").fetchone()[0]
            )
            last_run = conn.execute(
                "SELECT source, created_at FROM scanner_runs ORDER BY datetime(created_at) DESC, id DESC LIMIT 1"
            ).fetchone()
        status["last_scanner_run_at"] = last_run["created_at"] if last_run else None
        status["last_scanner_run_source"] = last_run["source"] if last_run else None
        heartbeat = self.get_scheduler_heartbeat()
        status["scheduler_heartbeat_at"] = heartbeat.get("timestamp") if heartbeat else None
        status["scheduler_heartbeat"] = heartbeat
        return status

    def _score_idea(self, idea: dict[str, Any]) -> Any:
        """
        Full Alpha Score for an idea: catalyst + price/volume + narrative +
        options-flow + institutional + macro, with the CRITICAL-RULE hard gate
        enforced inside composite(). Flow/institutional come from the configured
        providers (stubs by default -> neutral). The agent signals are returned
        alongside the score so they can be logged with the trade.
        """
        ticker = idea.get("ticker")
        options_signal = score_options_flow(self.options_flow_provider.fetch(ticker), ticker)
        institutional_signal = score_institutional(self.dark_pool_provider.fetch(ticker), ticker)
        alpha = composite(
            catalyst=score_catalyst(catalyst_inputs_from_idea(idea)),
            narrative=score_narrative(narrative_inputs_for_ticker(ticker)),
            macro=score_macro(MacroInputs()),
            price_volume=score_price_volume(self._price_volume_inputs(idea)),
            options=options_component_from_signal(options_signal),
            institutional=institutional_component_from_signal(institutional_signal),
        )
        return alpha, options_signal, institutional_signal

    # A move smaller than this (in %) is treated as no clear directional read, so
    # market noise neither confirms nor penalizes the thesis.
    _PV_GAP_DEADBAND_PCT = 0.25

    def _price_volume_inputs(self, idea: dict[str, Any]) -> PriceVolumeInputs:
        """
        Build price/volume confirmation inputs for the hard gate.

        Equities/options: pull a live Polygon intraday snapshot (gap %, relative
        volume) and decide whether price ACTION confirms the idea's bias. Price
        direction drives the gate; elevated volume can boost confirmation but
        low/early-session volume stays neutral (never a penalty). On any miss
        (no POLYGON_API_KEY, bad ticker, network) we fall back to neutral, so the
        gate behaves exactly as before — conservative, not broken.

        Crypto/other: left neutral here (no equity snapshot applies).
        """
        bias = str(idea.get("bias") or "neutral").lower()
        asset_type = str(idea.get("asset_type") or "").lower()
        ticker = str(idea.get("ticker") or "").strip()
        if asset_type not in {"equity", "option"} or not ticker:
            return PriceVolumeInputs(bias=bias)

        snap = fetch_polygon_intraday(ticker)
        if snap.get("status") != "ok":
            return PriceVolumeInputs(bias=bias)

        gap = snap.get("gap_pct")
        rv = snap.get("relative_volume")

        trend_confirms = None
        if isinstance(gap, (int, float)) and abs(gap) >= self._PV_GAP_DEADBAND_PCT:
            if bias == "bullish":
                trend_confirms = gap > 0
            elif bias == "bearish":
                trend_confirms = gap < 0

        # Volume only counts as confirmation when it accompanies a price move IN
        # the thesis direction. High volume on a move AGAINST the bias is
        # disconfirming, not confirming, so we don't let it lift the score — it
        # stays neutral and price action drags the component below the gate.
        # Sub-1.0 (early-session cumulative) volume also stays neutral.
        relative_volume = (
            rv if (trend_confirms is True and isinstance(rv, (int, float)) and rv >= 1.0) else None
        )

        return PriceVolumeInputs(
            bias=bias,
            relative_volume=relative_volume,
            gap_pct=float(gap) if isinstance(gap, (int, float)) else 0.0,
            trend_confirms=trend_confirms,
        )

    def create_idea(self, payload: dict[str, Any]) -> dict[str, Any]:
        idea = normalize_idea_payload(payload)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            idea["market_regime"] = idea.get("market_regime") or self._current_market_regime(repo)
            created = repo.create_idea(idea)
            validation_price = self._validation_price(created["ticker"])
            repo.upsert_signal_evaluation(
                created["id"],
                self._initial_signal_evaluation(created, validation_price),
            )
            analyst_context = {**self._latest_briefing_context(conn), "reference_price": validation_price}
            explanation = build_trade_explanation({**idea, "id": created["id"]}, analyst_context)
            repo.create_trade_explanation(created["id"], explanation, {"source_payload": payload})
            if created.get("catalyst_event_id"):
                repo.link_catalyst_event_to_idea(int(created["catalyst_event_id"]), int(created["id"]))
            return self._with_business_brief(repo.get_idea(created["id"]))

    def import_ideas(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_ideas = payload.get("signals") if isinstance(payload.get("signals"), list) else payload.get("ideas")
        if raw_ideas is None:
            raw_ideas = [payload]
        return [self.create_idea(item) for item in raw_ideas]

    def list_ideas(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return [self._with_business_brief(idea) for idea in AlphaLabRepository(conn).list_ideas(limit)]

    def import_and_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested_mode = str(payload.get("execution_mode", "dry_run")).strip().lower()
        if requested_mode not in {"dry_run", "paper"}:
            raise ValueError("execution_mode must be dry_run or paper")
        if requested_mode == "paper" and os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").lower() != "true":
            raise ValueError("automation paper trading is disabled; set ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true to enable")

        dry_run = requested_mode != "paper"
        ideas = self.import_ideas(payload)
        results = []
        for idea in ideas:
            try:
                trade_result = self.place_trade(idea["id"], dry_run=dry_run)
            except Exception as exc:
                trade_result = {"accepted": False, "action": "error", "reasons": [str(exc)], "ticker": idea.get("ticker")}
            results.append({"idea": idea, "test_result": trade_result})
        return {"execution_mode": requested_mode, "dry_run": dry_run, "results": results}

    def test_new_ideas(self, dry_run: bool = True) -> dict[str, Any]:
        if not dry_run and os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").lower() != "true":
            raise ValueError("paper testing is disabled; set ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true to enable")
        ideas = [idea for idea in self.list_ideas(limit=500) if idea.get("status") == "new"]
        results = []
        for idea in ideas:
            try:
                results.append({"idea": idea, "test_result": self.place_trade(idea["id"], dry_run=dry_run)})
            except Exception as exc:
                results.append({"idea": idea, "test_result": {"accepted": False, "action": "error", "reasons": [str(exc)]}})
        return {"dry_run": dry_run, "results": results}

    def test_trending_strategies(self, dry_run: bool = True, limit: int = 3) -> dict[str, Any]:
        if not dry_run and os.getenv("ALPHALAB_ALLOW_MANUAL_PAPER_TRADES", "true").lower() != "true":
            raise ValueError("manual paper trading is disabled; set ALPHALAB_ALLOW_MANUAL_PAPER_TRADES=true to enable")
        if not self._equity_market_open():
            generated = self.generate_after_hours_btc_idea()
            return {
                "dry_run": dry_run,
                "mode": "after_hours_btc",
                "signals_created": 1,
                "results": [{"idea": generated["idea"], "test_result": {"accepted": False, "action": "needs_human_approval", "reasons": ["After-hours BTC idea created for approval before paper execution."]}}],
            }
        limit = max(1, min(int(limit), 5))
        signals = build_trending_stock_signals(limit=limit)
        ideas = [self.create_idea(signal) for signal in signals]
        results = []
        for idea in ideas:
            try:
                results.append({"idea": idea, "test_result": self.place_trade(idea["id"], dry_run=dry_run)})
            except Exception as exc:
                results.append({"idea": idea, "test_result": {"accepted": False, "action": "error", "reasons": [str(exc)]}})
        return {"dry_run": dry_run, "signals_created": len(ideas), "results": results}

    def poll_live_catalysts(self, dry_run: bool = True) -> dict[str, Any]:
        if not dry_run and os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").lower() != "true":
            raise ValueError("automation paper trading is disabled; set ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true to enable")
        intelligence = self.catalyst_intelligence(live=True, persist=True, generate_ideas=False)
        payload = {
            "signals": intelligence.get("signals", []),
            "catalysts": intelligence.get("catalysts", []),
            "live_status": intelligence.get("live_status"),
            "mode": intelligence.get("mode"),
            "source": "catalyst_intelligence",
            "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
        }
        existing = self._recent_catalyst_theses()
        signals = []
        duplicates = 0
        for signal in payload["signals"]:
            if signal["reason"] in existing:
                duplicates += 1
                continue
            signals.append(signal)
        if not signals:
            summary = self._scanner_summary(
                candidates_found=len(payload.get("catalysts") or []),
                ideas_persisted=0,
                rejected=len(payload.get("catalysts") or []),
                skipped=duplicates,
                reasons={"duplicate ticker/catalyst": duplicates, "not trade candidate": len(payload.get("catalysts") or []) - len(payload.get("signals") or [])},
                dry_run=dry_run,
                note="no new catalyst signals",
            )
            summary.update(self._catalyst_source_accounting(payload))
            self._record_scanner_run(
                "catalyst_radar",
                "poll_live",
                summary,
            )
            return {**payload, "signals": [], "test_result": {"dry_run": dry_run, "results": [], "note": "no new catalyst signals"}}
        result = self.import_and_test({"signals": signals, "execution_mode": "dry_run" if dry_run else "paper"})
        summary = self._scanner_summary(
            candidates_found=len(payload.get("catalysts") or []),
            ideas_persisted=len(result.get("results") or []),
            rejected=max(0, len(payload.get("catalysts") or []) - len(result.get("results") or [])),
            skipped=duplicates,
            reasons={"duplicate ticker/catalyst": duplicates, "not trade candidate": len(payload.get("catalysts") or []) - len(payload.get("signals") or [])},
            dry_run=dry_run,
        )
        summary.update(self._catalyst_source_accounting(payload))
        self._record_scanner_run(
            "catalyst_radar",
            "poll_live",
            summary,
        )
        return {**payload, "signals": signals, "test_result": result}

    def catalyst_intelligence(
        self,
        payload: dict[str, Any] | None = None,
        live: bool = True,
        persist: bool = True,
        generate_ideas: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Run Catalyst Intelligence: collect/score, optionally persist and test ideas."""
        radar = get_catalyst_radar(payload, live=live)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            regime = self._current_market_regime(repo)
            persisted = []
            for event in radar.get("catalysts", []):
                event = {**event, "market_regime": event.get("market_regime") or regime}
                if persist:
                    event = repo.upsert_catalyst_event(event)
                persisted.append(event)
            events_by_key = {
                (event.get("ticker"), event.get("headline"), event.get("source"), event.get("published_at")): event
                for event in persisted
            }
            signals = []
            for signal in radar.get("signals", []):
                key = (
                    signal.get("ticker"),
                    next((c.get("headline") for c in persisted if c.get("ticker") == signal.get("ticker") and (c.get("summary") == signal.get("catalyst") or c.get("headline") in signal.get("reason", ""))), ""),
                    None,
                    None,
                )
                event = next(
                    (
                        item for item in persisted
                        if item.get("ticker") == signal.get("ticker")
                        and item.get("catalyst_score") == signal.get("catalyst_score")
                        and (item.get("summary") == signal.get("catalyst") or item.get("headline") in signal.get("reason", ""))
                    ),
                    None,
                )
                signal = {**signal, "market_regime": signal.get("market_regime") or regime}
                if event:
                    signal["catalyst_event_id"] = event.get("id")
                    signal["catalyst_type"] = event.get("catalyst_type")
                    signal["catalyst_score"] = event.get("catalyst_score")
                    signal["strategy_tags"] = list(dict.fromkeys([event.get("strategy_label"), event.get("catalyst_type"), *signal.get("strategy_tags", [])]))
                    signal["source_refs"] = event.get("supporting_evidence") or signal.get("source_refs", [])
                signals.append(signal)
            test_result = None
            if generate_ideas and signals:
                test_result = self.import_and_test({"signals": signals, "execution_mode": "dry_run" if dry_run else "paper"})
                if persist and test_result:
                    for result in test_result.get("results", []):
                        idea = result.get("idea") or {}
                        event_id = idea.get("catalyst_event_id")
                        if event_id and idea.get("id"):
                            repo.link_catalyst_event_to_idea(int(event_id), int(idea["id"]))
            dashboard = repo.catalyst_intelligence_dashboard()
        return {
            **radar,
            "source": "catalyst_intelligence",
            "market_regime": dashboard.get("market_regime", None) or (persisted[0].get("market_regime") if persisted else "unknown"),
            "catalysts": persisted,
            "signals": signals,
            "dashboard": dashboard,
            "test_result": test_result,
        }

    def build_daily_brief(self, live_catalysts: bool = True) -> dict[str, Any]:
        return build_daily_market_brief(live_catalysts=live_catalysts)

    def futures_pulse(
        self,
        session_date: str | None = None,
        catalyst_ts: str | None = None,
        persist: bool = True,
        score_signals: bool = True,
        provider: FuturesDataProvider | None = None,
    ) -> dict[str, Any]:
        """Overnight Futures Pulse: build the premarket regime read from overnight
        futures aggregates, optionally persist it for backtesting, and attach a
        READ-ONLY strategy-scoring preview. This never places or approves a trade.

        ``provider`` overrides the default data provider for this call only — the
        scheduled nightly pull passes a throttled provider so the full board fills
        the backtest tables without tripping the free-plan rate limit.
        """
        report_model = build_pulse_report(
            provider or self.futures_data_provider, session_date=session_date, catalyst_ts=catalyst_ts,
        )
        # Build candidate signals from the typed model, then serialize to JSON.
        signals = report_to_strategy_signals(report_model) if score_signals else []
        report = report_model.model_dump()

        # Feed the watchlist into the existing scoring engine as a read-only
        # preview (tier/composite only) — no idea is created, no order is placed.
        scored: list[dict[str, Any]] = []
        for signal in signals:
            try:
                alpha = composite(
                    catalyst=score_catalyst(catalyst_inputs_from_idea(signal)),
                    narrative=score_narrative(narrative_inputs_for_ticker(signal.get("ticker"))),
                    macro=score_macro(MacroInputs()),
                    price_volume=score_price_volume(PriceVolumeInputs(bias=signal.get("bias", "neutral"))),
                )
                scored.append({
                    "ticker": signal["ticker"],
                    "bias": signal["bias"],
                    "composite_score": alpha.composite_score,
                    "tier": alpha.tier,
                    "thesis": signal["thesis"],
                    "strategy_tags": signal.get("strategy_tags", []),
                })
            except Exception as exc:
                scored.append({"ticker": signal.get("ticker"), "error": str(exc).splitlines()[0][:160]})

        report["strategy_signals"] = signals
        report["strategy_scoring_preview"] = scored

        if persist and report.get("status") == "ok":
            try:
                with connect(self.db_path) as conn:
                    snapshot_id = AlphaLabRepository(conn).save_futures_pulse(report)
                report["snapshot_id"] = snapshot_id
            except Exception as exc:
                report.setdefault("notes", []).append(
                    f"Snapshot persistence failed: {str(exc).splitlines()[0][:160]}")
        return report

    def run_overnight_futures_pull(
        self,
        session_date: str | None = None,
        catalyst_ts: str | None = None,
    ) -> dict[str, Any]:
        """Scheduled early-morning pull of the completed overnight session.

        Runs the pulse with a THROTTLED provider (default 13s/request, honoring
        POLYGON_FUTURES_MIN_INTERVAL_SEC) so the full 12-contract board stays under
        the free "Futures Basic" 5-requests/minute cap, then persists the snapshot
        into the SQLite backtest tables. Read-only — no idea is created, no order
        is placed. A no-op (nothing persisted) when POLYGON_API_KEY is unset.
        """
        interval = float(os.getenv("POLYGON_FUTURES_MIN_INTERVAL_SEC", "13") or 13)
        provider = PolygonFuturesProvider(min_interval_sec=interval)
        report = self.futures_pulse(
            session_date=session_date, catalyst_ts=catalyst_ts,
            persist=True, score_signals=True, provider=provider,
        )
        print(
            f"[alphalab-futures] overnight pull session={report.get('session_date')} "
            f"status={report.get('status')} regime={report.get('regime', {}).get('regime')} "
            f"snapshot_id={report.get('snapshot_id')}",
            flush=True,
        )
        return report

    def run_options_flow_preview(
        self,
        watchlist: list[str] | None = None,
        session_date: str | None = None,
        provider: OptionsFlowProvider | None = None,
    ) -> dict[str, Any]:
        """Read-only options-flow pre-scan preview with scanner accounting.

        This only fetches/grades context for a small watchlist and writes one
        scanner_runs summary. It never creates ideas, trades, orders, approvals,
        or broker calls.
        """
        symbols = self._options_preview_watchlist(watchlist)
        interval = float(os.getenv("POLYGON_OPTIONS_MIN_INTERVAL_SEC", "13") or 13)
        flow_provider = provider or PolygonOptionsFlowProvider(
            min_interval_sec=interval,
            session_date=session_date,
            max_contracts_per_side=int(os.getenv("POLYGON_OPTIONS_MAX_CONTRACTS_PER_SIDE", "4") or 4),
        )
        results = []
        has_data = 0
        no_data = 0
        bullish_or_bearish = 0
        for symbol in symbols:
            try:
                signal = score_options_flow(flow_provider.fetch(symbol), symbol)
            except Exception as exc:
                signal = score_options_flow(None, symbol)
                item = signal.model_dump()
                item["error"] = str(exc).splitlines()[0][:160]
                results.append(item)
                no_data += 1
                continue
            item = signal.model_dump()
            results.append(item)
            if signal.has_data:
                has_data += 1
                if signal.bias in {"bullish", "bearish"}:
                    bullish_or_bearish += 1
            else:
                no_data += 1
        reasons = {}
        if no_data:
            reasons["no options data or not entitled"] = no_data
        if has_data and not bullish_or_bearish:
            reasons["neutral options flow"] = has_data
        summary = self._scanner_summary(
            candidates_found=has_data,
            ideas_persisted=0,
            rejected=no_data,
            skipped=no_data,
            reasons=reasons,
            dry_run=True,
            note="read-only options-flow preview; no ideas/trades/orders created",
        )
        summary.update(
            {
                "enabled": bool(os.getenv("POLYGON_API_KEY", "").strip()) or provider is not None,
                "requests_attempted": len(symbols),
                "responses_received": has_data,
                "raw_items": len(symbols),
                "candidates_filtered": no_data,
                "source_problems": [] if has_data else ["no data, missing entitlement, missing key, or provider returned empty"],
            }
        )
        self._record_scanner_run("options_flow", "preview", summary)
        return {
            "status": "ok",
            "source": "options_flow",
            "read_only": True,
            "watchlist": symbols,
            "session_date": session_date,
            "summary": summary,
            "results": results,
        }

    def list_futures_snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_futures_snapshots(limit)

    def after_hours_btc(self) -> dict[str, Any]:
        btc = self._safe_market_payload(get_bitcoin_market)
        liquidity = self._safe_market_payload(get_liquidity_flows)
        crypto_flow = next((group for group in liquidity.get("groups", []) if group.get("name") == "Crypto Majors"), {})
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            pending = [
                idea for idea in repo.list_ideas(100)
                if str(idea.get("asset_type", "")).lower() == "crypto" and idea.get("status") in {"new", "needs_review", "approved"}
            ]
        return {
            "status": "ok" if btc.get("status") == "ok" else "unavailable",
            "mode": "after_hours_crypto",
            "asset_type": "crypto",
            "market_hours_note": "Equities/options stay restricted to market hours; BTC/crypto analysis is available 24/7.",
            "current_btc_thesis": btc,
            "crypto_flow": crypto_flow,
            "pending_crypto_ideas": pending,
            "approval_status": self._crypto_approval_summary(pending),
            "risk_status": self._crypto_risk_status(),
        }

    def generate_after_hours_btc_idea(self) -> dict[str, Any]:
        return self._generate_crypto_idea("BTC/USD")

    def _generate_crypto_idea(self, ticker: str) -> dict[str, Any]:
        market = get_crypto_market(ticker)
        signal = self._btc_signal_from_market(market)
        idea = normalize_idea_payload(signal)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            idea["market_regime"] = self._current_market_regime(repo)
            created = repo.create_idea(idea)
            explanation = build_trade_explanation({**idea, "id": created["id"]}, {"market_context": market.get("summary", ""), "source": market.get("source", "")})
            explanation["analyst_assisted"] = True
            repo.create_trade_explanation(created["id"], explanation, {"source_payload": signal, "btc_market": market})
            return {"idea": self._with_business_brief(repo.get_idea(created["id"])), "explanation": explanation, "btc": market}

    def generate_after_hours_crypto_ideas(self) -> dict[str, Any]:
        """Generate one after-hours idea per Alpaca-tradeable coin (BTC/LINK/HYPE)."""
        results: list[dict[str, Any]] = []
        for ticker in CRYPTO_COINS:
            try:
                results.append({"ticker": ticker, **self._generate_crypto_idea(ticker)})
            except Exception as exc:  # one coin's data failure must not block the rest
                results.append({"ticker": ticker, "status": "error", "error": str(exc)})
        return {"status": "ok", "asset_type": "crypto", "results": results}

    def generate_and_save_market_briefing(self, live_catalysts: bool = True) -> dict[str, Any]:
        base_brief = self.build_daily_brief(live_catalysts=live_catalysts)
        briefing = build_market_briefing(base_brief)
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).save_market_briefing(briefing)

    def list_market_briefings(self, limit: int = 20) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_market_briefings(limit)

    def import_daily_brief_and_test(self, dry_run: bool = True, live_catalysts: bool = True) -> dict[str, Any]:
        if not dry_run and os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").lower() != "true":
            raise ValueError("automation paper trading is disabled; set ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true to enable")
        brief = self.build_daily_brief(live_catalysts=live_catalysts)
        existing = self._recent_daily_brief_theses()
        signals = [signal for signal in brief["signals"] if signal["reason"] not in existing]
        duplicates = len(brief.get("signals") or []) - len(signals)
        if not signals:
            self._record_scanner_run(
                "daily_market_brief",
                "import_and_test",
                self._scanner_summary(
                    candidates_found=len(brief.get("signals") or []),
                    ideas_persisted=0,
                    rejected=len(brief.get("signals") or []),
                    skipped=duplicates,
                    reasons={"duplicate thesis": duplicates, "no actionable signal": 0},
                    dry_run=dry_run,
                    note="no new daily brief signals",
                ),
            )
            return {**brief, "signals": [], "test_result": {"dry_run": dry_run, "results": [], "note": "no new daily brief signals"}}
        result = self.import_and_test({"signals": signals, "execution_mode": "dry_run" if dry_run else "paper"})
        self._record_scanner_run(
            "daily_market_brief",
            "import_and_test",
            self._scanner_summary(
                candidates_found=len(brief.get("signals") or []),
                ideas_persisted=len(result.get("results") or []),
                rejected=max(0, len(brief.get("signals") or []) - len(result.get("results") or [])),
                skipped=duplicates,
                reasons={"duplicate thesis": duplicates},
                dry_run=dry_run,
            ),
        )
        return {**brief, "signals": signals, "test_result": result}

    def poll_weekend_crypto(self, dry_run: bool = True) -> dict[str, Any]:
        """Weekend-safe, crypto-ONLY idea poll.

        Equities/options markets are closed on weekends, so the regular catalyst
        and daily-brief jobs run mon-fri only. This keeps the 24/7 crypto path
        alive: build a fresh BTC setup from live market data, dedupe against
        recent after-hours BTC theses so it won't spam an idea every few minutes,
        then score/test it. It never imports an equity signal.
        """
        if not dry_run and os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").lower() != "true":
            raise ValueError("automation paper trading is disabled; set ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true to enable")
        recent = self._recent_crypto_theses()
        signals: list[dict[str, Any]] = []
        unavailable = 0
        duplicates = 0
        for ticker in CRYPTO_COINS:
            market = self._safe_market_payload(lambda t=ticker: get_crypto_market(t))
            if market.get("status") not in {None, "ok"}:
                unavailable += 1
                continue
            signal = self._btc_signal_from_market(market)
            if signal.get("thesis") in recent:
                duplicates += 1
                continue
            signals.append(signal)
        if not signals:
            note = "no new crypto signal" if (duplicates or not unavailable) else "crypto market data unavailable"
            status = "unavailable" if unavailable and not duplicates else "ok"
            self._record_scanner_run(
                "after_hours_btc",
                "weekend_crypto",
                self._scanner_summary(
                    candidates_found=len(CRYPTO_COINS) - unavailable,
                    ideas_persisted=0,
                    rejected=unavailable,
                    skipped=duplicates,
                    reasons={"duplicate thesis": duplicates, "crypto market data unavailable": unavailable},
                    dry_run=dry_run,
                    note=note,
                ),
            )
            return {"status": status, "asset_type": "crypto", "signals": [],
                    "test_result": {"dry_run": dry_run, "results": [], "note": note}}
        result = self.import_and_test({"signals": signals, "execution_mode": "dry_run" if dry_run else "paper"})
        self._record_scanner_run(
            "after_hours_btc",
            "weekend_crypto",
            self._scanner_summary(
                candidates_found=len(signals),
                ideas_persisted=len(result.get("results") or []),
                rejected=unavailable,
                skipped=duplicates,
                reasons={"duplicate thesis": duplicates, "crypto market data unavailable": unavailable},
                dry_run=dry_run,
            ),
        )
        return {"status": "ok", "asset_type": "crypto", "signals": signals, "test_result": result}

    def analyst_chat(self, message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Advisory markets chat grounded in current AlphaLab data (read-only).

        Assembles a compact live context (recent catalysts, scored ideas, latest
        brief) and asks the LLM analyst. This NEVER places or approves a trade —
        it only reads context and returns text.
        """
        message = str(message or "").strip()
        if not message:
            raise ValueError("message is required")
        context = self._chat_context()
        return chat_reply(message, context=context, history=history or [])

    def _chat_context(self) -> dict[str, Any]:
        from .catalysts import get_catalyst_radar
        ctx: dict[str, Any] = {}
        try:
            radar = get_catalyst_radar(live=True)
            items = radar.get("catalysts") or radar.get("items") or []
            ctx["recent_catalysts"] = [
                {"ticker": c.get("ticker"), "headline": c.get("headline"),
                 "source": c.get("source"), "published_at": c.get("published_at")}
                for c in items[:15]
            ]
        except Exception as exc:
            ctx["recent_catalysts_error"] = str(exc).splitlines()[0][:160]
        try:
            ctx["scored_ideas"] = [
                {"ticker": i.get("ticker"), "bias": i.get("bias"), "status": i.get("status"),
                 "confidence": i.get("confidence"), "thesis": str(i.get("thesis") or "")[:200]}
                for i in self.list_ideas(limit=15)
            ]
        except Exception as exc:
            ctx["scored_ideas_error"] = str(exc).splitlines()[0][:160]
        try:
            briefs = self.list_market_briefings(limit=1)
            if briefs:
                b = briefs[0]
                ctx["latest_brief"] = {
                    "generated_at": b.get("generated_at") or b.get("created_at"),
                    "tone": b.get("broad_market_tone"),
                    "themes": b.get("themes"),
                    "candidates": b.get("candidate_tickers_to_monitor"),
                }
        except Exception as exc:
            ctx["latest_brief_error"] = str(exc).splitlines()[0][:160]
        return ctx

    def set_idea_status(self, idea_id: int, status: str, reason: str = "") -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return self._with_business_brief(AlphaLabRepository(conn).update_idea_status(idea_id, status, reason))

    def run_decision(self, idea_id: int, dry_run: bool = True, as_option: bool = False) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            idea = repo.get_idea(idea_id)
            selection = self._select_option_contract(idea) if as_option else None
            signal = self._signal_from_idea(idea, as_option=as_option)
            broker = self._broker(dry_run=True)
            config_profile = "crypto" if signal.asset_type == "crypto" else "default"
            alpha_score, options_signal, institutional_signal = self._score_idea(idea)
            alpha = alpha_score.model_dump()
            decision = evaluate_signal(
                signal,
                load_config(self.risk_config_path, profile=config_profile),
                broker,
                AuditLog(self.audit_log_path),
                dry_run=dry_run,
                alpha=alpha,
                option=selection,
            )
            payload = serialize_decision(decision)
            payload["options_flow"] = options_signal.model_dump()
            payload["institutional"] = institutional_signal.model_dump()
            if selection:
                payload["option"] = selection
            decision_log_id = repo.log_decision(idea_id, payload["action"], payload["reasons"], payload)
            payload["decision_log_id"] = decision_log_id
            if not decision.accepted:
                repo.update_idea_status(idea_id, "rejected", "; ".join(decision.reasons))
            elif dry_run:
                repo.update_idea_status(idea_id, "accepted")
            return payload

    def place_trade(self, idea_id: int, dry_run: bool = True, as_option: bool = False) -> dict[str, Any]:
        if not dry_run:
            approval_error = self._paper_execution_approval_error(idea_id)
            if approval_error:
                self._log_execution_attempt(idea_id, approval_error, dry_run=dry_run)
                return approval_error
        try:
            decision = self.run_decision(idea_id, dry_run=dry_run, as_option=as_option)
        except OptionSelectionError as exc:
            reason = f"No tradeable option contract: {exc}"
            with connect(self.db_path) as conn:
                repo = AlphaLabRepository(conn)
                ticker = "unknown"
                try:
                    ticker = repo.get_idea(idea_id).get("ticker", "unknown")
                except Exception:
                    pass
                repo.update_idea_status(idea_id, "rejected", reason)
            result = {
                "accepted": False,
                "action": "no_option_contract",
                "reasons": [reason],
                "ticker": ticker,
                "notional": None,
                "qty": None,
                "order_payload": None,
                "order_response": {"submitted": False, "message": "No Alpaca paper order was placed."},
            }
            self._log_execution_attempt(idea_id, result, dry_run=dry_run)
            return result
        except (AlpacaAPIError, AlpacaSafetyError, OSError) as exc:
            reason = self._friendly_broker_error(exc)
            ticker = "unknown"
            with connect(self.db_path) as conn:
                repo = AlphaLabRepository(conn)
                try:
                    ticker = repo.get_idea(idea_id).get("ticker", "unknown")
                except Exception:
                    pass
                repo.update_idea_status(idea_id, "rejected", reason)
            result = {
                "accepted": False,
                "action": "broker_unavailable",
                "reasons": [reason],
                "ticker": ticker,
                "notional": None,
                "qty": None,
                "order_payload": None,
                "order_response": {"submitted": False, "message": "No Alpaca paper order was placed."},
            }
            self._log_execution_attempt(idea_id, result, dry_run=dry_run)
            return result
        if not decision["accepted"]:
            self._log_execution_attempt(idea_id, decision, dry_run=dry_run)
            return decision

        broker = self._broker(dry_run=dry_run)
        order_payload = decision["order_payload"]
        try:
            response = {"dry_run": True, "message": "No order placed"} if dry_run else broker.place_order(order_payload)
        except (AlpacaAPIError, AlpacaSafetyError, OSError) as exc:
            reason = self._friendly_broker_error(exc)
            with connect(self.db_path) as conn:
                AlphaLabRepository(conn).update_idea_status(idea_id, "rejected", reason)
            result = {**decision, "accepted": False, "action": "broker_unavailable", "reasons": [reason], "order_response": {"submitted": False, "message": "No Alpaca paper order was placed."}}
            self._log_execution_attempt(idea_id, result, dry_run=dry_run)
            return result
        side = order_payload["side"]
        option = decision.get("option")
        # Option fills are priced per-contract; the stock last-trade endpoint does not
        # cover OCC symbols, so fall back to the selected contract's mid/ask.
        if option:
            submitted_price = self._submitted_price(response) or option.get("mid") or option.get("ask")
        else:
            submitted_price = self._submitted_price(response) or self._latest_price(decision["ticker"])

        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            trade_id = repo.create_trade(
                {
                    "idea_id": idea_id,
                    "ticker": (option or {}).get("contract_symbol") or decision["ticker"],
                    "side": side,
                    "quantity": decision.get("qty"),
                    "notional": decision.get("notional"),
                    "entry_price": submitted_price,
                    "status": "dry_run" if dry_run else "paper_open",
                    "dry_run": dry_run,
                    "asset_type": "option" if option else decision.get("asset_type", "equity"),
                    "decision_log_id": decision.get("decision_log_id"),
                    "contracts": decision.get("qty") if option else None,
                    "option": option,
                    "alpha": decision.get("alpha"),
                    "options_flow": decision.get("options_flow"),
                    "institutional": decision.get("institutional"),
                }
            )
            repo.create_order(
                {
                    "trade_id": trade_id,
                    "alpaca_order_id": response.get("id"),
                    "ticker": (option or {}).get("contract_symbol") or decision["ticker"],
                    "side": side,
                    "payload": order_payload,
                    "response": response,
                    "status": "dry_run" if dry_run else "submitted",
                    "dry_run": dry_run,
                }
            )
            if submitted_price and not dry_run:
                idea = repo.get_idea(idea_id)
                repo.upsert_signal_evaluation(
                    idea_id,
                    self._initial_signal_evaluation(idea, float(submitted_price)),
                )
            repo.update_idea_status(idea_id, "tested" if dry_run else "traded")
        result = {**decision, "order_response": response}
        result["trade_id"] = trade_id
        self._log_execution_attempt(idea_id, result, dry_run=dry_run, submitted_price=submitted_price)
        return result

    def _poll_fill(self, broker, order_id: str, attempts: int = 20, delay: float = 1.5) -> dict[str, Any]:
        """Poll an order until it reaches a terminal state or attempts run out."""
        import time

        order: dict[str, Any] = {}
        for _ in range(max(1, attempts)):
            order = broker.get_order(order_id)
            if str(order.get("status")) in {"filled", "canceled", "rejected", "expired", "done_for_day"}:
                return order
            time.sleep(delay)
        return order

    def refresh_option_entry_fill(self, trade_id: int) -> dict[str, Any]:
        """Poll the entry order and write the realized fill price onto the trade."""
        broker = self._broker(dry_run=False)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            trade = repo.get_trade(trade_id)
            order_id = repo.entry_order_id_for_trade(trade_id)
        if not order_id:
            return trade
        order = self._poll_fill(broker, order_id)
        fill = self._submitted_price(order)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            status = "paper_open" if str(order.get("status")) == "filled" else trade.get("status", "paper_open")
            repo.record_fill(trade_id, fill, status)
            return {"trade": repo.get_trade(trade_id), "order": order, "filled_avg_price": fill}

    def close_option_trade(self, trade_id: int) -> dict[str, Any]:
        """Close an open paper option position and settle realized P/L back onto the trade.

        Long option P/L = (exit_fill - entry_fill) * contracts * 100 (the contract
        multiplier). This populates exit_price / realized_pl / closed_at so the
        training_rows view links entry features to the realized outcome.
        """
        broker = self._broker(dry_run=False)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            trade = repo.get_trade(trade_id)
        symbol = trade.get("contract_symbol") or trade.get("ticker")
        contracts = int(trade.get("contracts") or trade.get("quantity") or 1)
        entry = float(trade.get("entry_price") or 0)
        close_order = broker.close_position(symbol)
        order_id = close_order.get("id")
        if order_id:
            close_order = self._poll_fill(broker, order_id)
        exit_price = self._submitted_price(close_order)
        realized = round(((exit_price or entry) - entry) * contracts * 100, 4)
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            settled = repo.close_trade(trade_id, exit_price, realized, "closed")
            positions = []
            try:
                positions = broker.get_positions()
                repo.sync_positions(positions)
            except Exception:
                pass
        return {
            "trade": settled,
            "close_order": close_order,
            "exit_price": exit_price,
            "realized_pl": realized,
            "contracts": contracts,
        }

    def list_pending_approvals(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_pending_approvals(limit)

    def approve_idea_for_execution(self, idea_id: int, note: str = "") -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return self._with_business_brief(AlphaLabRepository(conn).set_approval_status(idea_id, "approved", note))

    def reject_idea_for_execution(self, idea_id: int, note: str = "rejected by reviewer") -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return self._with_business_brief(AlphaLabRepository(conn).set_approval_status(idea_id, "rejected", note))

    def expire_idea(self, idea_id: int, note: str = "expired before review") -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return self._with_business_brief(AlphaLabRepository(conn).set_approval_status(idea_id, "expired", note))

    def get_trade_explanation(self, idea_id: int) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            explanation = AlphaLabRepository(conn).get_trade_explanation(idea_id)
        if explanation is None:
            raise KeyError(f"trade explanation not found for idea {idea_id}")
        return explanation

    def regenerate_trade_explanation(self, idea_id: int) -> dict[str, Any]:
        """Rebuild and persist an idea's analyst explanation against a fresh price.

        Used to backfill numeric entry/stop/take-profit levels onto ideas whose
        stored explanation predates live-price grounding, without recreating the
        idea. Inserts a new explanation row, which supersedes the prior one.
        """
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            idea = repo.get_idea(idea_id)
            if idea is None:
                raise KeyError(f"idea {idea_id} not found")
            validation_price = self._validation_price(idea["ticker"])
            analyst_context = {**self._latest_briefing_context(conn), "reference_price": validation_price}
            explanation = build_trade_explanation({**idea, "id": idea_id}, analyst_context)
            return repo.create_trade_explanation(idea_id, explanation, {"regenerated": True})

    def sync_alpaca(self, dry_run: bool = True) -> dict[str, Any]:
        broker = self._broker(dry_run=dry_run)
        account = broker.get_account()
        positions = broker.get_positions()
        with connect(self.db_path) as conn:
            AlphaLabRepository(conn).sync_positions(positions)
        return {"account": account, "positions": positions, "dry_run": dry_run}

    def alpaca_health(self) -> dict[str, Any]:
        try:
            credentials = load_credentials_from_env()
            assert_paper = credentials.base_url == "https://paper-api.alpaca.markets"
            account = AlpacaClient(credentials).get_account()
            return {
                "ok": True,
                "paper_endpoint": assert_paper,
                "account_status": account.get("status"),
                "trading_blocked": account.get("trading_blocked"),
                "account_blocked": account.get("account_blocked"),
                "equity_present": "equity" in account,
                "issue": "",
                "recommendation": "Alpaca paper API is reachable from this network.",
            }
        except AlpacaSafetyError as exc:
            return {
                "ok": False,
                "paper_endpoint": False,
                "issue": str(exc),
                "recommendation": "Check ALPACA_API_KEY, ALPACA_SECRET_KEY, and ALPACA_PAPER_BASE_URL in .env.",
            }
        except (AlpacaAPIError, OSError) as exc:
            raw = str(exc)
            is_html_block = "<!DOCTYPE html>" in raw or "<html" in raw.lower()
            is_403 = " 403 " in raw or "failed: 403" in raw
            is_tls_intercept = "CERTIFICATE_VERIFY_FAILED" in raw or "self signed certificate" in raw.lower()
            if is_html_block and is_403:
                recommendation = "Network/proxy is returning an HTML block page. Use another network, hotspot/VPN, or allowlist paper-api.alpaca.markets."
            elif is_tls_intercept:
                recommendation = "TLS is being intercepted by this network. Use another network/hotspot/VPN or allowlist paper-api.alpaca.markets before sending paper orders."
            elif is_403:
                recommendation = "Alpaca returned 403. Regenerate paper API keys and confirm they are Trading API paper keys."
            else:
                recommendation = "Check network/DNS/TLS access to https://paper-api.alpaca.markets."
            return {
                "ok": False,
                "paper_endpoint": True,
                "issue": raw.splitlines()[0][:240],
                "looks_like_html_block": is_html_block,
                "recommendation": recommendation,
            }

    def dashboard(self) -> dict[str, Any]:
        account_error = ""
        positions = []
        try:
            broker = self._broker(dry_run=True)
            account = broker.get_account()
            try:
                positions = broker.get_positions()
            except (AlpacaAPIError, AlpacaSafetyError, OSError) as exc:
                account_error = str(exc).splitlines()[0][:220]
        except (AlpacaAPIError, AlpacaSafetyError, OSError) as exc:
            account_error = str(exc).splitlines()[0][:220]
            account = SimulatedPaperBroker().get_account()
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            ideas = repo.list_ideas(12)
            trades = repo.list_trades(12)
            stats = repo.strategy_stats()
            counts = repo.dashboard_counts()
            pending_approvals = repo.list_pending_approvals(12)
            catalyst_intelligence = repo.catalyst_intelligence_dashboard(12)
        return {
            "paper_account": account,
            "positions": positions,
            "recent_ideas": ideas,
            "recent_trades": trades,
            "strategy_stats": stats,
            "counts": counts,
            "pending_approvals": pending_approvals,
            "catalyst_intelligence": catalyst_intelligence,
            "mode": "dry-run default",
            "account_error": account_error,
        }

    def list_trades(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_trades()

    def strategy_stats(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).strategy_stats()

    def strategy_diagnostics(self) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            repo.ensure_trade_strategy_links()
            return repo.strategy_diagnostics()

    def list_execution_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_execution_audit(limit)

    def idea_performance(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = AlphaLabRepository(conn).list_idea_performance(limit)
        return [self._with_performance_marks(row) for row in rows]

    def strategy_scoreboard(self) -> dict[str, list[dict[str, Any]]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).strategy_scoreboard()

    def performance_report(self, recent_limit: int = 12) -> dict[str, Any]:
        """Alpha Report Card: signal-quality grades, source/regime leaderboards,
        recent graded signals, and the composite AlphaLabs IQ. Built from the same
        marked performance rows that back the idea-performance feed."""
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            rows = repo.list_idea_performance(1000)
            context = self._alpha_iq_context(repo)
        marked = [self._with_performance_marks(row) for row in rows]
        return build_performance_report(marked, recent_limit=recent_limit, context=context)

    def list_signal_evaluations(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_signal_evaluations(limit)

    def list_scanner_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).list_scanner_runs(limit)

    def catalyst_intelligence_dashboard(self, limit: int = 25) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return {
                "status": "ok",
                "source": "catalyst_intelligence",
                "dashboard": AlphaLabRepository(conn).catalyst_intelligence_dashboard(limit),
            }

    def evaluate_pending_signals(self, limit: int = 100) -> dict[str, Any]:
        """Evaluate stored signals against current live quotes without placing orders."""
        with connect(self.db_path) as conn:
            ideas = AlphaLabRepository(conn).list_ideas(limit)
        results = []
        for idea in ideas:
            try:
                results.append(self.evaluate_signal_quality(int(idea["id"])))
            except Exception as exc:
                results.append({"idea_id": idea.get("id"), "status": "error", "error": str(exc)})
        status_counts: dict[str, int] = {}
        for result in results:
            status = str(result.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {"evaluated": len(results), "status_counts": status_counts, "results": results}

    def evaluate_signal_quality(self, idea_id: int) -> dict[str, Any]:
        """Score whether a signal was early/useful, independent of trade P/L."""
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            idea = repo.get_idea(idea_id)
            try:
                existing = repo.get_signal_evaluation(idea_id)
            except KeyError:
                existing = {}
            alert_price = existing.get("alert_price") or self._validation_price(idea["ticker"])
            current_price = self._validation_price(idea["ticker"])
            base = self._initial_signal_evaluation(idea, alert_price)
            if not alert_price or not current_price:
                return repo.upsert_signal_evaluation(
                    idea_id,
                    {
                        **base,
                        "status": "price_unavailable",
                        "payload": {
                            "benchmark_status": "unavailable",
                            "reason": "No live quote was available from configured providers.",
                        },
                    },
                )
            move_after_pct = round(((float(current_price) - float(alert_price)) / float(alert_price)) * 100.0, 4)
            score = self._early_detection_score(idea, move_after_pct)
            return repo.upsert_signal_evaluation(
                idea_id,
                {
                    **base,
                    "alert_price": float(alert_price),
                    "price_after": float(current_price),
                    "move_after_pct": move_after_pct,
                    "benchmark_move_pct": None,
                    "early_detection_score": score,
                    "final_grade": self._grade_for_detection_score(score),
                    "status": "evaluated",
                    "evaluated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                    "payload": {
                        "benchmark_status": "unavailable",
                        "scoring_basis": "directional move after alert; benchmark not configured",
                    },
                },
            )

    def create_journal(self, payload: dict[str, Any]) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return AlphaLabRepository(conn).create_journal(payload)

    def _record_scanner_run(self, source: str, run_type: str, summary: dict[str, Any]) -> None:
        try:
            with connect(self.db_path) as conn:
                AlphaLabRepository(conn).log_scanner_run(source, run_type, summary)
        except Exception:
            return

    def _alpha_iq_context(self, repo: AlphaLabRepository) -> dict[str, Any]:
        futures = {"available": False, "regime": "unknown", "latest_at": ""}
        options = {"available": False, "samples": 0, "latest_at": ""}
        try:
            snapshots = repo.list_futures_snapshots(1)
            if snapshots:
                latest = snapshots[0]
                futures = {
                    "available": bool(latest.get("regime")),
                    "regime": latest.get("regime") or "unknown",
                    "latest_at": latest.get("created_at") or latest.get("generated_at") or "",
                }
        except Exception:
            pass
        try:
            option_runs = [run for run in repo.list_scanner_runs(100) if run.get("source") == "options_flow"]
            samples = sum(int((run.get("payload") or {}).get("responses_received") or 0) for run in option_runs)
            options = {
                "available": samples > 0,
                "samples": samples,
                "latest_at": option_runs[0].get("created_at", "") if option_runs else "",
            }
        except Exception:
            pass
        return {"futures": futures, "options": options}

    def _scanner_summary(
        self,
        *,
        candidates_found: int,
        ideas_persisted: int,
        rejected: int,
        skipped: int,
        reasons: dict[str, int],
        dry_run: bool,
        note: str = "",
    ) -> dict[str, Any]:
        top_reasons = [
            {"reason": reason, "count": int(count)}
            for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True)
            if int(count) > 0
        ][:5]
        return {
            "status": "ok",
            "candidates_found": max(0, int(candidates_found)),
            "ideas_persisted": max(0, int(ideas_persisted)),
            "rejected": max(0, int(rejected)),
            "skipped": max(0, int(skipped)),
            "top_rejection_reasons": top_reasons,
            "dry_run": dry_run,
            "note": note,
        }

    def _options_preview_watchlist(self, watchlist: list[str] | None = None) -> list[str]:
        raw = watchlist
        if raw is None:
            env_value = os.getenv("POLYGON_OPTIONS_WATCHLIST", "").strip()
            raw = env_value.split(",") if env_value else ["SPY", "QQQ", "NVDA"]
        symbols = []
        for item in raw:
            symbol = str(item).strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols[: max(1, min(len(symbols), int(os.getenv("POLYGON_OPTIONS_PREVIEW_LIMIT", "3") or 3)))]

    def _catalyst_source_accounting(self, payload: dict[str, Any]) -> dict[str, Any]:
        live_status = payload.get("live_status") or {}
        providers = live_status.get("providers") if isinstance(live_status, dict) else []
        problems = []
        responses = 0
        requests = 0
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                requests += 1
                status = str(provider.get("status") or "unknown")
                if status == "ok":
                    responses += 1
                else:
                    name = provider.get("name", "provider")
                    reason = provider.get("reason") or provider.get("error") or status
                    problems.append(f"{name}: {reason}")
        return {
            "enabled": payload.get("mode") == "live",
            "requests_attempted": requests,
            "responses_received": responses,
            "raw_items": len(payload.get("catalysts") or []),
            "candidates_filtered": max(0, len(payload.get("catalysts") or []) - len(payload.get("signals") or [])),
            "source_problems": problems[:8],
        }

    def _with_business_brief(self, idea: dict[str, Any]) -> dict[str, Any]:
        if idea.get("ticker"):
            return {**idea, "business_brief": get_business_brief(str(idea["ticker"]))}
        return idea

    def _recent_catalyst_theses(self) -> set[str]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT thesis FROM alpha_ideas
                WHERE source = 'catalyst_radar'
                ORDER BY datetime(created_at) DESC
                LIMIT 250
                """
            ).fetchall()
        return {str(row["thesis"]) for row in rows}

    def _recent_daily_brief_theses(self) -> set[str]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT thesis FROM alpha_ideas
                WHERE source = 'daily_market_brief'
                ORDER BY datetime(created_at) DESC
                LIMIT 250
                """
            ).fetchall()
        return {str(row["thesis"]) for row in rows}

    def _recent_crypto_theses(self) -> set[str]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT thesis FROM alpha_ideas
                WHERE source = 'after_hours_btc'
                ORDER BY datetime(created_at) DESC
                LIMIT 250
                """
            ).fetchall()
        return {str(row["thesis"]) for row in rows}

    def _friendly_broker_error(self, exc: Exception) -> str:
        raw = str(exc)
        if "paper-api.alpaca.markets" in raw and "blocked" in raw.lower():
            return "Alpaca paper endpoint is blocked by the current network policy; no paper order was placed."
        if "HTTP Error 403" in raw:
            return "Alpaca paper API returned 403 Forbidden; no paper order was placed."
        return raw.splitlines()[0][:220]

    def _broker(self, dry_run: bool):
        try:
            return AlpacaClient(load_credentials_from_env())
        except AlpacaSafetyError:
            if dry_run:
                return SimulatedPaperBroker()
            raise

    def _regular_equity_session_open(self) -> bool:
        now = datetime.now(ZoneInfo("America/New_York"))
        if now.weekday() >= 5:
            return False
        return time(9, 30) <= now.time() < time(16, 0)

    def _log_execution_attempt(
        self,
        idea_id: int,
        result: dict[str, Any],
        dry_run: bool,
        submitted_price: float | None = None,
    ) -> None:
        order_payload = result.get("order_payload") or {}
        response = result.get("order_response") or {}
        context = self._execution_context(dry_run)
        payload_for_log = {**order_payload, "_execution": context}
        response_for_log = {**response, "_execution": context}
        reasons = result.get("reasons") or []
        ticker = result.get("ticker") or order_payload.get("symbol") or "unknown"
        status = "submitted" if result.get("accepted") and not dry_run else result.get("action") or ("dry_run" if dry_run else "blocked")
        with connect(self.db_path) as conn:
            AlphaLabRepository(conn).log_execution_attempt(
                {
                    "idea_id": idea_id,
                    "ticker": ticker,
                    "side": order_payload.get("side") or result.get("side", ""),
                    "quantity": result.get("qty"),
                    "order_type": order_payload.get("type", ""),
                    "requested_entry": str(order_payload.get("notional") or result.get("notional") or ""),
                    "submitted_price": submitted_price or self._submitted_price(response),
                    "status": status,
                    "rejection_reason": "; ".join(str(reason) for reason in reasons),
                    "alpaca_order_id": response.get("id", ""),
                    "payload": payload_for_log,
                    "response": response_for_log,
                    "dry_run": dry_run,
                }
            )

    def _execution_context(self, dry_run: bool) -> dict[str, Any]:
        base_url = os.getenv("ALPACA_PAPER_BASE_URL", "").strip()
        mode = "paper" if base_url == "https://paper-api.alpaca.markets" else "unknown"
        return {
            "dry_run": bool(dry_run),
            "alpaca_mode": mode,
            "alpaca_base_url": base_url or "unset",
            "paper_endpoint": base_url == "https://paper-api.alpaca.markets",
        }

    def _submitted_price(self, response: dict[str, Any]) -> float | None:
        for key in ("filled_avg_price", "submitted_price", "limit_price"):
            value = response.get(key)
            if value not in {None, ""}:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    def _validation_price(self, ticker: str) -> float | None:
        """Best-effort live quote for signal validation; never uses simulated prices.

        Tries Polygon (needs a key), then Yahoo Finance (keyless, works on
        networks that block the broker API), then Alpaca. The Yahoo fallback
        means trade levels still populate when Polygon is unconfigured and Alpaca
        is unreachable (e.g. restrictive school/campus Wi-Fi).
        """
        snap = fetch_polygon_intraday(ticker)
        if snap.get("status") == "ok":
            price = snap.get("last_price")
            if isinstance(price, (int, float)) and price > 0:
                return float(price)
        yahoo = fetch_yahoo_price(ticker)
        if yahoo.get("status") == "ok":
            price = yahoo.get("last_price")
            if isinstance(price, (int, float)) and price > 0:
                return float(price)
        try:
            credentials = load_credentials_from_env()
            price = AlpacaClient(credentials).get_latest_trade_price(ticker)
            return float(price) if price else None
        except Exception:
            return None

    def _initial_signal_evaluation(self, idea: dict[str, Any], alert_price: float | None = None) -> dict[str, Any]:
        confidence = float(idea.get("confidence") or 0)
        return {
            "ticker": idea.get("ticker"),
            "source": idea.get("source") or "manual",
            "source_tags": idea.get("source_tags") or [],
            "generated_at": idea.get("timestamp") or idea.get("created_at"),
            "horizon": idea.get("timeframe") or "intraday",
            "direction": idea.get("bias") or "",
            "confidence": confidence,
            "market_regime": idea.get("market_regime") or "unknown",
            "catalyst": idea.get("catalyst") or "",
            "alert_price": alert_price,
            "provisional_grade": self._provisional_signal_grade(confidence, idea.get("catalyst")),
            "status": "provisional",
            "payload": {"benchmark_status": "unavailable"},
        }

    def _provisional_signal_grade(self, confidence: float, catalyst: Any) -> str:
        if confidence >= 0.85 and str(catalyst or "").strip():
            return "B"
        if confidence >= 0.7:
            return "C"
        if confidence >= 0.55:
            return "D"
        return "F"

    def _early_detection_score(self, idea: dict[str, Any], move_after_pct: float) -> float:
        bias = str(idea.get("bias") or "").lower()
        if bias == "bearish":
            directional_move = -move_after_pct
        elif bias == "bullish":
            directional_move = move_after_pct
        else:
            directional_move = abs(move_after_pct)
        confidence = max(0.0, min(1.0, float(idea.get("confidence") or 0)))
        direction_points = 40.0 if directional_move > 0 else 0.0
        magnitude_points = max(0.0, min(40.0, directional_move * 8.0))
        confidence_points = confidence * 20.0
        return round(direction_points + magnitude_points + confidence_points, 1)

    def _grade_for_detection_score(self, score: float | None) -> str | None:
        if score is None:
            return None
        if score >= 85:
            return "A"
        if score >= 70:
            return "B"
        if score >= 55:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    def _latest_price(self, ticker: str) -> float | None:
        try:
            return self._broker(dry_run=True).get_latest_trade_price(ticker)
        except Exception:
            return None

    def _equity_market_open(self) -> bool:
        try:
            broker = self._broker(dry_run=True)
            if isinstance(broker, SimulatedPaperBroker) and not broker.market_open_explicit:
                return self._regular_equity_session_open()
            return bool(broker.get_clock().get("is_open"))
        except Exception:
            return False

    def _safe_market_payload(self, fn) -> dict[str, Any]:
        try:
            return fn()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc)}

    def _btc_signal_from_market(self, btc: dict[str, Any]) -> dict[str, Any]:
        ticker = btc.get("ticker") or "BTC/USD"
        symbol = btc.get("symbol") or ticker.split("/")[0]
        name = btc.get("name") or symbol
        indicators = btc.get("indicators", {}) or {}
        price = float(btc.get("price") or 0)
        ema20 = indicators.get("ema20")
        support = indicators.get("support_14d_close")
        resistance = indicators.get("resistance_14d_close")
        bias = btc.get("bias") if btc.get("bias") in {"bullish", "bearish"} else "neutral"
        if bias == "neutral" and price and ema20:
            bias = "bullish" if price > float(ema20) else "bearish"
        confidence = 0.78 if bias in {"bullish", "bearish"} else 0.62
        entry = self._entry_zone(price, bias, support, resistance, ema20)
        stop = self._stop_level(price, bias, support, resistance, ema20)
        target = self._target_level(price, bias, support, resistance, ema20)
        invalidation = (
            f"Invalidate bullish thesis below {self._fmt_price(stop)}."
            if bias == "bullish"
            else f"Invalidate bearish thesis above {self._fmt_price(stop)}."
            if bias == "bearish"
            else f"Invalidate if {symbol} fails to create a directional reclaim/rejection setup."
        )
        thesis = (
            f"{symbol} after-hours {bias} setup: {btc.get('summary', f'{symbol} market context unavailable')} "
            f"{indicators.get('ema_read', '')} Entry {entry}; stop {self._fmt_price(stop)}; target {self._fmt_price(target)}; {invalidation}"
        )
        catalyst = (
            f"24h volume {btc.get('volume_24h')}; 24h change {btc.get('change_24h_pct')}%; "
            f"support {self._fmt_price(support)}, resistance {self._fmt_price(resistance)}."
        )
        return {
            "ticker": ticker,
            "asset_type": "crypto",
            "bias": bias,
            "confidence": confidence,
            "timeframe": "intraday",
            "thesis": thesis,
            "reason": thesis,
            "catalyst": catalyst,
            "source": "after_hours_btc",
            "timestamp": btc.get("fetched_at") or btc.get("last_updated"),
            "strategy_tags": ["crypto momentum", f"{symbol} breakout", "after-hours crypto"],
            "theme": f"After-Hours {symbol}",
            "source_refs": [{"label": btc.get("source", "CoinGecko"), "url": "", "timestamp": btc.get("last_updated", "")}],
        }

    def _entry_zone(self, price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> str:
        anchor = resistance if bias == "bullish" else support if bias == "bearish" else ema20 or price
        return f"near {self._fmt_price(anchor)} with confirmation; current {self._fmt_price(price)}"

    def _stop_level(self, price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> float:
        if bias == "bullish":
            return float(support or ema20 or price * 0.97)
        if bias == "bearish":
            return float(resistance or ema20 or price * 1.03)
        return float(ema20 or price)

    def _target_level(self, price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> float:
        if bias == "bullish":
            return float(resistance or price * 1.06)
        if bias == "bearish":
            return float(support or price * 0.94)
        return float(resistance or support or ema20 or price)

    def _fmt_price(self, value: Any) -> str:
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "n/a"

    def _crypto_approval_summary(self, ideas: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "pending": len([idea for idea in ideas if idea.get("status") == "needs_review"]),
            "approved": len([idea for idea in ideas if idea.get("status") == "approved"]),
            "new": len([idea for idea in ideas if idea.get("status") == "new"]),
        }

    def _crypto_risk_status(self) -> dict[str, Any]:
        config = load_config(self.risk_config_path, profile="crypto")
        return {
            "max_trades_per_day": config.max_trades_per_day,
            "max_position_size_usd": config.max_position_size_usd,
            "max_daily_drawdown_pct": config.max_daily_drawdown_pct,
            "approved_tickers": sorted(config.approved_tickers),
        }

    def _with_performance_marks(self, row: dict[str, Any]) -> dict[str, Any]:
        entry = row.get("entry_price")
        current = self._latest_price(row["ticker"]) if row.get("trade_id") else None
        if current is None:
            current = row.get("exit_price") or entry
        quantity = float(row.get("quantity") or 0)
        notional = float(row.get("notional") or 0)
        side = row.get("side") or ""
        unrealized = float(row.get("unrealized_pl") or 0)
        if entry and current and quantity:
            move = (float(current) - float(entry)) * quantity
            unrealized = -move if side == "sell" else move
        percent_return = 0.0
        basis = notional or (float(entry or 0) * quantity)
        total_pl = float(row.get("realized_pl") or 0) + unrealized
        if basis:
            percent_return = round(total_pl / basis * 100, 4)
        explanation = row.get("trade_explanation") or {}
        return {
            **row,
            "current_price": current,
            "unrealized_pl": round(unrealized, 4),
            "percent_return": percent_return,
            "stop_target_status": self._stop_target_status(percent_return, row, explanation),
            "thesis_summary": explanation.get("thesis_summary", row.get("thesis", "")),
        }

    def _stop_target_status(self, percent_return: float, row: dict[str, Any], explanation: dict[str, Any]) -> str:
        if row.get("closed_at"):
            return "closed"
        if not row.get("trade_id"):
            return "not executed"
        if percent_return <= -3:
            return "stop watch"
        if percent_return >= 5:
            return "target watch"
        return "open"

    def _paper_execution_approval_error(self, idea_id: int) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            repo = AlphaLabRepository(conn)
            explanation = repo.get_trade_explanation(idea_id)
            idea = repo.get_idea(idea_id)
            asset_type = str(idea.get("asset_type", "equity"))
            if not explanation or (not explanation.get("analyst_assisted") and asset_type != "crypto"):
                return None
            status = repo.approval_status_for_idea(idea_id)
            if status in {"rejected", "expired"}:
                idea = repo.get_idea(idea_id)
                return {
                    "accepted": False,
                    "action": f"approval_{status}",
                    "reasons": [f"LLM-assisted signal was {status}; no Alpaca paper order was placed."],
                    "ticker": idea.get("ticker"),
                    "notional": None,
                    "qty": None,
                    "order_payload": None,
                    "order_response": {"submitted": False, "message": "No Alpaca paper order was placed."},
                }
            if not self._paper_approval_required():
                return None
            if status == "approved":
                return None
            return {
                "accepted": False,
                "action": "needs_human_approval",
                "reasons": [f"{asset_type.title()} signal requires human approval before Alpaca paper execution."],
                "ticker": idea.get("ticker"),
                "notional": None,
                "qty": None,
                "order_payload": None,
                "order_response": {"submitted": False, "message": "No Alpaca paper order was placed."},
            }

    def _paper_approval_required(self) -> bool:
        return os.getenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "true").strip().lower() not in FALSE_ENV_VALUES

    def _latest_briefing_context(self, conn) -> dict[str, Any]:
        briefings = AlphaLabRepository(conn).list_market_briefings(1)
        if not briefings:
            return {}
        payload = briefings[0].get("payload", {})
        return {
            "headline": payload.get("broad_market_tone", ""),
            "market_context": payload.get("broad_market_tone", ""),
            "source": "stored_market_briefing",
            "generated_at": payload.get("generated_at", ""),
        }

    def _current_market_regime(self, repo: AlphaLabRepository) -> str:
        """Regime posture in force right now, stamped on each new signal.

        Reads the most recent saved market briefing (the scheduler regenerates
        these) and uses its ``broad_market_tone`` — the same defensive / risk-on
        watch / mixed posture computed by the daily brief. Falls back to
        ``unknown`` when no briefing has been generated yet.
        """
        try:
            briefings = repo.list_market_briefings(1)
        except Exception:
            return "unknown"
        if not briefings:
            return "unknown"
        tone = str(briefings[0].get("payload", {}).get("broad_market_tone") or "").strip().lower()
        return tone or "unknown"

    def _signal_from_idea(self, idea: dict[str, Any], as_option: bool = False) -> Signal:
        # For an option trade the underlying ticker still drives the risk checks
        # (approved watchlist, market-open), but the asset_type flips to "option"
        # so the engine builds a contract order instead of an equity order.
        asset_type = "option" if as_option else idea.get("asset_type", "equity")
        return Signal.from_dict(
            {
                "ticker": idea["ticker"],
                "bias": idea["bias"],
                "confidence": idea["confidence"],
                "timeframe": idea["timeframe"],
                "asset_type": asset_type,
                "reason": idea["thesis"],
                "source": idea["source"],
                "timestamp": idea["timestamp"],
            }
        )

    def _select_option_contract(self, idea: dict[str, Any]) -> dict[str, Any]:
        # Phase-1: nearest-expiry ATM call (bullish) / put (bearish) on the
        # underlying. Raises OptionSelectionError if nothing passes the liquidity
        # guards; place_trade turns that into a clean "no_option_contract" result.
        return select_atm_contract(idea["ticker"], idea["bias"])


def reset_local_data(db_path: str | None = None) -> None:
    # Resolve through the shared precedence chain so a no-arg call targets the
    # SAME database the service/scheduler use — never the bare relative default.
    path = Path(resolve_db_path(db_path))
    if path.exists():
        path.unlink()
    init_db(str(path))
