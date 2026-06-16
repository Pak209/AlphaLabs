"""
alpha_lab/scoring_models.py — data models for the MVP Analyst Brain scoring engine.

These are the deterministic outputs of alpha_lab/scoring_engine.py. Every score
carries its sub-signal breakdown and a human-readable explanation so each paper
trade has a fully auditable "why". See docs/analyst-brain-mvp-engine.md for design.
"""
from typing import Optional

from pydantic import BaseModel


class SubSignal(BaseModel):
    """One weighted input to a component score, on a 0-100 sub-scale."""
    name: str
    value: float            # 0-100 sub-signal score
    weight: float           # weight within the parent component (sums to 1.0)
    detail: str             # how this sub-signal got its value


class ComponentScore(BaseModel):
    """A single 0-100 component score (Catalyst, Narrative, or Macro)."""
    score: float                    # 0-100, rounded to 1 dp
    signals: list[SubSignal]
    explanation: str                # shows the weighted-sum math


class AlphaScore(BaseModel):
    """
    The full scoring result attached to a trade idea.

    Composite weights (sum to 1.0):
        Catalyst 0.35, Price/Volume 0.20, Narrative 0.15,
        Options Flow 0.15, Institutional 0.10, Macro 0.05.

    Options Flow and Institutional are *conviction modifiers*: they only count
    when the idea is "confirmed" (a real catalyst AND price/volume confirmation).
    When unconfirmed, a hard gate excludes them and caps the tier at 'watchlist'
    so unusual options / dark-pool activity can never trigger a trade on its own.
    Components with no provider data are omitted and the remaining weights are
    renormalized, so absence is neutral (no penalty), not a 50 drag.
    """
    catalyst_score: float
    price_volume_score: Optional[float]
    narrative_score: float
    options_score: Optional[float]
    institutional_score: Optional[float]
    macro_score: float
    composite_score: float
    tier: str                       # high_conviction | tradeable | watchlist | ignore

    catalyst: ComponentScore
    price_volume: Optional[ComponentScore] = None
    narrative: ComponentScore
    options: Optional[ComponentScore] = None
    institutional: Optional[ComponentScore] = None
    macro: ComponentScore

    confirmed: bool = False         # catalyst + price/volume both confirm
    gate_applied: bool = False      # modifiers excluded + tier capped (rule enforced)
    composite_explanation: str
    floors_applied: list[str] = []  # e.g. ["macro_floor", "catalyst_floor", "confirmation_gate"]


class PriceVolumeInputs(BaseModel):
    """Inputs for the price/volume confirmation component."""
    bias: str = "neutral"                       # idea direction: bullish|bearish|neutral
    relative_volume: Optional[float] = None     # session volume / average (1.0 = normal)
    gap_pct: float = 0.0                         # signed % move at/after the catalyst
    trend_confirms: Optional[bool] = None        # price action agrees with the bias


# ─── Engine input models (kept explicit so scoring is a pure function) ─────────

class CatalystInputs(BaseModel):
    catalyst_type: str              # key into the catalyst-type weight table
    gap_pct: float = 0.0            # signed % move at detection (surprise proxy)
    prior_count_30d: int = 0        # same ticker+type catalysts in trailing 30d
    materiality: float = 50.0       # 0-100 heuristic event size


class NarrativeInputs(BaseModel):
    theme: str = "none"             # key into the theme base-score table
    phase: str = "expansion"        # expansion_transition|expansion|peak|fading
    theme_etf_return_4w_pct: Optional[float] = None  # 4-week ETF return, flow proxy


class MacroInputs(BaseModel):
    fed_stance: str = "neutral_hold"     # cutting|dovish_hold|neutral_hold|hawkish_hold|hiking
    cpi_trend: str = "flat"              # falling2|falling1|flat|rising1|rising2
    spx_above_200ma: bool = True
    vix: float = 20.0
    ten_year_yield_trend: str = "flat"   # falling|flat|rising
    dxy_trend: str = "flat"              # falling|flat|rising
