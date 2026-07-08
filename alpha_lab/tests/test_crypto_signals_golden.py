"""Value-pin characterization of BTC signal construction (Phase 2 PR5).

Pins the EXACT signal dicts — including the composed thesis, catalyst, and
invalidation strings and their price formatting — for three payload shapes:
bias derived from EMA (bullish), explicit bearish with missing support
(fallback levels), and neutral with no indicators (n/a formatting). Thesis
text feeds idea records and dedupe keys, so full-string equality is the
contract, not fragments.

Written BEFORE the extraction to crypto_signals.py so the move is
verbatim-or-fail; exercised through the service method, which stays as a
delegate (two scanner tests monkeypatch it on the instance).
"""
from __future__ import annotations

import json
from pathlib import Path

from alpha_lab.service import AlphaLabService

BULLISH_PAYLOAD = {
    "ticker": "BTC/USD", "symbol": "BTC", "name": "Bitcoin",
    "price": 118250.5,
    "summary": "BTC holding above the reclaim zone.",
    "indicators": {"ema20": 115000.0, "support_14d_close": 112000.0,
                   "resistance_14d_close": 121000.0, "ema_read": "Price above 20D EMA."},
    "volume_24h": 32000000000, "change_24h_pct": 2.4,
    "fetched_at": "2026-07-05T02:00:00Z", "last_updated": "2026-07-05T01:59:00Z",
    "source": "CoinGecko",
}

BEARISH_PAYLOAD = {
    "ticker": "ETH/USD", "symbol": "ETH",
    "price": 4100.0, "bias": "bearish",
    "indicators": {"ema20": 4300.0, "resistance_14d_close": 4450.0},
    "volume_24h": 9000000000, "change_24h_pct": -3.1,
    "fetched_at": "2026-07-05T02:00:00Z",
}

NEUTRAL_PAYLOAD = {
    "ticker": "SOL/USD", "symbol": "SOL",
    "price": 0,
    "fetched_at": "2026-07-05T02:00:00Z",
}


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "signals.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def test_bullish_bias_derived_from_ema(tmp_path: Path):
    assert service(tmp_path)._btc_signal_from_market(BULLISH_PAYLOAD) == GOLDEN["bullish"]


def test_bearish_explicit_with_missing_support_fallbacks(tmp_path: Path):
    assert service(tmp_path)._btc_signal_from_market(BEARISH_PAYLOAD) == GOLDEN["bearish"]


def test_neutral_without_indicators_formats_na(tmp_path: Path):
    assert service(tmp_path)._btc_signal_from_market(NEUTRAL_PAYLOAD) == GOLDEN["neutral"]


GOLDEN: dict = json.loads(r"""
{
  "bearish": {
    "asset_type": "crypto",
    "bias": "bearish",
    "catalyst": "24h volume 9000000000; 24h change -3.1%; support n/a, resistance $4,450.00.",
    "confidence": 0.78,
    "reason": "ETH after-hours bearish setup: ETH market context unavailable  Entry near n/a with confirmation; current $4,100.00; stop $4,450.00; target $3,854.00; Invalidate bearish thesis above $4,450.00.",
    "source": "after_hours_btc",
    "source_refs": [
      {
        "label": "CoinGecko",
        "timestamp": "",
        "url": ""
      }
    ],
    "strategy_tags": [
      "crypto momentum",
      "ETH breakout",
      "after-hours crypto"
    ],
    "theme": "After-Hours ETH",
    "thesis": "ETH after-hours bearish setup: ETH market context unavailable  Entry near n/a with confirmation; current $4,100.00; stop $4,450.00; target $3,854.00; Invalidate bearish thesis above $4,450.00.",
    "ticker": "ETH/USD",
    "timeframe": "intraday",
    "timestamp": "2026-07-05T02:00:00Z"
  },
  "bullish": {
    "asset_type": "crypto",
    "bias": "bullish",
    "catalyst": "24h volume 32000000000; 24h change 2.4%; support $112,000.00, resistance $121,000.00.",
    "confidence": 0.78,
    "reason": "BTC after-hours bullish setup: BTC holding above the reclaim zone. Price above 20D EMA. Entry near $121,000.00 with confirmation; current $118,250.50; stop $112,000.00; target $121,000.00; Invalidate bullish thesis below $112,000.00.",
    "source": "after_hours_btc",
    "source_refs": [
      {
        "label": "CoinGecko",
        "timestamp": "2026-07-05T01:59:00Z",
        "url": ""
      }
    ],
    "strategy_tags": [
      "crypto momentum",
      "BTC breakout",
      "after-hours crypto"
    ],
    "theme": "After-Hours BTC",
    "thesis": "BTC after-hours bullish setup: BTC holding above the reclaim zone. Price above 20D EMA. Entry near $121,000.00 with confirmation; current $118,250.50; stop $112,000.00; target $121,000.00; Invalidate bullish thesis below $112,000.00.",
    "ticker": "BTC/USD",
    "timeframe": "intraday",
    "timestamp": "2026-07-05T02:00:00Z"
  },
  "neutral": {
    "asset_type": "crypto",
    "bias": "neutral",
    "catalyst": "24h volume None; 24h change None%; support n/a, resistance n/a.",
    "confidence": 0.62,
    "reason": "SOL after-hours neutral setup: SOL market context unavailable  Entry near $0.00 with confirmation; current $0.00; stop $0.00; target $0.00; Invalidate if SOL fails to create a directional reclaim/rejection setup.",
    "source": "after_hours_btc",
    "source_refs": [
      {
        "label": "CoinGecko",
        "timestamp": "",
        "url": ""
      }
    ],
    "strategy_tags": [
      "crypto momentum",
      "SOL breakout",
      "after-hours crypto"
    ],
    "theme": "After-Hours SOL",
    "thesis": "SOL after-hours neutral setup: SOL market context unavailable  Entry near $0.00 with confirmation; current $0.00; stop $0.00; target $0.00; Invalidate if SOL fails to create a directional reclaim/rejection setup.",
    "ticker": "SOL/USD",
    "timeframe": "intraday",
    "timestamp": "2026-07-05T02:00:00Z"
  }
}
""")
