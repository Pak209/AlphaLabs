from __future__ import annotations

from pathlib import Path

from alpha_lab.database import connect, init_db
from alpha_lab.options_flow import OptionsFlowInputs
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService
from paper_trader.simulated_broker import SimulatedPaperBroker


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "alpha.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def idea_payload():
    return {
        "ticker": "NVDA",
        "bias": "bullish",
        "confidence": 0.82,
        "timeframe": "intraday",
        "thesis": "AI infrastructure momentum with relative strength.",
        "source": "test",
        "timestamp": "2026-06-04T13:00:00Z",
        "strategy_tags": ["AI bottleneck", "breakout"],
    }


class _Dump:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self) -> dict:
        return self.payload


def force_alpha(lab: AlphaLabService, monkeypatch, *, tier: str | None, composite: float | None):
    alpha = {
        "tier": tier,
        "composite_score": composite,
        "confirmed": tier in {"tradeable", "high_conviction"},
        "gate_applied": False,
        "catalyst_score": 80.0,
        "price_volume_score": 72.0,
        "narrative_score": 75.0,
        "macro_score": 62.2,
    }
    monkeypatch.setattr(
        lab,
        "_score_idea",
        lambda idea: (
            _Dump(alpha),
            _Dump({"options_score": 0, "component_score": 50.0, "bias": "neutral"}),
            _Dump({"institutional_score": 0, "component_score": 50.0, "bias": "neutral"}),
        ),
    )


def test_create_idea_with_strategy_tags(tmp_path: Path):
    lab = service(tmp_path)
    idea = lab.create_idea(idea_payload())
    assert idea["ticker"] == "NVDA"
    assert "AI bottleneck" in idea["strategies"]
    evaluations = lab.list_signal_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0]["idea_id"] == idea["id"]
    assert evaluations[0]["status"] == "provisional"
    assert "test" in evaluations[0]["source_tags"]


