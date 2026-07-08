"""Phase 1 test frontier: the trending-stock setup classifier.

_classify_stock_setup drives trending-signal confidence (quality → confidence
in _stock_strategy_candidate), so each branch is pinned with synthetic inputs:
one canonical example per setup type, plus the don't-chase guard.
"""
from __future__ import annotations

from alpha_lab.market_data import _classify_stock_setup


def classify(price, closes, *, ema20=None, ema50=None, rsi=None,
             price_vs_ema20=None, price_vs_ema50=None,
             vol=0.0, d1=0.0, d5=0.0, d20=0.0):
    indicators = {
        "ema20": ema20, "ema50": ema50, "rsi14": rsi,
        "price_vs_ema20_pct": price_vs_ema20, "price_vs_ema50_pct": price_vs_ema50,
    }
    return _classify_stock_setup(price, closes, indicators, vol, d1, d5, d20)


FLAT_BASE = [100 + (i % 5) for i in range(20)]        # closes 100..104, range 4%


def test_extended_or_correcting_guards_against_chasing():
    # Overbought RSI alone triggers the don't-chase read.
    setup = classify(120.0, FLAT_BASE, ema20=110, ema50=100, rsi=74, price_vs_ema20=2.0)
    assert setup["type"] == "extended_or_correcting"
    assert setup["direction"] == "wait"
    # A -3% day on +35% volume does too, even with tame RSI.
    dumped = classify(97.0, FLAT_BASE, ema20=100, ema50=100, rsi=50,
                      price_vs_ema20=-3.0, vol=40, d1=-3.5)
    assert dumped["type"] == "extended_or_correcting"


def test_pre_breakout_base_below_resistance():
    # Resistance 104 (max of FLAT_BASE), price 103 → 0.96% below, range 4% wide.
    setup = classify(103.0, FLAT_BASE, ema20=101, ema50=99, rsi=55, price_vs_ema20=2.0)
    assert setup["type"] == "pre_breakout"
    assert setup["direction"] == "long"
    assert setup["quality"] == 88
    assert setup["levels"]["resistance"] == 104
    assert setup["levels"]["support"] == 100


def test_trend_pullback_long_near_ema20_above_ema50():
    # Price above resistance so pre_breakout can't claim it; hugging the 20D EMA
    # inside an intact 50D uptrend.
    setup = classify(106.0, FLAT_BASE, ema20=105, ema50=100, rsi=50,
                     price_vs_ema20=0.95, d5=0.0, d20=5.0)
    assert setup["type"] == "trend_pullback_long"
    assert setup["direction"] == "long"
    assert setup["quality"] == 82


def test_breakdown_short_below_both_emas_with_volume():
    setup = classify(90.0, FLAT_BASE, ema20=93, ema50=96, rsi=40,
                     price_vs_ema20=-3.2, vol=15, d1=-1.0, d5=-3.0, d20=-6.0)
    assert setup["type"] == "breakdown_short"
    assert setup["direction"] == "short"
    assert setup["quality"] == 80


def test_base_watch_compression_without_direction():
    # Tight range, mid RSI, but too far from resistance for pre_breakout.
    setup = classify(98.0, FLAT_BASE, ema20=101, ema50=101, rsi=48, price_vs_ema20=-3.0)
    assert setup["type"] == "base_watch"
    assert setup["direction"] == "wait"


def test_oversold_watch_needs_reclaim_evidence():
    falling = [140 - i for i in range(20)]            # wide range defeats base_watch
    setup = classify(115.0, falling, ema20=125, ema50=130, rsi=25, price_vs_ema20=-8.0)
    assert setup["type"] == "oversold_watch"
    assert setup["direction"] == "wait"


def test_unclear_when_nothing_fits():
    wide = [100, 130] * 10                            # 30% range: no compression
    setup = classify(115.0, wide, ema20=114, ema50=112, rsi=58, price_vs_ema20=0.9)
    assert setup["type"] == "unclear"
    assert setup["quality"] == 30
    assert setup["direction"] == "wait"
