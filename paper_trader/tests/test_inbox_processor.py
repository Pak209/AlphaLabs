import json
from pathlib import Path

from paper_trader.inbox_processor import process_inbox


class FakeBroker:
    def get_account(self):
        return {"equity": "100000", "cash": "100000", "last_equity": "100000"}

    def get_positions(self):
        return []

    def get_clock(self):
        return {"is_open": True}

    def get_latest_trade_price(self, symbol):
        return 100


def write_config(path: Path):
    path.write_text(
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


def test_inbox_moves_accepted_file_to_processed(tmp_path: Path):
    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    rejected = tmp_path / "rejected"
    inbox.mkdir()
    write_config(tmp_path / "config.json")
    (inbox / "signal.json").write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "ticker": "NVDA",
                        "bias": "bullish",
                        "confidence": 0.8,
                        "timeframe": "intraday",
                        "reason": "relative strength",
                        "source": "market_scan_bot",
                        "timestamp": "2026-06-04T13:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    results = process_inbox(
        inbox, processed, rejected, tmp_path / "config.json", tmp_path / "log.jsonl", FakeBroker(), dry_run=True
    )

    assert results[0]["status"] == "processed"
    assert not (inbox / "signal.json").exists()
    assert (processed / "signal.json").exists()
    assert (processed / "signal.json.result.json").exists()


def test_inbox_moves_rejected_file_to_rejected(tmp_path: Path):
    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    rejected = tmp_path / "rejected"
    inbox.mkdir()
    write_config(tmp_path / "config.json")
    (inbox / "signal.json").write_text(
        json.dumps(
            {
                "ticker": "TSLA",
                "bias": "bullish",
                "confidence": 0.8,
                "timeframe": "intraday",
                "reason": "not approved",
                "source": "market_scan_bot",
                "timestamp": "2026-06-04T13:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    results = process_inbox(
        inbox, processed, rejected, tmp_path / "config.json", tmp_path / "log.jsonl", FakeBroker(), dry_run=True
    )

    assert results[0]["status"] == "rejected"
    assert not (inbox / "signal.json").exists()
    assert (rejected / "signal.json").exists()
    assert (rejected / "signal.json.result.json").exists()
