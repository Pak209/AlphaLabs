"""Tests for the live Polygon intraday price/volume feed wired into the hard gate.

Two layers are covered:
  1. fetch_polygon_intraday — env gating + snapshot parsing (no real network).
  2. AlphaLabService._price_volume_inputs — how a snapshot becomes confirmation
     inputs, including the bias deadband, volume-only-helps rule, crypto skip,
     and safe neutral fallback.
"""
from __future__ import annotations

import pytest

from alpha_lab import service as service_mod
from alpha_lab import live_sources
from alpha_lab.service import AlphaLabService
from alpha_lab.scoring_engine import score_price_volume, PRICE_VOLUME_CONFIRM_MIN


@pytest.fixture
def svc(tmp_path):
    return AlphaLabService(db_path=str(tmp_path / "t.sqlite3"))


def _patch_snapshot(monkeypatch, payload):
    monkeypatch.setattr(service_mod, "fetch_polygon_intraday", lambda ticker: payload)


def test_fetch_disabled_without_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    out = live_sources.fetch_polygon_intraday("AAPL")
    assert out["status"] == "disabled"


def test_bullish_confirming_move_clears_gate(svc, monkeypatch):
    _patch_snapshot(monkeypatch, {"status": "ok", "gap_pct": 2.5, "relative_volume": 2.4})
    inp = svc._price_volume_inputs({"ticker": "NVDA", "asset_type": "equity", "bias": "bullish"})
    assert inp.trend_confirms is True
    assert inp.relative_volume == 2.4
    # Real confirming price + elevated volume must clear the 55 confirmation floor.
    assert score_price_volume(inp).score >= PRICE_VOLUME_CONFIRM_MIN


def test_price_against_thesis_is_gated(svc, monkeypatch):
    # Bullish idea but price is falling -> trend does not confirm -> below floor.
    _patch_snapshot(monkeypatch, {"status": "ok", "gap_pct": -3.0, "relative_volume": 5.0})
    inp = svc._price_volume_inputs({"ticker": "NVDA", "asset_type": "equity", "bias": "bullish"})
    assert inp.trend_confirms is False
    assert score_price_volume(inp).score < PRICE_VOLUME_CONFIRM_MIN


def test_tiny_move_within_deadband_is_neutral(svc, monkeypatch):
    _patch_snapshot(monkeypatch, {"status": "ok", "gap_pct": 0.10, "relative_volume": 3.0})
    inp = svc._price_volume_inputs({"ticker": "AAPL", "asset_type": "equity", "bias": "bullish"})
    assert inp.trend_confirms is None  # noise neither confirms nor penalizes


def test_low_volume_does_not_penalize(svc, monkeypatch):
    # Early-session cumulative volume < prior full day -> treated as neutral, not low.
    _patch_snapshot(monkeypatch, {"status": "ok", "gap_pct": 1.5, "relative_volume": 0.3})
    inp = svc._price_volume_inputs({"ticker": "AAPL", "asset_type": "equity", "bias": "bullish"})
    assert inp.relative_volume is None


def test_crypto_skips_equity_snapshot(svc, monkeypatch):
    # Should NOT call the equity feed for crypto; stays neutral.
    def _boom(ticker):
        raise AssertionError("equity snapshot must not be fetched for crypto")
    monkeypatch.setattr(service_mod, "fetch_polygon_intraday", _boom)
    inp = svc._price_volume_inputs({"ticker": "BTC/USD", "asset_type": "crypto", "bias": "bullish"})
    assert inp.relative_volume is None and inp.trend_confirms is None


def test_feed_miss_falls_back_to_neutral(svc, monkeypatch):
    _patch_snapshot(monkeypatch, {"status": "error", "reason": "boom"})
    inp = svc._price_volume_inputs({"ticker": "AAPL", "asset_type": "equity", "bias": "bullish"})
    assert inp.relative_volume is None and inp.trend_confirms is None
