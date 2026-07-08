from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.options_selector import OptionSelectionError
from alpha_lab.service import AlphaLabService
from paper_trader.simulated_broker import SimulatedPaperBroker


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "options.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def idea_payload(**overrides):
    payload = {
        "ticker": "AAPL",
        "bias": "bullish",
        "confidence": 0.86,
        "timeframe": "intraday",
        "thesis": "AAPL ATM call momentum with paper-testable liquidity.",
        "catalyst": "demo catalyst",
        "source": "unit_test",
        "timestamp": "2026-06-10T13:00:00Z",
        "strategy_tags": ["news catalyst"],
    }
    payload.update(overrides)
    return payload


CALL_SELECTION = {
    "contract_symbol": "AAPL260618C00292500",
    "underlying": "AAPL",
    "option_type": "call",
    "strike": 292.5,
    "expiry": "2026-06-18",
    "dte": 7,
    "underlying_price": 292.02,
    "bid": 4.42,
    "ask": 4.73,
    "mid": 4.575,
    "spread_pct": 6.78,
    "bid_size": 53,
    "ask_size": 71,
    "implied_volatility": 0.3259,
    "delta": 0.4663,
    "open_interest": 1048,
    "volume": 3832,
    "estimated_cost_usd": 473.0,
}

PUT_SELECTION = {
    **CALL_SELECTION,
    "contract_symbol": "SPY260618P00725000",
    "underlying": "SPY",
    "option_type": "put",
    "strike": 725.0,
    "delta": -0.4784,
    "estimated_cost_usd": 480.0,
}


class _Dump:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self) -> dict:
        return self.payload


def _force_tradeable_alpha(lab, monkeypatch):
    monkeypatch.setattr(
        lab,
        "_score_idea",
        lambda idea: (
            _Dump({
                "tier": "tradeable",
                "composite_score": 72.0,
                "confirmed": True,
                "gate_applied": False,
                "catalyst_score": 80.0,
                "price_volume_score": 72.0,
                "narrative_score": 75.0,
                "macro_score": 62.2,
            }),
            _Dump({"options_score": 0, "component_score": 50.0, "bias": "neutral"}),
            _Dump({"institutional_score": 0, "component_score": 50.0, "bias": "neutral"}),
        ),
    )


def _stub_lab(tmp_path, monkeypatch, selection, market_open=True):
    # These tests characterize the option mechanics DOWNSTREAM of the approval
    # gate (selection, budget, lifecycle). The option-order approval rule
    # (2026-07-08) has its own dedicated tests in test_options_automation.py,
    # so opt out here via the documented operator escape hatch.
    monkeypatch.setenv("ALPHALAB_REQUIRE_OPTION_APPROVAL", "false")
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    lab = service(tmp_path)
    monkeypatch.setattr(lab, "_select_option_contract", lambda idea: selection)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: SimulatedPaperBroker(market_open=market_open))
    _force_tradeable_alpha(lab, monkeypatch)
    return lab


def test_bullish_idea_buys_one_atm_call_contract(tmp_path, monkeypatch):
    lab = _stub_lab(tmp_path, monkeypatch, CALL_SELECTION)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False, as_option=True)
    assert result["accepted"] is True
    assert result["action"] == "submit_order"
    payload = result["order_payload"]
    assert payload["symbol"] == "AAPL260618C00292500"
    assert payload["side"] == "buy"
    assert payload["qty"] == 1
    assert payload["type"] == "market"
    assert payload["time_in_force"] == "day"
    assert "notional" not in payload


def test_bearish_idea_buys_a_put_even_when_shorting_disabled(tmp_path, monkeypatch):
    lab = _stub_lab(tmp_path, monkeypatch, PUT_SELECTION)
    idea = lab.create_idea(idea_payload(ticker="SPY", bias="bearish"))
    result = lab.place_trade(idea["id"], dry_run=False, as_option=True)
    assert result["accepted"] is True
    assert result["order_payload"]["symbol"] == "SPY260618P00725000"
    assert result["order_payload"]["side"] == "buy"


