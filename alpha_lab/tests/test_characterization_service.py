"""Phase 0 characterization tests — freeze the current public contract.

These tests pin what `AlphaLabService` and the decision path *currently* do so
the Phase 1+ refactors in docs/ARCHITECTURE.md §6 can prove behavior is
unchanged. They are diagnostics only:

- Pinned surface: every public member of AlphaLabService with its exact
  parameter list. Removing or re-signing a member fails; ADDING one does not.
- Golden payload shapes: rejection_waterfall() and serialize_decision() —
  the two telemetry payloads every downstream reader (waterfall snapshots,
  research frames, dashboards) depends on.
- Schema spine: the tables/columns the telemetry readers join on.

If one of these tests fails, the correct response is usually to fix the code
change that broke the contract — not to update the golden values. Update the
goldens only for a deliberate, human-approved contract change, in the same
commit, with a handoff entry.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from alpha_lab.database import connect
from alpha_lab.service import AlphaLabService
from paper_trader.audit_log import AuditLog
from paper_trader.decision_engine import BrokerState, evaluate_signal, serialize_decision
from paper_trader.models import RiskConfig, Signal


# ── 1. Public surface freeze ────────────────────────────────────────────────
# Captured 2026-07-04 (56 members). Method name → parameter names in order.
# "<property>" marks properties. Additions are allowed; removals and signature
# changes are not (they break api.py, scheduler.py, seed.py, and 3 scripts).
PINNED_SURFACE: dict[str, list[str]] = {
    "after_hours_btc": ["self"],
    "alpaca_health": ["self"],
    "analyst_chat": ["self", "message", "history"],
    "approve_idea_for_execution": ["self", "idea_id", "note"],
    "build_daily_brief": ["self", "live_catalysts"],
    "catalyst_intelligence": ["self", "payload", "live", "persist", "generate_ideas", "dry_run"],
    "catalyst_intelligence_dashboard": ["self", "limit"],
    "close_option_trade": ["self", "trade_id"],
    "create_idea": ["self", "payload"],
    "create_journal": ["self", "payload"],
    "dashboard": ["self"],
    "db_identity": ["self"],
    "db_status": ["self"],
    "evaluate_pending_signals": ["self", "limit"],
    "evaluate_signal_quality": ["self", "idea_id"],
    "expire_idea": ["self", "idea_id", "note"],
    "futures_pulse": ["self", "session_date", "catalyst_ts", "persist", "score_signals", "provider"],
    "generate_after_hours_btc_idea": ["self"],
    "generate_after_hours_crypto_ideas": ["self"],
    "generate_and_save_market_briefing": ["self", "live_catalysts"],
    "get_scheduler_heartbeat": ["self"],
    "get_trade_explanation": ["self", "idea_id"],
    "idea_performance": ["self", "limit"],
    "import_and_test": ["self", "payload"],
    "import_daily_brief_and_test": ["self", "dry_run", "live_catalysts"],
    "import_ideas": ["self", "payload"],
    "list_execution_audit": ["self", "limit"],
    "list_futures_snapshots": ["self", "limit"],
    "list_ideas": ["self", "limit"],
    "list_market_briefings": ["self", "limit"],
    "list_pending_approvals": ["self", "limit"],
    "list_scanner_runs": ["self", "limit"],
    "list_signal_evaluations": ["self", "limit"],
    "list_trades": ["self"],
    "notifications": ["<property>"],
    "performance_report": ["self", "recent_limit"],
    "place_trade": ["self", "idea_id", "dry_run", "as_option"],
    "poll_live_catalysts": ["self", "dry_run"],
    "poll_weekend_crypto": ["self", "dry_run"],
    "record_scheduler_heartbeat": ["self", "label"],
    "refresh_option_entry_fill": ["self", "trade_id"],
    "regenerate_trade_explanation": ["self", "idea_id"],
    "reject_idea_for_execution": ["self", "idea_id", "note"],
    "rejection_waterfall": ["self", "limit"],
    "review_briefing": ["self", "limit"],
    "review_opportunity": ["self", "idea_id"],
    "run_decision": ["self", "idea_id", "dry_run", "as_option"],
    "run_options_flow_preview": ["self", "watchlist", "session_date", "provider"],
    "run_overnight_futures_pull": ["self", "session_date", "catalyst_ts"],
    "set_idea_status": ["self", "idea_id", "status", "reason"],
    "strategy_diagnostics": ["self"],
    "strategy_scoreboard": ["self"],
    "strategy_stats": ["self"],
    "sync_alpaca": ["self", "dry_run"],
    "test_new_ideas": ["self", "dry_run"],
    "test_trending_strategies": ["self", "dry_run", "limit"],
}

PINNED_CONSTRUCTOR = ["self", "db_path", "risk_config_path", "audit_log_path",
                      "options_flow_provider", "dark_pool_provider", "futures_data_provider"]


def test_service_public_surface_is_frozen():
    for name, pinned_params in PINNED_SURFACE.items():
        member = inspect.getattr_static(AlphaLabService, name, None)
        assert member is not None, (
            f"AlphaLabService.{name} was removed — it is pinned by Phase 0 "
            f"(docs/ARCHITECTURE.md §6 Phase 0); entry points may depend on it."
        )
        if pinned_params == ["<property>"]:
            assert isinstance(member, property), f"AlphaLabService.{name} is no longer a property"
            continue
        actual = list(inspect.signature(member).parameters)
        assert actual == pinned_params, (
            f"AlphaLabService.{name} signature changed: {actual} != pinned {pinned_params}"
        )


def test_service_constructor_signature_is_frozen():
    actual = list(inspect.signature(AlphaLabService.__init__).parameters)
    assert actual == PINNED_CONSTRUCTOR


# ── 2. rejection_waterfall() golden payload ─────────────────────────────────

@pytest.fixture()
def waterfall_service(tmp_path):
    """Service on a fresh DB with a hand-built population covering structured
    accepted/rejected rows, an advisory gate record, a near miss, a legacy
    free-text row, scanner accounting, and one paper trade."""
    service = AlphaLabService(
        db_path=str(tmp_path / "char.sqlite3"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    with connect(service.db_path) as conn:
        for i in range(4):
            conn.execute(
                """
                INSERT INTO alpha_ideas (ticker, bias, confidence, timeframe, thesis,
                                         source, status, timestamp)
                VALUES (?, 'bullish', 0.8, 'swing', 'characterization', 'catalyst_radar',
                        'new', '2026-07-01T14:00:00+00:00')
                """,
                (f"CHR{i}",),
            )
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json) VALUES (?, ?, ?)",
            ("catalyst_radar", "poll",
             json.dumps({"candidates_found": 10,
                         "top_rejection_reasons": [{"reason": "not trade candidate", "count": 7}]})),
        )

        def audit(idea_id, status, reason, payload, created_at):
            conn.execute(
                """
                INSERT INTO execution_audit (idea_id, ticker, status, rejection_reason,
                                             payload_json, dry_run, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (idea_id, f"CHR{idea_id - 1}", status, reason, json.dumps(payload), created_at),
            )

        def gate(name, passed, observed, threshold, **extra):
            return {"stage": "risk_engine", "gate": name, "passed": passed,
                    "observed": observed, "threshold": threshold,
                    "comparator": ">=", "detail": "" if passed else f"{name} failed", **extra}

        # Accepted dry-run; advisory alpha gate fails as a near miss (65 vs 70).
        audit(1, "dry_run", "", {
            "_gates": [gate("confidence", True, 0.82, 0.75),
                       gate("market_open", True, True, True),
                       gate("alpha_composite_tier", False, 65.0, 70.0, enforced=False)],
            "_first_failed_gate": None,
        }, "2026-07-01T15:00:00+00:00")
        # Accepted and submitted; alpha gate passes.
        audit(2, "submitted", "", {
            "_gates": [gate("confidence", True, 0.9, 0.75),
                       gate("alpha_composite_tier", True, 78.0, 70.0)],
            "_first_failed_gate": None,
        }, "2026-07-01T15:01:00+00:00")
        # Structured rejection: confidence near miss (0.71 vs 0.75, margin 0.075).
        audit(3, "rejected", "confidence 0.71 below threshold 0.75", {
            "_gates": [gate("confidence", False, 0.71, 0.75)],
            "_first_failed_gate": "confidence",
        }, "2026-07-01T15:02:00+00:00")
        # Legacy free-text rejection: two clauses, first-clause attribution.
        audit(4, "rejected",
              "confidence 0.60 below threshold 0.75; ticker is not in approved watchlist",
              {}, "2026-07-01T15:03:00+00:00")

        conn.execute(
            "INSERT INTO trades (idea_id, ticker, side, status, dry_run) VALUES (2, 'CHR1', 'buy', 'open', 0)"
        )
        conn.commit()
    return service