def test_repository_create_idea_creates_default_signal_evaluation(tmp_path: Path):
    db_path = str(tmp_path / "repo.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        repo = AlphaLabRepository(conn)
        idea = repo.create_idea(
            {
                **idea_payload(),
                "sector": "",
                "theme": "",
                "catalyst": "unit catalyst",
                "strategies": ["manual"],
                "source_tags": ["manual"],
                "market_regime": "unknown",
            }
        )
        evaluation = repo.get_signal_evaluation(idea["id"])
    assert evaluation["status"] == "provisional"
    assert evaluation["source_tags"] == ["manual"]


def test_seed_defaults_backfills_existing_idea_evaluation_and_source_tags(tmp_path: Path):
    db_path = str(tmp_path / "backfill.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, source, timestamp, source_tags)
            VALUES ('MSFT', 'bullish', 0.8, 'intraday', 'manual idea', 'manual',
                    '2026-06-04T13:00:00Z', '[]')
            """
        )
        conn.commit()
        repo = AlphaLabRepository(conn)
        repo.seed_defaults()
        idea = repo.list_ideas(1)[0]
        evaluation = repo.get_signal_evaluation(idea["id"])
    assert "manual" in idea["source_tags"]
    assert evaluation["status"] == "provisional"
    assert evaluation["source_tags"] == ["manual"]


def test_source_tags_persist_for_core_sources(tmp_path: Path):
    lab = service(tmp_path)
    sources = ["manual", "catalyst_radar", "daily_market_brief"]
    for source in sources:
        payload = idea_payload()
        payload["ticker"] = {"manual": "AAPL", "catalyst_radar": "NVDA", "daily_market_brief": "TSLA"}[source]
        payload["source"] = source
        payload.pop("strategy_tags", None)
        idea = lab.create_idea(payload)
        assert source in idea["source_tags"]


def test_options_flow_preview_is_read_only_and_accounted(tmp_path: Path):
    class FakeOptionsProvider:
        def fetch(self, ticker: str):
            if ticker == "SPY":
                return OptionsFlowInputs(ticker="SPY", call_volume=1200, put_volume=300, avg_call_volume=100)
            return None

    lab = service(tmp_path)
    result = lab.run_options_flow_preview(watchlist=["SPY", "QQQ"], provider=FakeOptionsProvider())
    assert result["read_only"] is True
    assert result["summary"]["candidates_found"] == 1
    assert result["summary"]["ideas_persisted"] == 0
    assert len(lab.list_scanner_runs()) == 1
    assert lab.list_ideas() == []
    assert lab.list_trades() == []
    assert lab.list_execution_audit() == []
    with connect(lab.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"] == 0


def test_dry_run_trade_creates_trade_without_alpaca_keys(tmp_path: Path):
    lab = service(tmp_path)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=True)
    assert result["accepted"] is True
    assert result["order_response"]["dry_run"] is True
    trades = lab.list_trades()
    assert len(trades) == 1
    assert trades[0]["dry_run"] == 1
    assert lab.list_ideas()[0]["status"] == "tested"


def test_ignore_tier_blocks_paper_order(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="ignore", composite=45.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is False
    assert result["action"] == "paper_execution_blocked"
    assert "alpha gate: composite must be >= 70 with tier tradeable/high_conviction" in result["reasons"][0]
    assert "tier ignore" in result["reasons"][0]
    assert broker.orders == []
    assert lab.list_trades() == []
    stored = lab.list_ideas()[0]
    assert stored["status"] == "rejected"
    assert "alpha gate" in stored["rejection_reason"]


def test_watchlist_tier_blocks_paper_order(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="watchlist", composite=69.9)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is False
    assert result["action"] == "paper_execution_blocked"
    assert any("composite must be >= 70" in reason for reason in result["reasons"])
    assert broker.orders == []
    assert lab.list_trades() == []


def test_missing_alpha_tier_blocks_paper_order(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier=None, composite=75.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is False
    assert result["action"] == "paper_execution_blocked"
    assert "tier missing" in result["reasons"][0]
    assert broker.orders == []
    assert lab.list_trades() == []


def test_tradeable_tier_with_low_composite_blocks_paper_order(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="tradeable", composite=69.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is False
    assert result["action"] == "paper_execution_blocked"
    assert result["reasons"] == [
        "alpha gate: composite must be >= 70 with tier tradeable/high_conviction "
        "before Alpaca paper execution (got composite 69.0, tier tradeable)"
    ]
    assert broker.orders == []
    assert lab.list_trades() == []


def test_tradeable_tier_can_submit_paper_order_when_other_gates_pass(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="tradeable", composite=70.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is True
    assert result["paper_eligible"] is True
    assert result["order_response"]["paper_simulated"] is True
    assert len(broker.orders) == 1
    assert lab.list_trades()[0]["dry_run"] == 0


def test_high_conviction_tier_can_submit_paper_order_when_other_gates_pass(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="high_conviction", composite=82.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is True
    assert result["paper_eligible"] is True
    assert result["order_response"]["paper_simulated"] is True
    assert len(broker.orders) == 1
    assert lab.list_trades()[0]["dry_run"] == 0


def test_dry_run_low_tier_still_simulates_without_broker_order(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="ignore", composite=45.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=True)

    assert result["accepted"] is True
    assert result["action"] == "dry_run"
    assert result["paper_eligible"] is False
    assert "alpha gate: composite must be >= 70 with tier tradeable/high_conviction" in result["paper_eligibility_reason"]
    assert broker.orders == []
    trades = lab.list_trades()
    assert len(trades) == 1
    assert trades[0]["dry_run"] == 1


def test_neutral_idea_is_rejected_with_reason(tmp_path: Path):
    lab = service(tmp_path)
    payload = idea_payload()
    payload["bias"] = "neutral"
    idea = lab.create_idea(payload)
    decision = lab.run_decision(idea["id"], dry_run=True)
    assert decision["accepted"] is False
    stored = lab.list_ideas()[0]
    assert stored["status"] == "rejected"
    assert "bias is not actionable" in stored["rejection_reason"]



def test_import_and_test_defaults_to_dry_run(tmp_path: Path):
    lab = service(tmp_path)
    result = lab.import_and_test({"signals": [idea_payload()]})
    assert result["dry_run"] is True
    assert result["results"][0]["test_result"]["accepted"] is True
    assert lab.list_trades()[0]["dry_run"] == 1
    assert lab.list_ideas()[0]["status"] == "tested"


def test_test_new_ideas_runs_dry_run_once_for_new_status(tmp_path: Path):
    lab = service(tmp_path)
    lab.create_idea(idea_payload())
    result = lab.test_new_ideas(dry_run=True)
    assert len(result["results"]) == 1
    assert result["results"][0]["test_result"]["action"] == "dry_run"
    assert lab.list_ideas()[0]["status"] == "tested"


def test_dry_run_decision_writes_strategy_metrics_and_execution_context(tmp_path: Path):
    lab = service(tmp_path)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=True)
    assert result["decision_log_id"]

    stats = lab.strategy_stats()
    breakout = next(row for row in stats if row["strategy"] == "breakout")
    assert breakout["trades"] == 1
    assert breakout["dry_run_trades"] == 1
    assert breakout["paper_trades"] == 0
    assert breakout["recent_trades"][0]["ticker"] == "NVDA"

    audit = lab.list_execution_audit()
    assert audit[0]["payload"]["_execution"]["dry_run"] is True
    assert audit[0]["response"]["_execution"]["paper_endpoint"] is False


def test_trades_without_strategy_are_backfilled_to_untagged(tmp_path: Path):
    lab = service(tmp_path)
    payload = idea_payload()
    payload.pop("strategy_tags")
    idea = lab.create_idea(payload)
    lab.place_trade(idea["id"], dry_run=True)

    diagnostics = lab.strategy_diagnostics()

    assert diagnostics["trades_missing_strategy_labels"] == 0
    assert any(row["strategy"] == "test" and row["trades"] == 1 for row in lab.strategy_stats())


def _fake_crypto_signal(ticker: str, bias: str) -> dict:
    return {
        "ticker": ticker,
        "asset_type": "crypto",
        "bias": bias,
        "confidence": 0.78,
        "timeframe": "intraday",
        "thesis": f"{ticker} {bias} after-hours setup at a live price snapshot.",
        "reason": f"{ticker} {bias} after-hours setup at a live price snapshot.",
        "source": "after_hours_btc",
        "timestamp": "2026-06-04T13:00:00Z",
        "catalyst": "after-hours crypto read",
        "strategy_tags": ["crypto momentum"],
    }


def test_poll_weekend_crypto_skips_bearish_long_only_entries(tmp_path: Path, monkeypatch):
    import alpha_lab.service as service_module

    lab = service(tmp_path)
    monkeypatch.setattr(service_module, "get_crypto_market", lambda t: {"status": "ok", "ticker": t})
    monkeypatch.setattr(
        lab, "_btc_signal_from_market",
        lambda market: _fake_crypto_signal(market["ticker"], "bearish"),
    )

    result = lab.poll_weekend_crypto(dry_run=True)

    assert result["signals"] == []
    assert lab.list_ideas() == []
    run = lab.list_scanner_runs()[0]
    reasons = {item["reason"]: item["count"] for item in run["payload"]["top_rejection_reasons"]}
    assert reasons["bearish crypto skipped (broker is long-only)"] == 3


def test_poll_weekend_crypto_dedupes_same_ticker_bias_within_window(tmp_path: Path, monkeypatch):
    import alpha_lab.service as service_module

    lab = service(tmp_path)
    monkeypatch.setattr(service_module, "get_crypto_market", lambda t: {"status": "ok", "ticker": t})
    calls = {"n": 0}

    def fake_signal(market):
        calls["n"] += 1
        # Thesis embeds a changing "price" so thesis-equality dedupe never fires.
        signal = _fake_crypto_signal(market["ticker"], "bullish")
        signal["thesis"] = f"{market['ticker']} bullish setup at price {calls['n']}"
        signal["reason"] = signal["thesis"]
        return signal

    monkeypatch.setattr(lab, "_btc_signal_from_market", fake_signal)

    first = lab.poll_weekend_crypto(dry_run=True)
    assert len(first["signals"]) == 3
    ideas_after_first = len(lab.list_ideas())
    assert ideas_after_first == 3

    second = lab.poll_weekend_crypto(dry_run=True)
    assert second["signals"] == []
    assert len(lab.list_ideas()) == ideas_after_first


def test_poll_live_catalysts_defers_equity_signals_while_market_closed(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    equity_signal = {
        "ticker": "NVDA",
        "asset_type": "equity",
        "bias": "bullish",
        "confidence": 0.82,
        "timeframe": "intraday",
        "reason": "Catalyst Radar: NVDA wins major AI contract.",
        "source": "catalyst_radar",
        "timestamp": "2026-06-04T13:00:00Z",
        "catalyst": "major AI contract",
        "strategy_tags": ["Government Contract"],
    }
    monkeypatch.setattr(
        lab, "catalyst_intelligence",
        lambda **kwargs: {"signals": [equity_signal], "catalysts": [], "live_status": None, "mode": "test"},
    )
    monkeypatch.setattr(lab, "_equity_market_open", lambda: False)

    closed = lab.poll_live_catalysts(dry_run=True)
    assert closed["signals"] == []
    assert lab.list_ideas() == []

    monkeypatch.setattr(lab, "_equity_market_open", lambda: True)
    open_result = lab.poll_live_catalysts(dry_run=True)
    assert len(open_result["signals"]) == 1
    assert len(lab.list_ideas()) == 1


def test_execution_audit_persists_gate_trace(tmp_path: Path):
    lab = service(tmp_path)
    payload = idea_payload()
    payload["confidence"] = 0.72   # near-miss vs the 0.75 threshold
    idea = lab.create_idea(payload)
    result = lab.place_trade(idea["id"], dry_run=True)
    assert result["accepted"] is False

    audit = lab.list_execution_audit()[0]
    gates = audit["payload"]["_gates"]
    confidence = next(r for r in gates if r["gate"] == "confidence")
    assert confidence["passed"] is False
    assert confidence["observed"] == 0.72
    assert confidence["threshold"] == 0.75
    assert audit["payload"]["_first_failed_gate"] == "confidence"
    assert audit["payload"]["_gate_context"]["config"]["min_confidence"] == 0.75


def test_dry_run_records_advisory_alpha_gate(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="ignore", composite=45.0)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=True)

    assert result["accepted"] is True   # dry-run still simulates
    alpha_gate = next(r for r in result["gate_results"] if r["gate"] == "alpha_composite_tier")
    assert alpha_gate["passed"] is False
    assert alpha_gate["enforced"] is False   # advisory in dry-run
    assert alpha_gate["observed"] == 45.0
    assert alpha_gate["threshold"] == 70


def test_paper_block_records_enforced_alpha_gate(tmp_path: Path, monkeypatch):
    lab = service(tmp_path)
    broker = SimulatedPaperBroker()
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    force_alpha(lab, monkeypatch, tier="watchlist", composite=69.9)

    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False)

    assert result["accepted"] is False
    assert result["first_failed_gate"] == "alpha_composite_tier"
    alpha_gate = next(r for r in result["gate_results"] if r["gate"] == "alpha_composite_tier")
    assert alpha_gate["enforced"] is True
    audit = lab.list_execution_audit()[0]
    assert audit["payload"]["_first_failed_gate"] == "alpha_composite_tier"


def test_rejection_waterfall_aggregates_gates_and_stages(tmp_path: Path):
    lab = service(tmp_path)
    near_miss_payload = idea_payload()
    near_miss_payload["confidence"] = 0.72
    rejected = lab.create_idea(near_miss_payload)
    lab.place_trade(rejected["id"], dry_run=True)
    accepted = lab.create_idea(idea_payload())
    lab.place_trade(accepted["id"], dry_run=True)

    report = lab.rejection_waterfall()

    assert report["status"] == "ok"
    stages = {row["stage"]: row for row in report["stage_funnel"]}
    assert stages["ideas_created"]["count"] == 2
    assert stages["decision_attempts"]["count"] == 2
    assert stages["accepted_decisions"]["count"] == 1
    assert stages["paper_orders_submitted"]["count"] == 0

    confidence = next(b for b in report["gate_failures"] if b["gate"] == "confidence")
    assert confidence["failures"] == 1
    assert confidence["near_misses"] == 1   # 0.72 is within 10% of 0.75
    # Distribution over ALL structured evaluations (passed 0.82 + failed 0.72),
    # so threshold placement can be judged against the candidate population.
    stats = confidence["observed_stats"]
    assert stats["count"] == 2
    assert stats["min"] == 0.72
    assert stats["max"] == 0.82
    assert report["first_failed_gates"][0]["gate"] == "confidence"
    assert report["window"]["structured_rows"] == 2


def test_rejection_waterfall_maps_legacy_reason_rows(tmp_path: Path):
    lab = service(tmp_path)
    with connect(lab.db_path) as conn:
        AlphaLabRepository(conn).log_execution_attempt({
            "idea_id": None,
            "ticker": "BTC/USD",
            "status": "reject",
            "rejection_reason": "Alpaca does not support shorting crypto (crypto is long-only); market is closed",
            "payload": {},
            "response": {},
            "dry_run": True,
        })

    report = lab.rejection_waterfall()
    by_gate = {b["gate"]: b for b in report["gate_failures"]}
    assert by_gate["crypto_long_only"]["legacy_failures"] == 1
    assert by_gate["market_open"]["legacy_failures"] == 1
    # First clause counts as the first-failed gate for legacy rows.
    assert {"gate": "crypto_long_only", "count": 1} in report["first_failed_gates"]


def test_waterfall_snapshot_writes_file_and_diffs(tmp_path: Path, capsys):
    from scripts.waterfall_snapshot import take_snapshot, previous_snapshot, print_delta

    lab = service(tmp_path)
    rejected = lab.create_idea({**idea_payload(), "confidence": 0.72})
    lab.place_trade(rejected["id"], dry_run=True)

    out_dir = tmp_path / "snapshots"
    first = take_snapshot(lab, out_dir)
    assert first.exists()
    assert previous_snapshot(out_dir, first) is None

    accepted = lab.create_idea(idea_payload())
    lab.place_trade(accepted["id"], dry_run=True)
    second = take_snapshot(lab, out_dir)
    assert previous_snapshot(out_dir, second) == first

    print_delta(second, first)
    output = capsys.readouterr().out
    assert "compared to" in output
    assert "decision_attempts" in output
