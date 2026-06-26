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
    assert "alpha_tier must be high_conviction or tradeable" in result["reasons"][0]
    assert broker.orders == []
    assert lab.list_trades() == []
    stored = lab.list_ideas()[0]
    assert stored["status"] == "rejected"
    assert "alpha_tier" in stored["rejection_reason"]


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
    assert any("alpha_composite must be >= 70" in reason for reason in result["reasons"])
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
    assert "got missing" in result["reasons"][0]
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
    assert result["reasons"] == ["alpha_composite must be >= 70 before Alpaca paper execution (got 69.0)"]
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
    assert "alpha_tier must be high_conviction or tradeable" in result["paper_eligibility_reason"]
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
