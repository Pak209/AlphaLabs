"""Exit management (portfolio audit B6): stop/target pass over paper positions.

Contract: off = no-op; shadow = decisions recorded via scanner_runs, zero
orders; on = closes ONLY when the paper switches are also armed, settling
matching trade rows and raising a WATCH alert. Thresholds are the existing
risk-config percentages (equity 4%/8%, crypto profile 3%/6%) — nothing new.
"""
from __future__ import annotations

from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "exits.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


class ExitBroker:
    """Position fixture + close capture."""

    def __init__(self, positions):
        self.positions = positions
        self.closed: list[str] = []

    def get_positions(self):
        return self.positions

    def close_position(self, symbol):
        self.closed.append(symbol)
        return {"id": f"order-{symbol}"}


def position(symbol, entry, current, qty=10.0):
    return {"symbol": symbol, "avg_entry_price": entry, "current_price": current,
            "qty": qty, "market_value": current * qty}


BOOK = [
    position("NVDA", 100.0, 95.5),      # -4.5% -> stop (equity 4%)
    position("META", 100.0, 109.0),     # +9%   -> target (equity 8%)
    position("MSFT", 100.0, 101.0),     # +1%   -> hold
    position("BTCUSD", 100.0, 97.5),    # -2.5% -> hold under crypto 3% stop
    position("ETHUSD", 100.0, 93.0),    # -7%   -> crypto stop
    {"symbol": "PLTR260918C00170000", "avg_entry_price": 4.5, "current_price": 9.0, "qty": 1},  # option: skipped
]


def exit_lab(tmp_path, monkeypatch, mode, armed=False, market_open=True):
    if mode is None:
        monkeypatch.delenv("ALPHALAB_EXIT_MANAGEMENT", raising=False)
    else:
        monkeypatch.setenv("ALPHALAB_EXIT_MANAGEMENT", mode)
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "paper" if armed else "dry_run")
    if armed:
        monkeypatch.setenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "true")
    else:
        monkeypatch.delenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", raising=False)
    lab = service(tmp_path)
    broker = ExitBroker([dict(p) for p in BOOK])
    monkeypatch.setattr(lab, "_broker", lambda dry_run=True: broker)
    monkeypatch.setattr(lab, "_equity_market_open", lambda: market_open)
    return lab, broker


def test_off_mode_is_a_noop(tmp_path, monkeypatch):
    lab, broker = exit_lab(tmp_path, monkeypatch, mode=None)
    assert lab.manage_exits()["status"] == "disabled"
    assert broker.closed == [] and lab.list_scanner_runs() == []


def test_shadow_records_decisions_but_never_orders(tmp_path, monkeypatch):
    lab, broker = exit_lab(tmp_path, monkeypatch, mode="shadow")
    result = lab.manage_exits()

    assert result["live"] is False and broker.closed == []
    verdicts = {(d["symbol"], d["verdict"]) for d in result["decisions"]}
    assert verdicts == {("NVDA", "stop_loss"), ("META", "take_profit"), ("ETHUSD", "stop_loss")}
    # crypto used the crypto profile: BTCUSD at -2.5% stayed under the 3% stop
    run = lab.list_scanner_runs()[0]
    assert run["source"] == "exit_manager"
    assert len(run["payload"]["exit_decisions"]) == 3
    assert run["payload"]["top_rejection_reasons"][0]["reason"] == "option position (own lifecycle)"


def test_on_mode_requires_armed_switches(tmp_path, monkeypatch):
    lab, broker = exit_lab(tmp_path, monkeypatch, mode="on", armed=False)
    result = lab.manage_exits()
    assert result["live"] is False and broker.closed == []   # on + disarmed = shadow


def test_on_and_armed_closes_settles_and_alerts(tmp_path, monkeypatch):
    lab, broker = exit_lab(tmp_path, monkeypatch, mode="on", armed=True)
    with connect(lab.db_path) as conn:
        repo = AlphaLabRepository(conn)
        idea = repo.create_idea({
            "ticker": "NVDA", "bias": "bullish", "confidence": 0.8, "timeframe": "intraday",
            "thesis": "t", "source": "test", "timestamp": "2026-07-09T14:00:00Z",
            "sector": "", "theme": "", "catalyst": "c", "strategies": ["manual"],
            "source_tags": ["manual"], "market_regime": "unknown",
        })
        repo.create_trade({"idea_id": idea["id"], "ticker": "NVDA", "side": "buy",
                           "quantity": 10.0, "notional": 1000.0, "entry_price": 100.0,
                           "status": "paper_open", "dry_run": False, "asset_type": "equity"})

    result = lab.manage_exits()

    assert result["live"] is True
    assert sorted(broker.closed) == ["ETHUSD", "META", "NVDA"]
    nvda = next(c for c in result["closed"] if c["symbol"] == "NVDA")
    assert nvda["trades_settled"] == 1 and "error" not in nvda
    with connect(lab.db_path) as conn:
        trade = conn.execute("SELECT status, exit_price, realized_pl FROM trades WHERE ticker='NVDA'").fetchone()
        assert trade["status"] == "closed"
        assert round(trade["realized_pl"], 2) == round((95.5 - 100.0) * 10, 2)
        alert = conn.execute("SELECT level, title FROM alerts ORDER BY id DESC LIMIT 3").fetchall()
        assert any("Exit executed" in a["title"] for a in alert)


def test_equity_exits_wait_for_market_open_but_crypto_proceeds(tmp_path, monkeypatch):
    lab, broker = exit_lab(tmp_path, monkeypatch, mode="shadow", market_open=False)
    result = lab.manage_exits()
    symbols = {d["symbol"] for d in result["decisions"]}
    assert symbols == {"ETHUSD"}                              # only the crypto stop fires
    run = lab.list_scanner_runs()[0]
    reasons = {r["reason"] for r in run["payload"]["top_rejection_reasons"]}
    assert "equity exits wait for market open" in reasons