def _bucket(report: dict[str, Any], gate: str) -> dict[str, Any]:
    match = [b for b in report["gate_failures"] if b["gate"] == gate]
    assert match, f"gate bucket {gate!r} missing from waterfall"
    return match[0]


def test_rejection_waterfall_golden_payload(waterfall_service):
    report = waterfall_service.rejection_waterfall()

    assert set(report) == {"status", "generated_at", "window", "stage_funnel",
                           "gate_failures", "first_failed_gates", "threshold_impact",
                           "pre_idea_skips"}
    assert report["status"] == "ok"
    assert report["window"] == {"audit_rows_analyzed": 4, "audit_rows_total": 4,
                                "structured_rows": 3, "legacy_rows": 1,
                                "scanner_runs_analyzed": 1}

    funnel = {row["stage"]: row for row in report["stage_funnel"]}
    assert [row["stage"] for row in report["stage_funnel"]] == [
        "candidates_scanned", "ideas_created", "decision_attempts",
        "accepted_decisions", "alpha_gate_passed", "paper_orders_submitted",
        "paper_trades"]
    assert funnel["candidates_scanned"]["count"] == 10
    assert funnel["ideas_created"]["count"] == 4
    assert funnel["ideas_created"]["pct_of_previous"] == 0.4
    assert funnel["decision_attempts"]["count"] == 4
    assert funnel["accepted_decisions"]["count"] == 2
    assert funnel["accepted_decisions"]["pct_of_previous"] == 0.5
    assert funnel["alpha_gate_passed"]["count"] == 1
    assert funnel["alpha_gate_passed"]["pct_of_previous"] == 0.5
    assert funnel["paper_orders_submitted"]["count"] == 1
    assert funnel["paper_trades"]["count"] == 1

    confidence = _bucket(report, "confidence")
    assert confidence["evaluated"] == 3
    assert confidence["failures"] == 2            # structured + legacy
    assert confidence["enforced_failures"] == 2
    assert confidence["advisory_failures"] == 0
    assert confidence["legacy_failures"] == 1
    assert confidence["near_misses"] == 1         # 0.71 within 10% of 0.75
    assert confidence["share_of_attempts"] == 0.5
    assert confidence["observed_stats"]["count"] == 3
    assert confidence["observed_stats"]["min"] == 0.71
    assert confidence["observed_stats"]["max"] == 0.9

    alpha = _bucket(report, "alpha_composite_tier")
    assert alpha["evaluated"] == 2
    assert alpha["failures"] == 1
    assert alpha["enforced_failures"] == 0
    assert alpha["advisory_failures"] == 1        # enforced: false is advisory
    assert alpha["near_misses"] == 1              # 65 within 10% of 70
    assert alpha["observed_stats"]["count"] == 2

    watchlist = _bucket(report, "watchlist")
    assert watchlist["evaluated"] == 0            # legacy rows add no denominators
    assert watchlist["failures"] == 1
    assert watchlist["legacy_failures"] == 1
    assert watchlist["observed_stats"] is None

    market_open = _bucket(report, "market_open")
    assert market_open["failures"] == 0
    # Current behavior quirk, pinned deliberately: Python bools are ints, so a
    # boolean observation (True/True) is collected into observed_stats as 1.0.
    assert market_open["observed_stats"] == {"count": 1, "min": 1.0, "p25": 1.0,
                                             "p50": 1.0, "p75": 1.0, "max": 1.0}

    assert report["first_failed_gates"] == [{"gate": "confidence", "count": 2}]
    assert [t["gate"] for t in report["threshold_impact"]] == [
        "confidence", "watchlist", "alpha_composite_tier"]
    assert report["pre_idea_skips"] == [{"reason": "not trade candidate", "count": 7}]

    bucket_keys = {"gate", "evaluated", "failures", "enforced_failures",
                   "advisory_failures", "legacy_failures", "near_misses",
                   "example", "share_of_attempts", "observed_stats"}
    for bucket in report["gate_failures"]:
        assert set(bucket) == bucket_keys


