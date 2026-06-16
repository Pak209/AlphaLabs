"""
alpha_lab/options_flow.py — the Options Flow Agent.

Detects unusual options activity / smart-money positioning and turns it into a
conviction *modifier* for an already-catalyst-driven idea. It NEVER triggers a
trade on its own — see the hard gate in scoring_engine.composite().

Two layers:
  1. A provider interface (OptionsFlowProvider) that returns raw chain stats for
     a ticker, plus a StubOptionsFlowProvider that returns None ("no data"). A
     real feed (Polygon options, Unusual Whales, etc.) implements the same
     interface later with zero changes here.
  2. A deterministic scorer (score_options_flow) that applies the framework's
     point system and emits an OptionsFlowSignal (the public JSON) plus a 0-100
     ComponentScore for the composite.

Point system (from the spec):
    call volume > 3x normal   -> +2
    call volume > 5x normal   -> +4
    call volume > 10x normal  -> +6   (highest matching bucket only)
    call/put ratio > 2        -> +2
    call/put ratio > 4        -> +4   (highest matching bucket only)
    open interest increasing  -> +2
    OI + call volume both up  -> +4   (supersedes the +2)
    large put buying          -> bearish adjustment (negative points)

Raw points are mapped onto a 0-100 component sub-score (50 = neutral) so the
modifier can both *increase* (bullish flow) and *decrease* (heavy put buying)
conviction. No data -> the component is omitted entirely (no effect), not 50.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel

from alpha_lab.scoring_models import ComponentScore, SubSignal


# Max attainable bullish points: call_vol +6, cp_ratio +4, oi+callvol +4 = 14.
_MAX_POINTS = 14.0


class OptionsFlowInputs(BaseModel):
    """Raw options-chain statistics for one ticker (one provider snapshot)."""
    ticker: str
    call_volume: int = 0
    put_volume: int = 0
    avg_call_volume: float = 0.0      # trailing "normal" call volume baseline
    open_interest: int = 0
    prior_open_interest: int = 0      # OI at the previous snapshot (for the delta)
    put_buy_premium_usd: float = 0.0  # notional of aggressive (ask-side) put buying
    call_buy_premium_usd: float = 0.0 # notional of aggressive (ask-side) call buying

    @property
    def call_put_ratio(self) -> float:
        if self.put_volume <= 0:
            return float(self.call_volume) if self.call_volume else 0.0
        return self.call_volume / self.put_volume

    @property
    def call_volume_multiple(self) -> Optional[float]:
        if self.avg_call_volume <= 0:
            return None
        return self.call_volume / self.avg_call_volume

    @property
    def open_interest_change(self) -> int:
        return self.open_interest - self.prior_open_interest


class OptionsFlowSignal(BaseModel):
    """
    Public agent output. The first block matches the spec's JSON shape; the
    remaining fields make the signal auditable and feed the composite.
    """
    ticker: str
    call_volume: int
    put_volume: int
    call_put_ratio: float
    open_interest_change: int
    options_score: int            # raw point total from the framework (can be negative)
    summary: str

    # — extra, for scoring + logging —
    component_score: float        # 0-100 sub-score for the composite (50 = neutral)
    bias: str                     # "bullish" | "bearish" | "neutral"
    has_data: bool
    call_volume_multiple: Optional[float] = None
    component: Optional[ComponentScore] = None  # 0-100 breakdown for the composite


@runtime_checkable
class OptionsFlowProvider(Protocol):
    """Returns chain stats for a ticker, or None when no data is available."""
    def fetch(self, ticker: str) -> Optional[OptionsFlowInputs]: ...


class StubOptionsFlowProvider:
    """Default provider: always 'no data'. Replace with a real feed later."""
    def fetch(self, ticker: str) -> Optional[OptionsFlowInputs]:  # noqa: ARG002
        return None


# ─── Live provider: Polygon/Massive Options (free "Options Basic" tier) ────────
#
# What the free plan actually entitles (probed empirically, mirrors Futures Basic):
#   * /v3/reference/options/contracts          -> chain reference (strikes/expiries)
#   * /v2/aggs/ticker/{contract}/range/.../day -> per-contract EOD OHLCV (volume)
# What it does NOT entitle (403 NOT_AUTHORIZED):
#   * /v3/snapshot/options/{underlying}        -> the only source of open_interest
#                                                 and per-side aggressive premium
# And grouped daily aggregates aren't offered for the options market at all.
#
# Consequence: this provider derives call/put VOLUME (and a trailing call-volume
# multiple) from EOD aggregates over a bounded near-the-money window. open_interest
# and put/call buy-premium are left at 0 — score_options_flow already treats those
# buckets as "no data" (0 points) rather than inventing a signal. Efficiency: ONE
# range-aggregates call per contract returns both the session-day volume and the
# prior-day baseline, so the call-volume multiple costs no extra requests.
#
# Read-only and graceful: a missing key, 403/429, bad ticker, or empty chain all
# degrade to None ("no data"), never an exception that breaks the premarket read.
# Given the 5-calls/min free limit, this is built for the offline overnight pull on
# a small watchlist, not interactive per-request use.

POLYGON_OPTIONS_BASE = os.getenv("POLYGON_OPTIONS_BASE_URL", "https://api.polygon.io").rstrip("/")
# Per-request floor (seconds) so a multi-contract chain throttles itself under the
# free 5/min limit instead of getting 429'd. 0 disables throttling (tests/paid).
POLYGON_OPTIONS_MIN_INTERVAL_SEC = float(os.getenv("POLYGON_OPTIONS_MIN_INTERVAL_SEC", "0") or 0)


class PolygonOptionsFlowProvider:
    """Live near-the-money options flow from Polygon/Massive EOD aggregates."""

    def __init__(self, api_key: Optional[str] = None,
                 min_interval_sec: Optional[float] = None,
                 session_date: Optional[str] = None,
                 strike_band_pct: float = 0.05,
                 max_contracts_per_side: int = 8,
                 baseline_days: int = 20):
        self.api_key = (api_key or os.getenv("POLYGON_API_KEY", "")).strip()
        self.min_interval_sec = (POLYGON_OPTIONS_MIN_INTERVAL_SEC
                                 if min_interval_sec is None else min_interval_sec)
        # Session whose EOD flow we read; defaults to the most recent weekday.
        self.session_date = session_date or _recent_weekday().isoformat()
        self.strike_band_pct = strike_band_pct
        self.max_contracts_per_side = max_contracts_per_side
        self.baseline_days = baseline_days
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        if self.min_interval_sec <= 0:
            return
        wait = self.min_interval_sec - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _get(self, path: str, params: dict) -> Optional[dict]:
        """Throttled, read-only GET returning parsed JSON, or None on any failure."""
        query = urlencode({**params, "apiKey": self.api_key})
        url = f"{POLYGON_OPTIONS_BASE}{path}?{query}"
        self._throttle()
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        finally:
            self._last_request_at = time.monotonic()

    def _spot(self, ticker: str) -> Optional[float]:
        """Underlying's close *on the session date*, to center the strike window.

        Uses the session-date daily bar (not /prev) so historical backtest pulls
        select strikes that were near the money *then*, not at today's price.
        """
        d = self.session_date
        data = self._get(f"/v2/aggs/ticker/{ticker}/range/1/day/{d}/{d}",
                         {"adjusted": "true"})
        results = (data or {}).get("results") or []
        if not results:
            return None
        close = results[0].get("c")
        return float(close) if close else None

    def _near_money_contracts(self, ticker: str, contract_type: str,
                              spot: float) -> list[str]:
        """Nearest-expiration calls/puts within the strike band, closest-to-spot."""
        lo = round(spot * (1 - self.strike_band_pct), 2)
        hi = round(spot * (1 + self.strike_band_pct), 2)
        data = self._get("/v3/reference/options/contracts", {
            "underlying_ticker": ticker,
            "contract_type": contract_type,
            "as_of": self.session_date,
            "expiration_date.gte": self.session_date,
            "strike_price.gte": lo,
            "strike_price.lte": hi,
            "sort": "expiration_date",
            "order": "asc",
            "limit": 100,
        })
        results = (data or {}).get("results") or []
        if not results:
            return []
        # Keep only the single nearest expiration, then the strikes closest to spot.
        nearest = results[0].get("expiration_date")
        chain = [r for r in results if r.get("expiration_date") == nearest]
        chain.sort(key=lambda r: abs(float(r.get("strike_price", 0)) - spot))
        return [r["ticker"] for r in chain[:self.max_contracts_per_side] if r.get("ticker")]

    def _session_and_baseline_volume(self, contract: str) -> tuple[int, float]:
        """One range call -> (session-day volume, mean prior-day volume baseline)."""
        end = self.session_date
        start = (date.fromisoformat(self.session_date)
                 - timedelta(days=self.baseline_days * 2)).isoformat()
        data = self._get(f"/v2/aggs/ticker/{contract}/range/1/day/{start}/{end}",
                         {"adjusted": "true", "sort": "asc", "limit": 5000})
        bars = (data or {}).get("results") or []
        if not bars:
            return 0, 0.0
        session = date.fromisoformat(self.session_date)
        session_vol = 0
        prior_vols: list[int] = []
        for b in bars:
            v = int(b.get("v", 0) or 0)
            # Polygon stamps each daily bar at midnight UTC of that session.
            bar_day = datetime.utcfromtimestamp(int(b.get("t", 0)) / 1000).date()
            if bar_day >= session:
                session_vol = v
            else:
                prior_vols.append(v)
        baseline = sum(prior_vols) / len(prior_vols) if prior_vols else 0.0
        return session_vol, baseline

    def fetch(self, ticker: str) -> Optional[OptionsFlowInputs]:
        ticker = ticker.strip().upper()
        if not self.api_key or not ticker:
            return None
        spot = self._spot(ticker)
        if not spot:
            return None
        calls = self._near_money_contracts(ticker, "call", spot)
        puts = self._near_money_contracts(ticker, "put", spot)
        if not calls and not puts:
            return None

        call_volume = 0
        call_baseline = 0.0
        for c in calls:
            v, base = self._session_and_baseline_volume(c)
            call_volume += v
            call_baseline += base
        put_volume = 0
        for p in puts:
            v, _ = self._session_and_baseline_volume(p)
            put_volume += v

        if call_volume == 0 and put_volume == 0:
            return None
        # open_interest / premium fields stay 0: not entitled on the free plan, so
        # the scorer's OI and put-buying buckets correctly contribute 0 points.
        return OptionsFlowInputs(
            ticker=ticker,
            call_volume=call_volume,
            put_volume=put_volume,
            avg_call_volume=round(call_baseline, 2),
        )


def _recent_weekday(ref: Optional[date] = None) -> date:
    """Most recent weekday on/before ``ref`` (today ET-ish), for EOD reads."""
    d = ref or date.today()
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


# ─── Point system ─────────────────────────────────────────────────────────────

def _call_volume_points(multiple: Optional[float]) -> int:
    if multiple is None:
        return 0
    if multiple > 10:
        return 6
    if multiple > 5:
        return 4
    if multiple > 3:
        return 2
    return 0


def _call_put_ratio_points(ratio: float) -> int:
    if ratio > 4:
        return 4
    if ratio > 2:
        return 2
    return 0


def _open_interest_points(oi_change: int, call_volume_rising: bool) -> int:
    if oi_change <= 0:
        return 0
    return 4 if call_volume_rising else 2


def _put_buying_points(inputs: OptionsFlowInputs) -> int:
    """
    Heavy, aggressive put buying is a bearish adjustment. Scaled by how dominant
    put premium is vs call premium so a little hedging noise doesn't flip bias.
    """
    put_prem = inputs.put_buy_premium_usd
    call_prem = inputs.call_buy_premium_usd
    if put_prem < 1_000_000:          # below $1M aggressive puts: ignore as noise
        return 0
    if put_prem >= call_prem * 2:     # puts dominate calls 2:1 -> strong bearish
        return -6
    if put_prem > call_prem:          # puts lead calls -> moderate bearish
        return -3
    return 0


def _points_to_component(points: int) -> float:
    """Map framework points onto a 0-100 sub-score; 0 points -> neutral 50."""
    raw = 50.0 + (points / _MAX_POINTS) * 50.0
    return round(max(0.0, min(100.0, raw)), 1)


def _bias_for(points: int) -> str:
    if points >= 4:
        return "bullish"
    if points <= -3:
        return "bearish"
    return "neutral"


def _summarize(points: int, bias: str) -> str:
    if bias == "bullish":
        return "Bullish options activity detected"
    if bias == "bearish":
        return "Bearish options positioning detected (heavy put buying)"
    return "No unusual options activity"


def score_options_flow(inputs: Optional[OptionsFlowInputs],
                       ticker: Optional[str] = None) -> OptionsFlowSignal:
    """
    Apply the point system to a provider snapshot. With no data, returns a
    has_data=False signal whose component is neutral and which the composite
    excludes entirely (no conviction effect in either direction).
    """
    if inputs is None:
        t = (ticker or "").strip().upper()
        return OptionsFlowSignal(
            ticker=t, call_volume=0, put_volume=0, call_put_ratio=0.0,
            open_interest_change=0, options_score=0,
            summary="No options-flow data available",
            component_score=50.0, bias="neutral", has_data=False,
            call_volume_multiple=None,
        )

    multiple = inputs.call_volume_multiple
    ratio = inputs.call_put_ratio
    oi_change = inputs.open_interest_change
    call_volume_rising = (multiple is not None and multiple > 1.0)

    cv_pts = _call_volume_points(multiple)
    cpr_pts = _call_put_ratio_points(ratio)
    oi_pts = _open_interest_points(oi_change, call_volume_rising)
    put_pts = _put_buying_points(inputs)
    points = cv_pts + cpr_pts + oi_pts + put_pts

    component = _points_to_component(points)
    bias = _bias_for(points)

    signals = [
        SubSignal(name="call_volume", value=float(cv_pts), weight=1.0,
                  detail=(f"call vol {multiple:.1f}x normal -> +{cv_pts}"
                          if multiple is not None else "no call-vol baseline -> +0")),
        SubSignal(name="call_put_ratio", value=float(cpr_pts), weight=1.0,
                  detail=f"C/P {ratio:.2f} -> +{cpr_pts}"),
        SubSignal(name="open_interest", value=float(oi_pts), weight=1.0,
                  detail=f"OI change {oi_change:+d}, call vol rising={call_volume_rising} -> +{oi_pts}"),
        SubSignal(name="put_buying", value=float(put_pts), weight=1.0,
                  detail=f"aggressive put premium ${inputs.put_buy_premium_usd:,.0f} -> {put_pts:+d}"),
    ]
    expl = (f"points = call_vol {cv_pts:+d} + cp_ratio {cpr_pts:+d} + "
            f"oi {oi_pts:+d} + puts {put_pts:+d} = {points:+d} -> component {component:g}")
    return OptionsFlowSignal(
        ticker=inputs.ticker.strip().upper(),
        call_volume=inputs.call_volume,
        put_volume=inputs.put_volume,
        call_put_ratio=round(ratio, 3),
        open_interest_change=oi_change,
        options_score=points,
        summary=_summarize(points, bias),
        component_score=component,
        bias=bias,
        has_data=True,
        call_volume_multiple=round(multiple, 2) if multiple is not None else None,
        component=ComponentScore(score=component, signals=signals, explanation=expl),
    )


def component_from_signal(signal: OptionsFlowSignal) -> Optional[ComponentScore]:
    """Return the 0-100 ComponentScore for the composite, or None if no data."""
    return signal.component if signal.has_data else None
