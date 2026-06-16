"""
tests/test_futures_pulse.py — the Overnight Futures Pulse Agent.

Everything except the network provider is a pure function, so each test feeds
fixed OvernightSeries inputs and asserts exact move math, regime classification,
watchlist mapping, and the read-only strategy-signal conversion. No network.
"""
from datetime import datetime
from typing import Optional

from alpha_lab.futures_pulse import (
    CONTRACTS_BY_SYMBOL,
    FuturesContractSpec,
    FuturesDataProvider,
    OvernightBar,
    OvernightSeries,
    StubFuturesDataProvider,
    build_pulse_report,
    classify_regime,
    compute_move,
    front_month_ticker,
    report_to_strategy_signals,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _series(symbol: str, prices: list[float], prior_close: float,
            avg: Optional[float] = None, start_hour: int = 18) -> OvernightSeries:
    """Build an OvernightSeries from a list of closes (open == prior close)."""
    bars = []
    for i, px in enumerate(prices):
        prev = prices[i - 1] if i else px
        bars.append(OvernightBar(
            ts=f"2026-06-15T{(start_hour + i) % 24:02d}:00:00-04:00",
            open=prev, high=max(prev, px), low=min(prev, px), close=px, volume=1000,
        ))
    return OvernightSeries(symbol=symbol, bars=bars, prior_close=prior_close,
                           avg_overnight_move_pct_20d=avg)


class FakeProvider:
    """Returns a preloaded series per symbol; None otherwise (no data)."""
    def __init__(self, by_symbol: dict[str, OvernightSeries]):
        self.by_symbol = by_symbol

    def fetch_overnight(self, spec: FuturesContractSpec, session_date: str,
                        timespan: str = "minute", multiplier: int = 5):
        return self.by_symbol.get(spec.symbol)


# ─── compute_move (pure) ──────────────────────────────────────────────────────

def test_compute_move_basic_up():
    spec = CONTRACTS_BY_SYMBOL["ES"]
    series = _series("ES", [5000, 5025, 5050], prior_close=5000.0, avg=0.5)
    move = compute_move(spec, series)
    assert move.has_data is True
    assert move.last_price == 5050.0
    assert move.net_move_pct == 1.0            # (5050-5000)/5000*100
    assert move.direction == "up"
    assert move.overnight_high == 5050.0
    assert move.overnight_low == 5000.0
    assert move.move_vs_avg == 2.0             # 1.0 / 0.5
    assert move.unusual is True                # 2.0 >= 1.5


def test_compute_move_no_data():
    spec = CONTRACTS_BY_SYMBOL["ES"]
    assert compute_move(spec, None).has_data is False
    empty = OvernightSeries(symbol="ES", bars=[], prior_close=5000.0)
    assert compute_move(spec, empty).has_data is False


def test_compute_move_flat_deadband():
    spec = CONTRACTS_BY_SYMBOL["ES"]
    series = _series("ES", [5000, 5000.2], prior_close=5000.0)   # 0.004% move
    assert compute_move(spec, series).direction == "flat"


def test_compute_move_catalyst_window():
    spec = CONTRACTS_BY_SYMBOL["CL"]
    series = _series("CL", [80, 80, 84], prior_close=80.0, start_hour=18)
    # bars at 18:00/19:00/20:00; catalyst at 19:00 anchors to close=80 -> (84-80)/80 = 5%
    move = compute_move(spec, series, catalyst_ts="2026-06-15T19:00:00-04:00")
    assert move.catalyst_move_pct == 5.0


# ─── classify_regime (pure) ───────────────────────────────────────────────────

def _moves(by_symbol: dict[str, OvernightSeries]):
    return [compute_move(CONTRACTS_BY_SYMBOL[s], by_symbol.get(s))
            for s in CONTRACTS_BY_SYMBOL]


def test_classify_risk_off():
    board = {
        "ES": _series("ES", [5000, 4950], 5000.0, avg=0.4),    # -1.0%
        "NQ": _series("NQ", [18000, 17820], 18000.0, avg=0.5), # -1.0%
        "GC": _series("GC", [2300, 2330], 2300.0, avg=0.6),    # +1.3% haven bid
        "VX": _series("VX", [15, 16.5], 15.0, avg=3.0),        # +10% vol spike
        "ZN": _series("ZN", [110, 110.5], 110.0, avg=0.2),     # bonds bid
    }
    reg = classify_regime(_moves(board))
    assert reg.regime == "risk_off"
    assert reg.confidence > 50
    assert reg.scores["risk_off"] > reg.scores["risk_on"]


def test_classify_oil_shock():
    board = {
        "CL": _series("CL", [80, 85], 80.0, avg=1.5),          # +6.25% crude spike
        "ES": _series("ES", [5000, 4985], 5000.0, avg=0.4),    # -0.3% soft
    }
    reg = classify_regime(_moves(board))
    assert reg.regime in ("oil_shock", "mixed")
    assert reg.scores["oil_shock"] > 0


def test_classify_neutral_when_no_data():
    reg = classify_regime(_moves({}))
    assert reg.regime == "neutral"
    assert reg.confidence == 0.0


# ─── build_pulse_report + provider behavior ───────────────────────────────────

def test_build_report_no_data_with_stub():
    report = build_pulse_report(StubFuturesDataProvider(), session_date="2026-06-15")
    assert report.status == "no_data"
    assert report.regime.regime == "neutral"
    assert all(not m.has_data for m in report.moves)
    assert any("provider data" in n for n in report.notes)


def test_build_report_ok_and_signals():
    board = {
        "ES": _series("ES", [5000, 5060], 5000.0, avg=0.4),    # +1.2% risk-on
        "NQ": _series("NQ", [18000, 18270], 18000.0, avg=0.5), # +1.5%
        "VX": _series("VX", [15, 14.0], 15.0, avg=3.0),        # -6.7% vol down
    }
    report = build_pulse_report(FakeProvider(board), session_date="2026-06-15")
    assert report.status == "ok"
    assert report.regime.regime == "risk_on"
    assert report.watchlist                                  # non-empty
    assert isinstance(report, type(report))

    signals = report_to_strategy_signals(report)
    assert signals
    for sig in signals:
        assert sig["source"] == "futures_pulse"
        assert sig["bias"] in ("bullish", "bearish")
        assert "Overnight Futures Pulse" in sig["thesis"]
        assert report.regime.regime in sig["strategy_tags"]


def test_signals_empty_when_no_data():
    report = build_pulse_report(StubFuturesDataProvider(), session_date="2026-06-15")
    assert report_to_strategy_signals(report) == []


def test_stub_provider_is_futures_data_provider():
    assert isinstance(StubFuturesDataProvider(), FuturesDataProvider)


# ─── front_month_ticker (pure) ────────────────────────────────────────────────

def test_front_month_equity_index_quarterly():
    es = CONTRACTS_BY_SYMBOL["ES"]
    # June -> M6 (June is itself a quarterly month, on/after ref month)
    assert front_month_ticker(es, datetime(2026, 6, 15)) == "ESM6"
    # July -> next quarterly is Sept (U)
    assert front_month_ticker(es, datetime(2026, 7, 1)) == "ESU6"
    # January -> nearest quarterly is March (H)
    assert front_month_ticker(es, datetime(2026, 1, 5)) == "ESH6"


def test_front_month_rolls_to_next_year():
    es = CONTRACTS_BY_SYMBOL["ES"]
    # Dec 20 is past the Dec contract's ~3rd-Friday (18th) last trade, so the
    # roll buffer advances to next year's first quarterly (March -> H7).
    assert front_month_ticker(es, datetime(2026, 12, 20)) == "ESH7"
    # Gold cycle G,J,M,Q,V,Z: November -> December (Z) same year.
    gc = CONTRACTS_BY_SYMBOL["GC"]
    assert front_month_ticker(gc, datetime(2026, 11, 1)) == "GCZ6"


def test_front_month_energy_roll_buffer():
    # Crude/nat-gas expire ~a month BEFORE the delivery month, so the calendar
    # month code is already dead — the buffer must resolve to the live front month.
    cl = CONTRACTS_BY_SYMBOL["CL"]
    # On Apr 10 the April (J) contract already expired (~Mar 20); roll to May (K).
    assert front_month_ticker(cl, datetime(2026, 4, 10)) == "CLK6"
    # On Jun 12 the June (M) contract already expired; active front is July (N).
    assert front_month_ticker(cl, datetime(2025, 6, 12)) == "CLN5"
    ng = CONTRACTS_BY_SYMBOL["NG"]
    # Nat gas on Jun 12: June expired ~May 25, so July (N) is the live front month.
    assert front_month_ticker(ng, datetime(2025, 6, 12)) == "NGN5"
