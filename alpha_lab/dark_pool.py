"""
alpha_lab/dark_pool.py — the Dark Pool / TRF Agent.

Detects institutional participation and accumulation from FINRA TRF / dark-pool
prints and turns it into a conviction *modifier* for an already-catalyst-driven
idea. Like the options-flow agent, it NEVER triggers a trade on its own — the
hard gate in scoring_engine.composite() enforces that.

Two layers:
  1. A provider interface (DarkPoolProvider) returning aggregated print stats for
     a ticker, plus a StubDarkPoolProvider that returns None ("no data"). A real
     feed (FINRA ADF/TRF, Polygon trades w/ TRF exchange codes, etc.) implements
     the same interface later with zero changes here.
  2. A deterministic scorer (score_institutional) applying the framework's point
     system and emitting an InstitutionalSignal (public JSON) plus a 0-100
     ComponentScore for the composite.

Point system (from the spec, escalating tiers — highest applicable wins):
    single large TRF print > $1M  -> +1
    repeated large prints         -> +3
    multi-day accumulation        -> +5

IMPORTANT: a dark-pool print is NOT inherently bullish. This agent scores the
*strength* of institutional participation (a conviction magnitude); the trade's
direction comes from the catalyst, not from the prints. Bias stays neutral unless
the feed supplies a clear directional (buy/sell pressure) read.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel

from alpha_lab.scoring_models import ComponentScore, SubSignal


_SINGLE_PRINT_MIN_USD = 1_000_000.0
_MAX_POINTS = 5.0


class DarkPoolInputs(BaseModel):
    """Aggregated dark-pool / TRF print statistics for one ticker."""
    ticker: str
    dark_pool_notional: float = 0.0      # total dark-pool notional in the window
    block_count: int = 0                 # number of large block prints
    largest_print_usd: float = 0.0       # biggest single TRF print
    repeated_large_prints: bool = False  # multiple $1M+ prints in the window
    multi_day_accumulation: bool = False # same-direction persistence across days
    accumulation_days: int = 0           # how many consecutive days of buildup
    direction: Optional[str] = None      # "buy" | "sell" | None (do NOT assume)


class InstitutionalSignal(BaseModel):
    """
    Public agent output. The first block matches the spec's JSON shape; the rest
    make the signal auditable and feed the composite.
    """
    ticker: str
    dark_pool_notional: float
    block_count: int
    institutional_score: int      # raw point total from the framework (0-5)
    summary: str

    # — extra, for scoring + logging —
    component_score: float        # 0-100 sub-score for the composite (50 = neutral)
    bias: str                     # "bullish" | "bearish" | "neutral" (usually neutral)
    has_data: bool
    accumulation_days: int = 0
    component: Optional[ComponentScore] = None  # 0-100 breakdown for the composite


@runtime_checkable
class DarkPoolProvider(Protocol):
    """Returns print stats for a ticker, or None when no data is available."""
    def fetch(self, ticker: str) -> Optional[DarkPoolInputs]: ...


class StubDarkPoolProvider:
    """Default provider: always 'no data'. Replace with a real feed later."""
    def fetch(self, ticker: str) -> Optional[DarkPoolInputs]:  # noqa: ARG002
        return None


# ─── Point system ─────────────────────────────────────────────────────────────

def _institutional_points(inputs: DarkPoolInputs) -> int:
    """Escalating tiers — strongest applicable pattern wins (not additive)."""
    if inputs.multi_day_accumulation:
        return 5
    if inputs.repeated_large_prints or inputs.block_count >= 2:
        return 3
    if inputs.largest_print_usd > _SINGLE_PRINT_MIN_USD:
        return 1
    return 0


def _points_to_component(points: int) -> float:
    """Map points onto 0-100; institutional strength only adds conviction (>=50)."""
    raw = 50.0 + (points / _MAX_POINTS) * 50.0
    return round(max(50.0, min(100.0, raw)), 1)


def _bias_for(inputs: DarkPoolInputs, points: int) -> str:
    """
    Only express a directional bias when the feed supplies a clear direction AND
    the participation is persistent (multi-day). Otherwise neutral — a print is
    not assumed bullish.
    """
    if points >= 5 and inputs.direction == "buy":
        return "bullish"
    if points >= 5 and inputs.direction == "sell":
        return "bearish"
    return "neutral"


def _summarize(points: int, inputs: DarkPoolInputs) -> str:
    if points >= 5:
        return "Institutional accumulation suspected"
    if points >= 3:
        return "Repeated institutional prints detected"
    if points >= 1:
        return "Single large institutional print detected"
    return "No notable institutional activity"


def score_institutional(inputs: Optional[DarkPoolInputs],
                        ticker: Optional[str] = None) -> InstitutionalSignal:
    """
    Apply the point system to a provider snapshot. With no data, returns a
    has_data=False signal whose component is neutral and which the composite
    excludes entirely (no conviction effect).
    """
    if inputs is None:
        t = (ticker or "").strip().upper()
        return InstitutionalSignal(
            ticker=t, dark_pool_notional=0.0, block_count=0,
            institutional_score=0, summary="No dark-pool/TRF data available",
            component_score=50.0, bias="neutral", has_data=False,
            accumulation_days=0,
        )

    points = _institutional_points(inputs)
    component = _points_to_component(points)
    bias = _bias_for(inputs, points)

    signals = [
        SubSignal(name="single_print", value=float(inputs.largest_print_usd), weight=1.0,
                  detail=f"largest print ${inputs.largest_print_usd:,.0f}"),
        SubSignal(name="repeated_prints", value=float(inputs.block_count), weight=1.0,
                  detail=f"{inputs.block_count} blocks, repeated={inputs.repeated_large_prints}"),
        SubSignal(name="multi_day", value=float(inputs.accumulation_days), weight=1.0,
                  detail=f"multi_day={inputs.multi_day_accumulation} ({inputs.accumulation_days}d)"),
    ]
    expl = (f"tier points = {points} (single>$1M:+1, repeated:+3, multi-day:+5) "
            f"-> component {component:g}")

    return InstitutionalSignal(
        ticker=inputs.ticker.strip().upper(),
        dark_pool_notional=round(inputs.dark_pool_notional, 2),
        block_count=inputs.block_count,
        institutional_score=points,
        summary=_summarize(points, inputs),
        component_score=component,
        bias=bias,
        has_data=True,
        accumulation_days=inputs.accumulation_days,
        component=ComponentScore(score=component, signals=signals, explanation=expl),
    )


def component_from_signal(signal: InstitutionalSignal) -> Optional[ComponentScore]:
    """Return the 0-100 ComponentScore for the composite, or None if no data."""
    return signal.component if signal.has_data else None
