"""Polygon-vs-Alpaca PV comparison: the daily renewal-evidence job.

Pins the agreement math (direction deadband, both-ok counting) and the
write toggle, with both intraday feeds mocked — no network.
"""
from __future__ import annotations

import scripts.pv_source_compare as pv


def _feeds(monkeypatch, poly_map, alp_map):
    monkeypatch.setattr(pv, "fetch_polygon_intraday", lambda t: poly_map.get(t, {"status": "error"}))
    monkeypatch.setattr(pv, "fetch_alpaca_intraday", lambda t: alp_map.get(t, {"status": "error"}))
    # pin the ticker universe so the test doesn't depend on config.example.json
    monkeypatch.setattr(pv, "load_config", lambda _p: type("C", (), {"approved_tickers": ["AAA", "BBB", "CCC"]})())


def test_direction_deadband():
    assert pv.direction(0.1) == "neutral"      # within DEADBAND
    assert pv.direction(0.9) == "up"
    assert pv.direction(-0.9) == "down"
    assert pv.direction(None) == "neutral"


def test_compare_counts_agreement_and_usability(monkeypatch, tmp_path):
    monkeypatch.setattr(pv, "REPORT_DIR", tmp_path)
    _feeds(monkeypatch,
           poly_map={
               "AAA": {"status": "ok", "gap_pct": 1.5, "relative_volume": 1.2},
               "BBB": {"status": "ok", "gap_pct": -0.8, "relative_volume": 0.9},
               "CCC": {"status": "ok", "gap_pct": 2.0, "relative_volume": 1.1}},
           alp_map={
               "AAA": {"status": "ok", "gap_pct": 1.4, "relative_volume": 1.3},   # agree up
               "BBB": {"status": "ok", "gap_pct": 0.5, "relative_volume": None},  # differ (up vs down)
               "CCC": {"status": "error"}})                                       # not both-ok
    result = pv.compare_pv_sources(write=True)
    s = result["summary"]
    assert s["tickers"] == 3
    assert s["both_ok"] == 2               # AAA, BBB
    assert s["direction_agreement"] == 1   # only AAA agrees among both-ok
    assert s["rel_volume_usable_both"] == 1
    assert result["report_path"] and result["report_path"].endswith(".json")


def test_write_false_skips_report(monkeypatch, tmp_path):
    monkeypatch.setattr(pv, "REPORT_DIR", tmp_path)
    _feeds(monkeypatch, {}, {})
    result = pv.compare_pv_sources(write=False)
    assert result["report_path"] is None
    assert list(tmp_path.iterdir()) == []


def test_service_wrapper_returns_summary(monkeypatch, tmp_path):
    from alpha_lab.service import AlphaLabService
    monkeypatch.setattr(pv, "REPORT_DIR", tmp_path)
    _feeds(monkeypatch,
           {"AAA": {"status": "ok", "gap_pct": 1.0, "relative_volume": 1.0}},
           {"AAA": {"status": "ok", "gap_pct": 1.0, "relative_volume": 1.0}})
    out = AlphaLabService(db_path=str(tmp_path / "s.sqlite3")).run_pv_source_compare()
    assert out["status"] == "ok" and out["both_ok"] == 1 and out["direction_agreement"] == 1