# ── 3. serialize_decision() golden payload ──────────────────────────────────

class _StubBroker(BrokerState):
    def __init__(self, positions=None, is_open=True, price=50.0):
        self._positions = positions or []
        self._is_open = is_open
        self._price = price

    def get_account(self):
        return {"equity": "100000", "last_equity": "100000"}

    def get_positions(self):
        return self._positions

    def get_clock(self):
        return {"is_open": self._is_open}

    def get_latest_trade_price(self, symbol):
        return self._price


def _config(**overrides) -> RiskConfig:
    base = dict(min_confidence=0.75, max_position_size_usd=1900.0,
                max_equity_pct_per_trade=0.02, max_trades_per_day=10,
                max_open_positions=20, approved_tickers={"AAPL", "BTC/USD"},
                stop_loss_pct=0.03, take_profit_pct=0.06,
                max_daily_drawdown_pct=0.03, allow_short=False,
                use_bracket_orders=False)
    base.update(overrides)
    return RiskConfig(**base)


def _signal(**overrides) -> Signal:
    base = dict(ticker="AAPL", bias="bullish", confidence=0.9, timeframe="intraday",
                reason="characterization", source="test",
                timestamp=datetime(2026, 7, 1, 15, 0, tzinfo=timezone.utc),
                asset_type="equity")
    base.update(overrides)
    return Signal(**base)


