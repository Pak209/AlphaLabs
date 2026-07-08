"""
alpha_lab/crypto_signals.py — pure BTC/after-hours signal construction.

Extracted verbatim from AlphaLabService (Phase 2 PR5, docs/PHASE2_PLAN.md):
the pure tier of the market-context cluster. These functions read no service
state — they turn a crypto market payload into the standard signal dict,
composing the entry/stop/target levels and the thesis/catalyst/invalidation
text. The exact output (full strings included — thesis feeds idea records and
dedupe keys) is pinned by tests/test_crypto_signals_golden.py.

The service keeps _btc_signal_from_market as a one-line delegate because two
scanner tests monkeypatch it on the instance; new code should call
btc_signal_from_market directly.
"""
from __future__ import annotations

from typing import Any


def btc_signal_from_market(btc: dict[str, Any]) -> dict[str, Any]:
    ticker = btc.get("ticker") or "BTC/USD"
    symbol = btc.get("symbol") or ticker.split("/")[0]
    name = btc.get("name") or symbol
    indicators = btc.get("indicators", {}) or {}
    price = float(btc.get("price") or 0)
    ema20 = indicators.get("ema20")
    support = indicators.get("support_14d_close")
    resistance = indicators.get("resistance_14d_close")
    bias = btc.get("bias") if btc.get("bias") in {"bullish", "bearish"} else "neutral"
    if bias == "neutral" and price and ema20:
        bias = "bullish" if price > float(ema20) else "bearish"
    confidence = 0.78 if bias in {"bullish", "bearish"} else 0.62
    entry = _entry_zone(price, bias, support, resistance, ema20)
    stop = _stop_level(price, bias, support, resistance, ema20)
    target = _target_level(price, bias, support, resistance, ema20)
    invalidation = (
        f"Invalidate bullish thesis below {_fmt_price(stop)}."
        if bias == "bullish"
        else f"Invalidate bearish thesis above {_fmt_price(stop)}."
        if bias == "bearish"
        else f"Invalidate if {symbol} fails to create a directional reclaim/rejection setup."
    )
    thesis = (
        f"{symbol} after-hours {bias} setup: {btc.get('summary', f'{symbol} market context unavailable')} "
        f"{indicators.get('ema_read', '')} Entry {entry}; stop {_fmt_price(stop)}; target {_fmt_price(target)}; {invalidation}"
    )
    catalyst = (
        f"24h volume {btc.get('volume_24h')}; 24h change {btc.get('change_24h_pct')}%; "
        f"support {_fmt_price(support)}, resistance {_fmt_price(resistance)}."
    )
    return {
        "ticker": ticker,
        "asset_type": "crypto",
        "bias": bias,
        "confidence": confidence,
        "timeframe": "intraday",
        "thesis": thesis,
        "reason": thesis,
        "catalyst": catalyst,
        "source": "after_hours_btc",
        "timestamp": btc.get("fetched_at") or btc.get("last_updated"),
        "strategy_tags": ["crypto momentum", f"{symbol} breakout", "after-hours crypto"],
        "theme": f"After-Hours {symbol}",
        "source_refs": [{"label": btc.get("source", "CoinGecko"), "url": "", "timestamp": btc.get("last_updated", "")}],
    }


def _entry_zone(price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> str:
    anchor = resistance if bias == "bullish" else support if bias == "bearish" else ema20 or price
    return f"near {_fmt_price(anchor)} with confirmation; current {_fmt_price(price)}"


def _stop_level(price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> float:
    if bias == "bullish":
        return float(support or ema20 or price * 0.97)
    if bias == "bearish":
        return float(resistance or ema20 or price * 1.03)
    return float(ema20 or price)


def _target_level(price: float, bias: str, support: Any, resistance: Any, ema20: Any) -> float:
    if bias == "bullish":
        return float(resistance or price * 1.06)
    if bias == "bearish":
        return float(support or price * 0.94)
    return float(resistance or support or ema20 or price)


def _fmt_price(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"