def test_option_entry_features_land_in_training_rows_view(tmp_path, monkeypatch):
    lab = _stub_lab(tmp_path, monkeypatch, CALL_SELECTION)
    idea = lab.create_idea(idea_payload())
    lab.place_trade(idea["id"], dry_run=False, as_option=True)
    with connect(lab.db_path) as conn:
        row = dict(conn.execute("SELECT * FROM training_rows").fetchone())
    assert row["asset_type"] == "option"
    assert row["contract_symbol"] == "AAPL260618C00292500"
    assert row["option_type"] == "call"
    assert row["strike"] == 292.5
    assert row["dte"] == 7
    assert row["contracts"] == 1
    assert row["entry_iv"] == 0.3259
    assert row["entry_delta"] == 0.4663
    assert row["entry_open_interest"] == 1048
    # The decision/alpha snapshot must be joinable to the trade for later learning.
    assert row["decision_action"] == "submit_order"
    assert row["decision_json"] and "alpha" in row["decision_json"]
    assert row["dry_run"] == 0


def test_no_qualifying_contract_is_a_clean_rejection(tmp_path, monkeypatch):
    lab = _stub_lab(tmp_path, monkeypatch, CALL_SELECTION)

    def boom(idea):
        raise OptionSelectionError("spread too wide on AAPL260618C00292500: 30% > 15% max")

    monkeypatch.setattr(lab, "_select_option_contract", boom)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False, as_option=True)
    assert result["accepted"] is False
    assert result["action"] == "no_option_contract"
    assert "spread too wide" in result["reasons"][0]
    assert lab.list_trades() == []


def test_full_lifecycle_fill_position_close_and_outcome_linkage(tmp_path, monkeypatch):
    # Entry fills at 4.50, exit at 5.50 -> realized = (5.50-4.50) * 1 contract * 100 = $100.
    broker = SimulatedPaperBroker(price=4.50, close_price=5.50)
    monkeypatch.setenv("ALPHALAB_REQUIRE_PAPER_APPROVAL", "false")
    monkeypatch.setenv("ALPHALAB_REQUIRE_OPTION_APPROVAL", "false")   # mechanics test; approval gate covered in test_options_automation
    lab = service(tmp_path)
    monkeypatch.setattr(lab, "_select_option_contract", lambda idea: CALL_SELECTION)
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    _force_tradeable_alpha(lab, monkeypatch)

    idea = lab.create_idea(idea_payload())

    # Order construction + broker acceptance + fill.
    result = lab.place_trade(idea["id"], dry_run=False, as_option=True)
    assert result["accepted"] is True
    trade_id = result["trade_id"]
    assert result["order_response"]["id"].startswith("sim-order-")

    fill = lab.refresh_option_entry_fill(trade_id)
    assert fill["filled_avg_price"] == 4.50
    assert fill["order"]["status"] == "filled"

    # Position tracking.
    positions = broker.get_positions()
    assert any(p["symbol"] == "AAPL260618C00292500" for p in positions)

    # Close -> realized P/L + outcome linkage in training_rows.
    close = lab.close_option_trade(trade_id)
    assert close["exit_price"] == 5.50
    assert close["realized_pl"] == 100.0

    with connect(lab.db_path) as conn:
        row = dict(conn.execute("SELECT * FROM training_rows WHERE trade_id = ?", (trade_id,)).fetchone())
    assert row["entry_price"] == 4.50
    assert row["exit_price"] == 5.50
    assert row["realized_pl"] == 100.0
    assert row["closed_at"]
    assert row["trade_status"] == "closed"
    assert row["decision_json"] and "alpha" in row["decision_json"]
    # Position should be flat again after the close.
    assert broker.get_positions() == []


def test_contract_cost_above_budget_is_rejected(tmp_path, monkeypatch):
    pricey = {**CALL_SELECTION, "estimated_cost_usd": 999999.0}
    lab = _stub_lab(tmp_path, monkeypatch, pricey)
    idea = lab.create_idea(idea_payload())
    result = lab.place_trade(idea["id"], dry_run=False, as_option=True)
    assert result["accepted"] is False
    assert "exceeds per-trade budget" in result["reasons"][0]
    assert lab.list_trades() == []