DECISION_PAYLOAD_KEYS = {"accepted", "action", "reasons", "ticker", "bias",
                         "confidence", "timeframe", "asset_type", "notional", "qty",
                         "order_payload", "alpha", "gate_results", "gate_context",
                         "first_failed_gate", "evaluated_at"}
GATE_RECORD_KEYS = {"stage", "gate", "passed", "observed", "threshold",
                    "comparator", "detail"}
GATE_CONTEXT_KEYS = {"open_positions", "position_tickers", "has_position_in_ticker",
                     "orders_submitted_today", "market_open", "equity", "last_equity",
                     "drawdown_pct", "signal", "config"}


def _decide(signal: Signal, config: RiskConfig, tmp_path, broker=None, option=None):
    audit = AuditLog(tmp_path / "audit.jsonl")
    decision = evaluate_signal(signal, config, broker or _StubBroker(), audit,
                               dry_run=True, option=option)
    return serialize_decision(decision)


def test_accepted_equity_decision_payload(tmp_path):
    payload = _decide(_signal(), _config(), tmp_path)
    assert set(payload) == DECISION_PAYLOAD_KEYS
    assert payload["accepted"] is True
    assert payload["action"] == "dry_run"
    assert payload["reasons"] == ["dry-run accepted; no order placed"]
    assert payload["notional"] == 1900.0          # min($1900 cap, 2% of $100k)
    assert payload["qty"] is None
    assert payload["order_payload"] == {"symbol": "AAPL", "side": "buy",
                                        "type": "market", "time_in_force": "day",
                                        "notional": 1900.0}
    assert payload["first_failed_gate"] is None
    # Full gate sequence for a bullish equity: bearish-only guards not recorded.
    assert [g["gate"] for g in payload["gate_results"]] == [
        "confidence", "bias_actionable", "watchlist", "market_open",
        "max_open_positions", "duplicate_position", "max_trades_per_day",
        "daily_drawdown", "equity_available"]
    assert all(g["passed"] for g in payload["gate_results"])
    assert payload["gate_results"][-1]["stage"] == "sizing"
    for record in payload["gate_results"]:
        assert set(record) == GATE_RECORD_KEYS
    assert set(payload["gate_context"]) == GATE_CONTEXT_KEYS
    assert set(payload["gate_context"]["signal"]) == {"ticker", "bias", "confidence",
                                                      "timeframe", "asset_type", "source"}
    assert set(payload["gate_context"]["config"]) == {
        "min_confidence", "max_open_positions", "max_trades_per_day",
        "max_daily_drawdown_pct", "max_position_size_usd",
        "max_equity_pct_per_trade", "allow_short", "approved_tickers_count"}


