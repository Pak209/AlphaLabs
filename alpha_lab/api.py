from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent_status import build_agent_status
from .catalysts import get_catalyst_radar, import_catalysts_payload
from .market_data import get_bitcoin_market, get_business_profiles, get_liquidity_flows, get_oil_market, get_trending_stocks
from .notifications import ALERT_LEVELS, NotificationCenter, clamp_limit, public_vapid_key
from .scheduler import scheduler_safety_status
from .service import AlphaLabService


FALSE_VALUES = {"0", "false", "no", "off"}
TRUE_VALUES = {"1", "true", "yes", "on"}


def _bool_param(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in FALSE_VALUES:
            return False
        if normalized in TRUE_VALUES:
            return True
    return bool(value)


def create_app(service: AlphaLabService | None = None) -> FastAPI:
    app = FastAPI(title="Alpha Lab", version="0.1.0")
    lab = service or AlphaLabService()
    notifications = NotificationCenter(db_path=lab.db_path)
    static_dir = Path(__file__).parent / "static"

    @app.middleware("http")
    async def require_token_for_writes(request: Request, call_next):
        """Gate every mutating request behind a shared bearer token.

        Opt-in: with ALPHALAB_API_TOKEN unset the API is fully open (localhost
        dev / current behavior). When set, any non-GET request (every approve /
        paper-trade / import / chat endpoint) must send
        'Authorization: Bearer <token>'. Reads stay open so the dashboard still
        renders. This is defense-in-depth on top of network-level auth
        (Tailscale) before anything can approve or place a paper trade remotely.
        """
        token = os.getenv("ALPHALAB_API_TOKEN", "").strip()
        if token and request.method not in ("GET", "HEAD", "OPTIONS"):
            provided = request.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            if not (provided and hmac.compare_digest(provided, expected)):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized: missing or invalid API token."})
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        # Expose the resolved DB identity (path + device:inode) so a health check
        # can PROVE the dashboard and scheduler are reading/writing the SAME file,
        # not just two same-named DBs. Identity errors must never down the probe.
        try:
            identity = lab.db_identity()
        except Exception as exc:  # pragma: no cover - defensive
            identity = {"db_error": str(exc)}
        return {"status": "ok", "mode": "paper-research", "default_execution": "dry-run", **identity}

    @app.get("/api/db-status")
    def db_status() -> dict[str, Any]:
        # Full operational snapshot of the active database for dashboards / phone:
        # path, existence, idea + trade counts, and the scheduler heartbeat.
        return lab.db_status()

    @app.get("/api/safety-status")
    def safety_status() -> dict[str, Any]:
        return scheduler_safety_status()

    @app.get("/api/ops/agent-status")
    def agent_status(limit: int = 50) -> dict[str, Any]:
        return build_agent_status(lab.db_path, limit=limit)

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return lab.dashboard()

    @app.get("/api/market/bitcoin")
    def bitcoin_market() -> dict[str, Any]:
        try:
            return get_bitcoin_market()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "CoinGecko"}

    @app.get("/api/after-hours/btc")
    def after_hours_btc() -> dict[str, Any]:
        try:
            return lab.after_hours_btc()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab After-Hours BTC"}

    @app.post("/api/after-hours/btc/generate")
    def generate_after_hours_btc_idea() -> dict[str, Any]:
        try:
            return lab.generate_after_hours_btc_idea()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/market/liquidity")
    def liquidity_flows() -> dict[str, Any]:
        try:
            return get_liquidity_flows()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab liquidity proxy"}

    @app.get("/api/market/trending-stocks")
    def trending_stocks(limit: int = 12) -> dict[str, Any]:
        try:
            return get_trending_stocks(limit=limit)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab trending stock proxy"}

    @app.get("/api/market/oil")
    def oil_market() -> dict[str, Any]:
        try:
            return get_oil_market()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab oil/energy proxy"}

    @app.get("/api/business-profiles")
    def business_profiles() -> dict[str, Any]:
        try:
            return get_business_profiles()
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab curated profiles"}

    @app.get("/api/catalysts/radar")
    def catalyst_radar(live: bool = True) -> dict[str, Any]:
        try:
            return get_catalyst_radar(live=live)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab Catalyst Radar"}

    @app.post("/api/catalysts/score")
    def score_catalysts(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return get_catalyst_radar(payload, live=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/catalysts/import-and-test")
    def import_and_test_catalysts(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        execution_mode = str(body.get("execution_mode", "dry_run")).strip().lower()
        try:
            imported = import_catalysts_payload(body)
            result = lab.import_and_test({**imported, "execution_mode": execution_mode})
            return {**imported, "test_result": result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/catalysts/intelligence")
    def catalyst_intelligence(live: bool = False, persist: bool = True) -> dict[str, Any]:
        try:
            if not live:
                return lab.catalyst_intelligence_dashboard()
            return lab.catalyst_intelligence(live=live, persist=persist, generate_ideas=False)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab Catalyst Intelligence"}

    @app.post("/api/catalysts/intelligence")
    def run_catalyst_intelligence(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        live = _bool_param(body.get("live"), default=False)
        persist = _bool_param(body.get("persist"), default=True)
        generate_ideas = _bool_param(body.get("generate_ideas"), default=False)
        dry_run = _bool_param(body.get("dry_run"), default=True)
        try:
            return lab.catalyst_intelligence(
                payload=body if body.get("catalysts") or body.get("items") or body.get("ticker") else None,
                live=live,
                persist=persist,
                generate_ideas=generate_ideas,
                dry_run=dry_run,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/catalysts/poll")
    def poll_live_catalysts(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        dry_run = _bool_param(body.get("dry_run"), default=True)
        try:
            return lab.poll_live_catalysts(dry_run=dry_run)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/futures/pulse")
    def futures_pulse(session_date: Optional[str] = None, catalyst_ts: Optional[str] = None,
                      persist: bool = True) -> dict[str, Any]:
        # Read-only premarket Overnight Futures Pulse. Never places a trade.
        try:
            return lab.futures_pulse(session_date=session_date, catalyst_ts=catalyst_ts, persist=persist)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab Overnight Futures Pulse"}

    @app.get("/api/futures/snapshots")
    def futures_snapshots(limit: int = 30) -> list[dict[str, Any]]:
        return lab.list_futures_snapshots(limit)

    @app.get("/api/options/flow-preview")
    def options_flow_preview(session_date: Optional[str] = None) -> dict[str, Any]:
        try:
            return lab.run_options_flow_preview(session_date=session_date)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab Options Flow Preview"}

    @app.get("/api/brief/daily")
    def daily_brief(live_catalysts: bool = True) -> dict[str, Any]:
        try:
            return lab.build_daily_brief(live_catalysts=live_catalysts)
        except Exception as exc:
            return {"status": "unavailable", "error": str(exc), "source": "AlphaLab Daily Market Brief"}

    @app.post("/api/brief/daily/import-and-test")
    def import_daily_brief(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        dry_run = _bool_param(body.get("dry_run"), default=True)
        live_catalysts = _bool_param(body.get("live_catalysts"), default=True)
        try:
            return lab.import_daily_brief_and_test(dry_run=dry_run, live_catalysts=live_catalysts)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/briefings/daily/generate")
    def generate_daily_briefing(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        live_catalysts = _bool_param(body.get("live_catalysts"), default=True)
        try:
            return lab.generate_and_save_market_briefing(live_catalysts=live_catalysts)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/briefings")
    def list_market_briefings(limit: int = 20) -> list[dict[str, Any]]:
        return lab.list_market_briefings(limit)

    @app.post("/api/ideas")
    def submit_idea(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return lab.create_idea(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ideas/import")
    def import_ideas(payload: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return lab.import_ideas(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ideas/import-and-test")
    def import_and_test(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return lab.import_and_test(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ideas/test-new")
    def test_new_ideas(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        dry_run = True if payload is None else _bool_param(payload.get("dry_run"), default=True)
        try:
            return lab.test_new_ideas(dry_run=dry_run)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/strategies/test-trending")
    def test_trending_strategies(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        dry_run = _bool_param(body.get("dry_run"), default=True)
        limit = int(body.get("limit", 3))
        try:
            return lab.test_trending_strategies(dry_run=dry_run, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/ideas")
    def list_ideas(limit: int = 100) -> list[dict[str, Any]]:
        return lab.list_ideas(limit)

    @app.get("/api/ideas/pending-approval")
    def pending_approvals(limit: int = 100) -> list[dict[str, Any]]:
        return lab.list_pending_approvals(limit)

    @app.get("/api/ideas/{idea_id}/explanation")
    def trade_explanation(idea_id: int) -> dict[str, Any]:
        try:
            return lab.get_trade_explanation(idea_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ideas/{idea_id}/explanation/regenerate")
    def regenerate_explanation(idea_id: int) -> dict[str, Any]:
        try:
            return lab.regenerate_trade_explanation(idea_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ideas/{idea_id}/approve")
    def approve_idea(idea_id: int) -> dict[str, Any]:
        return lab.set_idea_status(idea_id, "accepted")

    @app.post("/api/ideas/{idea_id}/reject")
    def reject_idea(idea_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return lab.set_idea_status(idea_id, "rejected", str(payload.get("reason", "manual rejection")))

    @app.post("/api/ideas/{idea_id}/approval/approve")
    def approve_idea_for_execution(idea_id: int, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        return lab.approve_idea_for_execution(idea_id, str(body.get("note", "")))

    @app.post("/api/ideas/{idea_id}/approval/reject")
    def reject_idea_for_execution(idea_id: int, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        return lab.reject_idea_for_execution(idea_id, str(body.get("note", "rejected by reviewer")))

    @app.post("/api/ideas/{idea_id}/approval/expire")
    def expire_idea(idea_id: int, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = payload or {}
        return lab.expire_idea(idea_id, str(body.get("note", "expired before review")))

    @app.post("/api/ideas/{idea_id}/decision")
    def run_decision(idea_id: int) -> dict[str, Any]:
        try:
            return lab.run_decision(idea_id, dry_run=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ideas/{idea_id}/dry-run-trade")
    def place_dry_run_trade(idea_id: int, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        as_option = _bool_param((payload or {}).get("as_option"), default=False)
        try:
            return lab.place_trade(idea_id, dry_run=True, as_option=as_option)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ideas/{idea_id}/paper-trade")
    def place_paper_trade(idea_id: int, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        as_option = _bool_param((payload or {}).get("as_option"), default=False)
        try:
            return lab.place_trade(idea_id, dry_run=False, as_option=as_option)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/alpaca/sync")
    def sync_alpaca(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        dry_run = True if payload is None else _bool_param(payload.get("dry_run"), default=True)
        try:
            return lab.sync_alpaca(dry_run=dry_run)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/alpaca/health")
    def alpaca_health() -> dict[str, Any]:
        return lab.alpaca_health()

    @app.get("/api/trades")
    def list_trades() -> list[dict[str, Any]]:
        return lab.list_trades()

    @app.get("/api/execution-audit")
    def execution_audit(limit: int = 100) -> list[dict[str, Any]]:
        return lab.list_execution_audit(limit)

    @app.get("/api/performance/ideas")
    def idea_performance(limit: int = 100) -> list[dict[str, Any]]:
        return lab.idea_performance(limit)

    @app.get("/api/performance/scoreboard")
    def performance_scoreboard() -> dict[str, list[dict[str, Any]]]:
        return lab.strategy_scoreboard()

    @app.get("/api/performance/report")
    def performance_report(recent_limit: int = 12) -> dict[str, Any]:
        return lab.performance_report(recent_limit=recent_limit)

    @app.get("/api/signals/evaluations")
    def signal_evaluations(limit: int = 100) -> list[dict[str, Any]]:
        return lab.list_signal_evaluations(limit)

    @app.post("/api/signals/evaluate")
    def evaluate_signals(limit: int = 100) -> dict[str, Any]:
        return lab.evaluate_pending_signals(limit)

    @app.get("/api/stats/strategies")
    def strategy_stats() -> list[dict[str, Any]]:
        return lab.strategy_stats()

    @app.get("/api/stats/strategies/diagnostics")
    def strategy_diagnostics() -> dict[str, Any]:
        return lab.strategy_diagnostics()

    @app.post("/api/journal")
    def create_journal(payload: dict[str, Any]) -> dict[str, Any]:
        return lab.create_journal(payload)

    @app.post("/api/config")
    def update_config(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "received", "note": "Config persistence is intentionally minimal in MVP", "payload": payload}

    @app.post("/api/chat")
    def analyst_chat(payload: dict[str, Any]) -> dict[str, Any]:
        # Advisory, read-only markets chat. Grounded in live AlphaLab context;
        # has no path to place or approve a trade.
        message = str(payload.get("message", "")).strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        return lab.analyst_chat(message, history=history)

    # --- notifications: alerts, preferences, push, test-mode ----------------- #
    @app.get("/api/alerts")
    def list_alerts(limit: int = 100, status: Optional[str] = None) -> dict[str, Any]:
        try:
            return notifications.list_alerts(limit=limit, status=status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/alerts/levels")
    def alert_levels() -> dict[str, Any]:
        return {"levels": ALERT_LEVELS}

    @app.get("/api/alerts/{alert_id}")
    def get_alert(alert_id: int) -> dict[str, Any]:
        try:
            return notifications.get_alert(alert_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/alerts/{alert_id}/status")
    def set_alert_status(alert_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return notifications.set_alert_status(alert_id, str(payload.get("status", "")))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/notifications/audit")
    def notification_audit(limit: int = 100) -> list[dict[str, Any]]:
        return notifications.list_audit(clamp_limit(limit))

    @app.get("/api/notifications/preferences")
    def get_notification_preferences() -> dict[str, Any]:
        return notifications.get_preferences()

    @app.post("/api/notifications/preferences")
    def update_notification_preferences(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return notifications.update_preferences(payload or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/notifications/vapid-public-key")
    def vapid_public_key() -> dict[str, Any]:
        # Public key only, normalized to the base64url form the browser Push API
        # requires (accepts a legacy hex-stored key too). The private key never
        # leaves the server.
        return {"public_key": public_vapid_key()}

    @app.post("/api/notifications/subscribe")
    def subscribe_push(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return notifications.save_subscription(payload or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/notifications/unsubscribe")
    def unsubscribe_push(payload: dict[str, Any]) -> dict[str, Any]:
        return notifications.remove_subscription(str((payload or {}).get("endpoint", "")))

    @app.post("/api/notifications/test")
    def create_test_alert(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        # Test-mode: create one alert at the requested level and run dispatch.
        #
        # SAFE BY DEFAULT: this endpoint always runs in dry-run (audited, nothing
        # sent). A REAL send (force_dry_run=false) is refused unless the operator has
        # set ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=true on the server — so the normal
        # API can never push an arbitrary real SMS/push. Inputs are strictly validated
        # and bounded; unknown payload fields are rejected.
        body = payload or {}
        allowed_fields = {"level", "title", "body", "source", "force_dry_run"}
        unknown = set(body) - allowed_fields
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown fields: {sorted(unknown)}")

        level = str(body.get("level", "WATCH")).strip().upper()
        if level not in ALERT_LEVELS:
            raise HTTPException(status_code=400, detail=f"level must be one of {ALERT_LEVELS}")

        title = str(body.get("title") or f"Test {level} alert")[:140]
        body_text = str(body.get("body") or "Synthetic alert from /api/notifications/test")[:600]
        source = str(body.get("source") or "test-mode")[:80]

        allow_real = os.getenv("ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS", "").strip().lower() in TRUE_VALUES
        raw_force = body.get("force_dry_run")
        if raw_force is None:
            force = True  # default: dry-run only
        elif _bool_param(raw_force, default=True):
            force = True  # explicit dry-run
        else:
            # Caller asked for a real send; gate it behind the explicit env opt-in.
            if not allow_real:
                raise HTTPException(
                    status_code=403,
                    detail="real test sends are disabled; set ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=true to enable",
                )
            force = False

        return notifications.create_and_dispatch(
            level=level,
            title=title,
            body=body_text,
            source=source,
            force_dry_run=force,
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        # Served from root so the service worker's scope is "/" (the whole app),
        # not "/static". Must not be cached by the browser or stale SW code sticks.
        return FileResponse(
            static_dir / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


app = create_app()
