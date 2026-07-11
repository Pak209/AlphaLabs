"""Portfolio report: live holdings + exit plans + honest account grade.

The account grade is deliberately separate from the signal-quality report
card — these tests pin the exit-plan math (side-aware, crypto profile,
options excluded), the grade bands, and the broker-unreachable degradation.
"""
from __future__ import annotations

from pathlib import Path

from alpha_lab.database import connect, init_db
from alpha_lab.service import AlphaLabService


class FakeBroker:
    def __init__(self, positions, equity="100500", cash="80000"):
        self._positions = positions
        self._equity = equity
        self._cash = cash

    def get_account(self):
        return {"equity": self._equity, "cash": self._cash}

    def get_positions(self):
        return self._positions


POSITIONS = [
    {"symbol": "META", "qty": "3.5", "side": "long", "avg_entry_price": "500",
     "current_price": "550", "market_value": "1925", "unrealized_pl": "175",
     "unrealized_plpc": "0.10", "asset_class": "us_equity"},
    {"symbol": "TSLA", "qty": "2", "side": "short", "avg_entry_price": "400",
     "current_price": "380", "market_value": "-760", "unrealized_pl": "40",
     "unrealized_plpc": "0.05", "asset_class": "us_equity"},
    {"symbol": "BTC/USD", "qty": "0.01", "side": "long", "avg_entry_price": "100000",
     "current_price": "99000", "market_value": "990", "unrealized_pl": "-10",
     "unrealized_plpc": "-0.01", "asset_class": "crypto"},
    {"symbol": "NVDA260116C00180000", "qty": "1", "side": "long", "avg_entry_price": "12.5",
     "current_price": "14", "market_value": "1400", "unrealized_pl": "150",
     "unrealized_plpc": "0.12", "asset_class": "us_option"},
]


def service_with_broker(tmp_path: Path, broker) -> AlphaLabService:
    db = str(tmp_path / "portfolio.sqlite3")
    init_db(db)
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO trades (ticker, side, quantity, entry_price, status, realized_pl,"
            " dry_run) VALUES ('OLD1', 'buy', 1, 10, 'closed', 25.0, 0)")
        conn.execute(
            "INSERT INTO trades (ticker, side, quantity, entry_price, status, realized_pl,"
            " dry_run) VALUES ('OLD2', 'buy', 1, 10, 'closed', -5.0, 0)")
        conn.commit()
    service = AlphaLabService(db_path=db)
    service._broker = lambda dry_run=True: broker
    return service


def test_portfolio_report_exit_plans_and_grade(tmp_path: Path):
    service = service_with_broker(tmp_path, FakeBroker(POSITIONS))
    report = service.portfolio_report()
    assert report["status"] == "ok"
    assert report["account"]["equity"] == 100500.0
    assert report["account"]["positions_count"] == 4
    by_symbol = {p["symbol"]: p for p in report["positions"]}

    meta = by_symbol["META"]["exit_plan"]          # long: stop below, target above
    assert meta["type"] == "stop_target"
    assert meta["stop_price"] < 500 < meta["target_price"]

    tsla = by_symbol["TSLA"]["exit_plan"]          # short: mirrored
    assert tsla["stop_price"] > 400 > tsla["target_price"]

    assert by_symbol["BTC/USD"]["exit_plan"]["type"] == "stop_target"
    assert by_symbol["NVDA260116C00180000"]["exit_plan"]["type"] == "options_lifecycle"

    # grade: realized (+20) + unrealized (+355) on ~100k baseline => C band (>=0, <2%)
    assert report["realized"] == {"closed_trades": 2, "realized_pl": 20.0, "win_rate": 50.0}
    assert report["unrealized_pl"] == 355.0
    assert report["grade"]["letter"] == "C"
    assert 0 <= report["grade"]["pl_pct"] < 2

    # sorted by |market value| so the biggest exposure leads the table
    assert report["positions"][0]["symbol"] == "META"


def test_portfolio_report_degrades_when_broker_unreachable(tmp_path: Path):
    class DownBroker:
        def get_account(self):
            raise RuntimeError("connection refused")

        def get_positions(self):  # pragma: no cover
            raise RuntimeError("connection refused")

    service = service_with_broker(tmp_path, DownBroker())
    report = service.portfolio_report()
    assert report["status"] == "unavailable"
    assert report["positions"] == []
    assert "connection refused" in report["detail"]