def test_bearish_crypto_rejection_payload(tmp_path):
    payload = _decide(_signal(ticker="BTC/USD", bias="bearish", asset_type="crypto"),
                      _config(allow_short=True), tmp_path)
    assert payload["accepted"] is False
    assert payload["action"] == "reject"
    assert payload["reasons"] == ["Alpaca does not support shorting crypto (crypto is long-only)"]
    assert payload["first_failed_gate"] == "crypto_long_only"
    # Bearish records the short guards; crypto skips market_open; rejection
    # still evaluates the remaining risk gates (honest denominators).
    assert [g["gate"] for g in payload["gate_results"]] == [
        "confidence", "bias_actionable", "short_allowed", "crypto_long_only",
        "watchlist", "max_open_positions", "duplicate_position",
        "max_trades_per_day", "daily_drawdown"]


def test_option_decision_payload(tmp_path):
    option = {"contract_symbol": "AAPL260117C00200000", "estimated_cost_usd": 450.0}
    payload = _decide(_signal(asset_type="option"), _config(), tmp_path, option=option)
    assert payload["accepted"] is True
    assert payload["action"] == "dry_run"
    assert payload["reasons"] == ["dry-run accepted; no option order placed"]
    assert payload["notional"] == 450.0
    assert payload["qty"] == 1
    assert payload["order_payload"] == {"symbol": "AAPL260117C00200000", "side": "buy",
                                        "type": "market", "time_in_force": "day", "qty": 1}
    sizing = [g["gate"] for g in payload["gate_results"] if g["stage"] == "sizing"]
    assert sizing == ["equity_available", "option_contract_selected",
                      "option_cost_known", "option_cost_within_budget"]


def test_low_confidence_rejection_records_all_risk_gates(tmp_path):
    payload = _decide(_signal(confidence=0.71), _config(), tmp_path)
    assert payload["accepted"] is False
    assert payload["reasons"][0] == "confidence 0.71 below threshold 0.75"
    assert payload["first_failed_gate"] == "confidence"
    assert len(payload["gate_results"]) == 8      # every risk gate, no sizing
    assert sum(1 for g in payload["gate_results"] if not g["passed"]) == 1


# ── 4. Telemetry schema spine ───────────────────────────────────────────────
# Columns the waterfall, research frames, and dashboards join on. Additions
# are fine; renames/removals break every telemetry reader.

REQUIRED_TABLES = {
    "strategies", "alpha_ideas", "catalyst_events", "idea_strategies",
    "signal_evaluations", "trades", "execution_audit", "orders", "positions",
    "journal_entries", "scanner_runs", "decision_logs", "app_config",
    "analyst_theses", "trade_explanations", "approval_queue", "market_briefings",
    "futures_snapshots", "futures_moves", "catalyst_futures_reactions", "alerts",
    "notification_preferences", "push_subscriptions", "notification_audit",
    "approval_decisions",
}
SPINE_COLUMNS = {
    "execution_audit": {"id", "idea_id", "ticker", "status", "rejection_reason",
                        "payload_json", "dry_run", "created_at"},
    "decision_logs": {"id", "idea_id", "action", "reasons_json", "decision_json",
                      "created_at"},
    "signal_evaluations": {"id", "idea_id", "ticker", "source", "generated_at",
                           "evaluated_at", "direction", "confidence", "alert_price",
                           "price_after", "move_after_pct", "benchmark_move_pct",
                           "early_detection_score", "provisional_grade",
                           "final_grade", "status"},
    "alpha_ideas": {"id", "ticker", "asset_type", "bias", "confidence", "timeframe",
                    "thesis", "catalyst_type", "catalyst_score", "source", "status",
                    "rejection_reason", "timestamp", "source_tags", "market_regime"},
    "trades": {"id", "idea_id", "ticker", "side", "quantity", "notional",
               "entry_price", "exit_price", "realized_pl", "unrealized_pl",
               "status", "dry_run", "opened_at", "closed_at"},
}


def test_schema_spine_is_stable(tmp_path):
    service = AlphaLabService(db_path=str(tmp_path / "schema.sqlite3"),
                              audit_log_path=str(tmp_path / "audit.jsonl"))
    with connect(service.db_path) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        views = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'")}
        missing = REQUIRED_TABLES - tables
        assert not missing, f"telemetry tables removed: {sorted(missing)}"
        assert "training_rows" in views, "training_rows read-model view removed"
        for table, required in SPINE_COLUMNS.items():
            actual = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            lost = required - actual
            assert not lost, f"{table} lost spine columns: {sorted(lost)}"
