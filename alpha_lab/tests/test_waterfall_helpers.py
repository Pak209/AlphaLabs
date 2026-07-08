"""Focused unit tests for the pure helpers promoted in Phase 2 PR2.

Integration behavior is pinned by test_waterfall_golden.py; these cover the
boundary semantics of the two promoted pure functions that the golden's seed
cannot economically enumerate.
"""
from __future__ import annotations

from alpha_lab.waterfall import _near_miss, _quantiles


def record(observed, threshold, comparator=">="):
    return {"observed": observed, "threshold": threshold, "comparator": comparator}


# ─── _near_miss ───────────────────────────────────────────────────────────────

def test_near_miss_ge_comparator_boundaries():
    assert _near_miss(record(0.72, 0.75)) is True          # inside the 10% margin
    assert _near_miss(record(0.675, 0.75)) is True         # exactly at the margin
    assert _near_miss(record(0.6749, 0.75)) is False       # just past the margin
    assert _near_miss(record(0.75, 0.75)) is True          # zero shortfall counts
    assert _near_miss(record(0.80, 0.75)) is False         # passed side: not a miss


def test_near_miss_lt_comparator_mirrors():
    assert _near_miss(record(21, 20, "<")) is True          # 1 over on a 2.0 margin
    assert _near_miss(record(23, 20, "<")) is False
    assert _near_miss(record(19, 20, "<")) is False         # under the limit: not a miss


def test_near_miss_rejects_non_numeric_and_unknown_comparators():
    assert _near_miss(record(None, 0.75)) is False
    assert _near_miss(record(0.72, "high")) is False
    assert _near_miss(record("BTC", "crypto", "!=")) is False
    assert _near_miss(record(0.72, 0.75, "in")) is False


def test_near_miss_zero_threshold_uses_absolute_margin():
    assert _near_miss(record(-0.05, 0)) is True             # within 0.1 absolute
    assert _near_miss(record(-0.2, 0)) is False


# ─── _quantiles ───────────────────────────────────────────────────────────────

def test_quantiles_empty_returns_none():
    assert _quantiles([]) is None


def test_quantiles_single_value_collapses():
    stats = _quantiles([0.75])
    assert stats == {"count": 1, "min": 0.75, "p25": 0.75,
                     "p50": 0.75, "p75": 0.75, "max": 0.75}


def test_quantiles_ties_and_rounding():
    stats = _quantiles([0.123456, 0.123456, 0.9, 0.9])
    assert stats["count"] == 4
    assert stats["min"] == 0.1235                           # rounded to 4 dp
    assert stats["max"] == 0.9
    assert stats["p25"] == 0.1235 and stats["p75"] == 0.9


def test_quantiles_order_insensitive():
    assert _quantiles([3.0, 1.0, 2.0]) == _quantiles([1.0, 2.0, 3.0])
