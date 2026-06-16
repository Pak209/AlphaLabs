from pathlib import Path

from paper_trader.runner import process_signal_payload


class FakeBroker:
    def __init__(self):
        self.orders = []

    def get_account(self):
        return {"equity": "100000", "cash": "100000", "last_equity": "100000"}

    def get_positions(self):
        return []

    def get_clock(self):
        return {"is_open": True}

    def get_latest_trade_price(self, symbol):
        return 100

    def place_order(self, payload):
        self.orders.append(payload)
        return {"id": "paper-order"}


def test_dry_run_does_not_place_order(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "min_confidence": 0.75,
          "max_position_size_usd": 500,
          "max_equity_pct_per_trade": 0.02,
          "max_trades_per_day": 5,
          "max_open_positions": 3,
          "approved_tickers": ["NVDA"],
          "stop_loss_pct": 0.04,
          "take_profit_pct": 0.08,
          "max_daily_drawdown_pct": 0.03
        }
        """,
        encoding="utf-8",
    )
    payload = {
        "ticker": "NVDA",
        "bias": "bullish",
        "confidence": 0.8,
        "timeframe": "intraday",
        "reason": "relative strength",
        "source": "market_scan_bot",
        "timestamp": "2026-06-04T13:00:00Z",
    }
    broker = FakeBroker()
    result = process_signal_payload(payload, config_path, tmp_path / "log.jsonl", broker, dry_run=True)
    assert result["action"] == "dry_run"
    assert broker.orders == []


def test_non_dry_run_places_mocked_order(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "min_confidence": 0.75,
          "max_position_size_usd": 500,
          "max_equity_pct_per_trade": 0.02,
          "max_trades_per_day": 5,
          "max_open_positions": 3,
          "approved_tickers": ["NVDA"],
          "stop_loss_pct": 0.04,
          "take_profit_pct": 0.08,
          "max_daily_drawdown_pct": 0.03
        }
        """,
        encoding="utf-8",
    )
    payload = {
        "ticker": "NVDA",
        "bias": "bullish",
        "confidence": 0.8,
        "timeframe": "intraday",
        "reason": "relative strength",
        "source": "market_scan_bot",
        "timestamp": "2026-06-04T13:00:00Z",
    }
    broker = FakeBroker()
    result = process_signal_payload(payload, config_path, tmp_path / "log.jsonl", broker, dry_run=False)
    assert result["action"] == "submit_order"
    assert len(broker.orders) == 1
