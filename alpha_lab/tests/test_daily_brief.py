"""Phase 1 test frontier: daily brief assembly (offline smoke).

The scheduler feeds import_daily_brief_and_test five times a day from this
builder; until now nothing verified its assembly offline. Section providers
are stubbed so the test never touches the network and pins: the strict
signals[] contract, the actionable-only filter, the max_signals cap, section
error containment, and the cache.
"""
from __future__ import annotations

import pytest

import alpha_lab.daily_brief as db


def stub_stock(ticker: str, bias: str, actionable: bool, confidence: float = 0.8):
    return {
        "ticker": ticker, "bias": bias, "confidence": confidence,
        "theme": "ai", "sector": "tech",
        "scenario": {"setup": f"{ticker} setup"},
        "strategy_candidate": {
            "name": f"{ticker} candidate", "actionable": actionable,
            "reason": "r", "trigger": "t", "confidence": confidence,
        },
    }


@pytest.fixture()
def offline_brief(monkeypatch):
    db._BRIEF_CACHE.clear()
    monkeypatch.setattr(db, "get_bitcoin_market", lambda: {"bias": "bullish"})
    monkeypatch.setattr(db, "get_liquidity_flows", lambda: {"groups": []})
    monkeypatch.setattr(db, "get_oil_market", lambda: (_ for _ in ()).throw(RuntimeError("feed down")))
    monkeypatch.setattr(db, "get_trending_stocks", lambda limit=10: {"stocks": [
        stub_stock("NVDA", "bullish", True),
        stub_stock("MSFT", "bullish", False),          # not actionable -> excluded
        stub_stock("SMCI", "bearish", True),
    ]})
    monkeypatch.setattr(db, "get_catalyst_radar", lambda live=True: {"signals": []})
    yield
    db._BRIEF_CACHE.clear()


def test_brief_signals_contract_and_filtering(offline_brief):
    brief = db.build_daily_market_brief(live_catalysts=False, max_signals=6)
    assert brief["status"] == "ok"
    tickers = [s["ticker"] for s in brief["signals"]]
    assert tickers == ["NVDA", "SMCI"]                 # actionable only
    for signal in brief["signals"]:
        # the strict block the dry-run importer requires
        for field in ("ticker", "bias", "confidence", "timeframe", "reason",
                      "source", "timestamp"):
            assert signal.get(field), field
        assert signal["source"] == "daily_market_brief"
        assert 0.75 <= signal["confidence"] <= 0.92
    bearish = next(s for s in brief["signals"] if s["ticker"] == "SMCI")
    assert bearish["timeframe"] == "intraday"          # bearish reads stay intraday
    assert brief["automation_contract"]["execution_default"] == "dry_run"


def test_section_errors_are_contained(offline_brief):
    brief = db.build_daily_market_brief(live_catalysts=False, max_signals=6)
    assert brief["sections"]["oil_energy"]["status"] == "unavailable"
    assert brief["signals"]                            # other sections still deliver


def test_max_signals_cap_and_cache(offline_brief, monkeypatch):
    brief = db.build_daily_market_brief(live_catalysts=False, max_signals=1)
    assert len(brief["signals"]) == 1
    # Second call inside the cache window returns the SAME payload without
    # rebuilding (stub a poisoned provider to prove no recompute happens).
    monkeypatch.setattr(db, "get_trending_stocks",
                        lambda limit=10: (_ for _ in ()).throw(AssertionError("rebuilt")))
    again = db.build_daily_market_brief(live_catalysts=False, max_signals=1)
    assert again["cached"] is True                     # served from cache, not rebuilt
    assert again["generated_at"] == brief["generated_at"]
    assert again["signals"] == brief["signals"]
