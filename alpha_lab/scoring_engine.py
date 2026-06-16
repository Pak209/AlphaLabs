"""
alpha_lab/scoring_engine.py — the MVP Analyst Brain scoring engine.

Deterministic, dependency-free scoring of catalysts into a Composite Alpha Score.
Every score is a weighted sum of fixed 0-100 sub-signals plus two override floors —
no ML, no network calls, no randomness. Given identical inputs it always returns
identical outputs, which makes it fully unit-testable.

Reference: docs/analyst-brain-mvp-engine.md

Public API:
    score_catalyst(inputs)   -> ComponentScore
    score_narrative(inputs)  -> ComponentScore
    score_macro(inputs)      -> ComponentScore
    composite(catalyst, narrative, macro) -> AlphaScore   (full result)
    score_idea(catalyst_inputs, narrative_inputs, macro_inputs) -> AlphaScore

Adapters that build engine inputs from existing platform objects:
    catalyst_inputs_from_alert(alert, prior_count_30d)
    narrative_inputs_for_ticker(ticker)
    macro_inputs_from_briefing(briefing)
"""
from __future__ import annotations

from typing import Optional

from alpha_lab.scoring_models import (
    SubSignal, ComponentScore, AlphaScore,
    CatalystInputs, NarrativeInputs, MacroInputs, PriceVolumeInputs,
)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _round(x: float) -> float:
    return round(x, 1)


# ─── 1. Catalyst Score ────────────────────────────────────────────────────────

# Static catalyst-type weight table (0-100). The heart of the catalyst score.
CATALYST_TYPE_WEIGHTS: dict[str, float] = {
    "m&a": 95,
    "acquisition": 95,
    "regulatory_approval": 90,
    "fda": 90,
    "contract": 85,
    "guidance_raise": 80,
    "earnings_beat": 80,
    "earnings": 80,
    "partnership_named": 70,
    "insider_buying": 60,
    "product_launch": 55,
    "analyst_upgrade": 45,
    "financing": 35,
    "partnership_vague": 30,
    "partnership": 30,
    "generic_pr": 15,
    "general": 15,
}
_DEFAULT_TYPE_WEIGHT = 15.0


def catalyst_type_weight(catalyst_type: str) -> float:
    return float(CATALYST_TYPE_WEIGHTS.get((catalyst_type or "").strip().lower(),
                                           _DEFAULT_TYPE_WEIGHT))


def novelty_score(prior_count_30d: int) -> float:
    """100 if first time in 30d, 50 if one prior, 20 if recycled (2+)."""
    if prior_count_30d <= 0:
        return 100.0
    if prior_count_30d == 1:
        return 50.0
    return 20.0


def surprise_score(gap_pct: float) -> float:
    """Map |price gap %| at detection to a 0-100 surprise proxy."""
    g = abs(gap_pct or 0.0)
    if g >= 8:
        return 100.0
    if g >= 5:
        return 80.0
    if g >= 3:
        return 60.0
    if g >= 1:
        return 40.0
    return 20.0


def score_catalyst(inputs: CatalystInputs) -> ComponentScore:
    type_w = catalyst_type_weight(inputs.catalyst_type)
    surprise = surprise_score(inputs.gap_pct)
    novelty = novelty_score(inputs.prior_count_30d)
    materiality = _clamp(inputs.materiality)

    signals = [
        SubSignal(name="catalyst_type", value=type_w, weight=0.40,
                  detail=f"type '{inputs.catalyst_type}' -> {type_w:g}"),
        SubSignal(name="surprise", value=surprise, weight=0.25,
                  detail=f"gap {inputs.gap_pct:+g}% -> {surprise:g}"),
        SubSignal(name="novelty", value=novelty, weight=0.20,
                  detail=f"{inputs.prior_count_30d} prior in 30d -> {novelty:g}"),
        SubSignal(name="materiality", value=materiality, weight=0.15,
                  detail=f"materiality {materiality:g}"),
    ]
    score = _round(sum(s.value * s.weight for s in signals))
    expl = (f"type {type_w:g}×.40 + surprise {surprise:g}×.25 + "
            f"novelty {novelty:g}×.20 + materiality {materiality:g}×.15 = {score:g}")
    return ComponentScore(score=score, signals=signals, explanation=expl)


# ─── 2. Narrative Score ───────────────────────────────────────────────────────

THEME_BASE_SCORES: dict[str, float] = {
    "ai": 100,
    "semiconductors": 90,
    "data_centers": 90,
    "energy": 80,
    "defense": 75,
    "robotics": 70,
    "crypto": 65,
    "emerging": 55,
    "none": 20,
}
_DEFAULT_THEME_SCORE = 20.0

PHASE_FACTORS: dict[str, float] = {
    "expansion_transition": 100,
    "expansion": 85,
    "peak": 50,
    "fading": 20,
}
_DEFAULT_PHASE_FACTOR = 85.0  # assume expansion if unknown

# Hand-curated config (MVP: a module-level map; edit by hand as themes rotate).
TICKER_THEME: dict[str, str] = {
    "NVDA": "ai", "AMD": "semiconductors", "AVGO": "semiconductors",
    "SMCI": "data_centers", "VRT": "data_centers", "DELL": "data_centers",
    "MSFT": "ai", "META": "ai", "GOOGL": "ai", "AAPL": "ai",
    "TSLA": "robotics", "PLTR": "ai",
    "VST": "energy", "CEG": "energy", "NEE": "energy",
    "LMT": "defense", "RTX": "defense",
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "COIN": "crypto", "MSTR": "crypto",
}
# Current narrative phase per theme (MVP: updated by hand, e.g. weekly).
THEME_PHASE: dict[str, str] = {
    "ai": "expansion",
    "semiconductors": "expansion",
    "data_centers": "expansion_transition",
    "energy": "expansion",
    "defense": "expansion",
    "robotics": "expansion",
    "crypto": "expansion",
    "emerging": "expansion_transition",
    "none": "fading",
}


def flow_direction_score(theme_etf_return_4w_pct: Optional[float]) -> float:
    """
    Convert trailing-4-week theme-ETF return into a 0-100 capital-flow proxy.
    No data available -> neutral 50.
    """
    if theme_etf_return_4w_pct is None:
        return 50.0
    r = theme_etf_return_4w_pct
    if r > 5:
        return 100.0   # strong inflow
    if r > 1:
        return 75.0    # mild inflow
    if r >= -1:
        return 50.0    # flat
    if r >= -5:
        return 25.0    # outflow
    return 0.0         # strong outflow


def theme_strength_score(theme: str) -> float:
    return float(THEME_BASE_SCORES.get((theme or "none").strip().lower(),
                                       _DEFAULT_THEME_SCORE))


def phase_factor_score(phase: str) -> float:
    return float(PHASE_FACTORS.get((phase or "").strip().lower(),
                                   _DEFAULT_PHASE_FACTOR))


def score_narrative(inputs: NarrativeInputs) -> ComponentScore:
    theme = theme_strength_score(inputs.theme)
    phase = phase_factor_score(inputs.phase)
    flow = flow_direction_score(inputs.theme_etf_return_4w_pct)

    signals = [
        SubSignal(name="theme_strength", value=theme, weight=0.50,
                  detail=f"theme '{inputs.theme}' -> {theme:g}"),
        SubSignal(name="phase_factor", value=phase, weight=0.30,
                  detail=f"phase '{inputs.phase}' -> {phase:g}"),
        SubSignal(name="flow_direction", value=flow, weight=0.20,
                  detail=(f"4w ETF return {inputs.theme_etf_return_4w_pct}%"
                          if inputs.theme_etf_return_4w_pct is not None
                          else "no flow data") + f" -> {flow:g}"),
    ]
    score = _round(sum(s.value * s.weight for s in signals))
    expl = (f"theme {theme:g}×.50 + phase {phase:g}×.30 + "
            f"flow {flow:g}×.20 = {score:g}")
    return ComponentScore(score=score, signals=signals, explanation=expl)


# ─── 3. Macro Score ───────────────────────────────────────────────────────────

FED_STANCE_SCORES: dict[str, float] = {
    "cutting": 100,
    "dovish_hold": 100,
    "neutral_hold": 60,
    "hawkish_hold": 40,
    "hiking": 15,
}
_DEFAULT_FED_SCORE = 60.0

CPI_TREND_SCORES: dict[str, float] = {
    "falling2": 100,
    "falling1": 80,
    "flat": 60,
    "rising1": 35,
    "rising2": 10,
}
_DEFAULT_CPI_SCORE = 60.0


def fed_rate_signal(fed_stance: str) -> float:
    return float(FED_STANCE_SCORES.get((fed_stance or "").strip().lower(),
                                       _DEFAULT_FED_SCORE))


def inflation_signal(cpi_trend: str) -> float:
    return float(CPI_TREND_SCORES.get((cpi_trend or "").strip().lower(),
                                      _DEFAULT_CPI_SCORE))


def risk_signal(spx_above_200ma: bool, vix: float) -> float:
    s = 50.0
    s += 25.0 if spx_above_200ma else -25.0
    if vix < 18:
        s += 25.0
    elif vix > 25:
        s -= 25.0
    return _clamp(s)


def liquidity_signal(ten_year_yield_trend: str, dxy_trend: str) -> float:
    s = 50.0
    y = (ten_year_yield_trend or "flat").strip().lower()
    d = (dxy_trend or "flat").strip().lower()
    if y == "falling":
        s += 25.0
    elif y == "rising":
        s -= 25.0
    if d == "falling":
        s += 25.0
    elif d == "rising":
        s -= 25.0
    return _clamp(s)


def score_macro(inputs: MacroInputs) -> ComponentScore:
    fed = fed_rate_signal(inputs.fed_stance)
    infl = inflation_signal(inputs.cpi_trend)
    risk = risk_signal(inputs.spx_above_200ma, inputs.vix)
    liq = liquidity_signal(inputs.ten_year_yield_trend, inputs.dxy_trend)

    signals = [
        SubSignal(name="fed_rate_signal", value=fed, weight=0.35,
                  detail=f"stance '{inputs.fed_stance}' -> {fed:g}"),
        SubSignal(name="inflation_signal", value=infl, weight=0.25,
                  detail=f"cpi '{inputs.cpi_trend}' -> {infl:g}"),
        SubSignal(name="risk_signal", value=risk, weight=0.25,
                  detail=f"spx_above_200ma={inputs.spx_above_200ma}, vix={inputs.vix:g} -> {risk:g}"),
        SubSignal(name="liquidity_signal", value=liq, weight=0.15,
                  detail=f"10y '{inputs.ten_year_yield_trend}', dxy '{inputs.dxy_trend}' -> {liq:g}"),
    ]
    score = _round(sum(s.value * s.weight for s in signals))
    expl = (f"fed {fed:g}×.35 + inflation {infl:g}×.25 + "
            f"risk {risk:g}×.25 + liquidity {liq:g}×.15 = {score:g}")
    return ComponentScore(score=score, signals=signals, explanation=expl)


# ─── 4. Price / Volume Confirmation Score ─────────────────────────────────────

def relative_volume_score(relative_volume: Optional[float]) -> float:
    """Session volume vs trailing average -> 0-100. No data -> neutral 50."""
    if relative_volume is None:
        return 50.0
    r = relative_volume
    if r > 3:
        return 100.0
    if r > 2:
        return 85.0
    if r > 1.5:
        return 70.0
    if r >= 1:
        return 55.0
    if r > 0:
        return 35.0
    return 50.0


def price_action_score(gap_pct: float, trend_confirms: Optional[bool]) -> float:
    """
    Does price action confirm the idea's direction? trend_confirms is the
    bias-aligned read (the caller signs gap_pct toward the bias). No read -> 50.
    """
    if trend_confirms is None:
        return 50.0
    if not trend_confirms:
        return 20.0           # price is moving against the thesis
    g = abs(gap_pct or 0.0)
    if g >= 3:
        return 90.0
    if g >= 1:
        return 75.0
    return 60.0


def score_price_volume(inputs: PriceVolumeInputs) -> ComponentScore:
    vol = relative_volume_score(inputs.relative_volume)
    price = price_action_score(inputs.gap_pct, inputs.trend_confirms)
    signals = [
        SubSignal(name="relative_volume", value=vol, weight=0.60,
                  detail=(f"rel vol {inputs.relative_volume}x -> {vol:g}"
                          if inputs.relative_volume is not None else "no volume data -> 50")),
        SubSignal(name="price_action", value=price, weight=0.40,
                  detail=(f"trend_confirms={inputs.trend_confirms}, gap {inputs.gap_pct:+g}% -> {price:g}")),
    ]
    score = _round(sum(s.value * s.weight for s in signals))
    expl = f"rel_vol {vol:g}×.60 + price {price:g}×.40 = {score:g}"
    return ComponentScore(score=score, signals=signals, explanation=expl)


# ─── 5. Composite Alpha Score ─────────────────────────────────────────────────

# New composite weights (sum to 1.0). See AlphaScore docstring for rationale.
WEIGHTS: dict[str, float] = {
    "catalyst": 0.35,
    "price_volume": 0.20,
    "narrative": 0.15,
    "options": 0.15,
    "institutional": 0.10,
    "macro": 0.05,
}

# Confirmation thresholds for the hard gate (the CRITICAL RULE).
CATALYST_CONFIRM_MIN = 40.0       # below this, the catalyst is too weak to act on
PRICE_VOLUME_CONFIRM_MIN = 55.0   # price/volume must actively confirm the move
WATCHLIST_CEILING = 69.9          # capped just under the 'tradeable' threshold (70)


def tier_for(composite_score: float) -> str:
    if composite_score >= 80:
        return "high_conviction"
    if composite_score >= 70:
        return "tradeable"
    if composite_score >= 60:
        return "watchlist"
    return "ignore"


def composite(catalyst: ComponentScore,
              narrative: ComponentScore,
              macro: ComponentScore,
              price_volume: Optional[ComponentScore] = None,
              options: Optional[ComponentScore] = None,
              institutional: Optional[ComponentScore] = None) -> AlphaScore:
    """
    Weighted blend of the present components with the CRITICAL-RULE hard gate.

    Confirmation requires a real catalyst AND price/volume confirmation. When the
    idea is NOT confirmed, the options-flow and institutional modifiers are
    EXCLUDED from the blend (so they can never lift a weak idea) and the score is
    capped at the watchlist ceiling. Components with no data are dropped and the
    remaining weights renormalized, so absence is neutral rather than a penalty.
    """
    floors_applied: list[str] = []

    confirmed = (
        catalyst.score >= CATALYST_CONFIRM_MIN
        and price_volume is not None
        and price_volume.score >= PRICE_VOLUME_CONFIRM_MIN
    )

    # Assemble the components that participate in the weighted average.
    parts: list[tuple[str, ComponentScore]] = [
        ("catalyst", catalyst),
        ("narrative", narrative),
        ("macro", macro),
    ]
    if price_volume is not None:
        parts.append(("price_volume", price_volume))

    gate_applied = False
    if confirmed:
        if options is not None:
            parts.append(("options", options))
        if institutional is not None:
            parts.append(("institutional", institutional))
    else:
        # Hard gate: modifiers may not contribute to an unconfirmed idea.
        if options is not None or institutional is not None:
            gate_applied = True
            floors_applied.append("confirmation_gate")

    # Renormalize the weights of the present components and blend.
    total_w = sum(WEIGHTS[name] for name, _ in parts)
    base = sum(WEIGHTS[name] * cs.score for name, cs in parts) / total_w

    result = base
    if gate_applied:
        result = min(result, WATCHLIST_CEILING)

    # Framework floors (composed via min).
    if macro.score < 30:
        result = min(result, 50.0)
        floors_applied.append("macro_floor")
    if catalyst.score < 40:
        result = min(result, 45.0)
        floors_applied.append("catalyst_floor")

    composite_score = _round(_clamp(result))

    blend = " + ".join(f"{name} {cs.score:g}×{WEIGHTS[name]:g}" for name, cs in parts)
    expl = f"base = ({blend}) / {total_w:g} = {_round(base):g}"
    if floors_applied:
        expl += f"; {floors_applied} -> {composite_score:g}"

    return AlphaScore(
        catalyst_score=catalyst.score,
        price_volume_score=price_volume.score if price_volume is not None else None,
        narrative_score=narrative.score,
        options_score=options.score if (confirmed and options is not None) else None,
        institutional_score=institutional.score if (confirmed and institutional is not None) else None,
        macro_score=macro.score,
        composite_score=composite_score,
        tier=tier_for(composite_score),
        catalyst=catalyst,
        price_volume=price_volume,
        narrative=narrative,
        options=options if confirmed else None,
        institutional=institutional if confirmed else None,
        macro=macro,
        confirmed=confirmed,
        gate_applied=gate_applied,
        composite_explanation=expl,
        floors_applied=floors_applied,
    )


def score_idea(catalyst_inputs: CatalystInputs,
               narrative_inputs: NarrativeInputs,
               macro_inputs: MacroInputs,
               price_volume_inputs: Optional[PriceVolumeInputs] = None,
               options: Optional[ComponentScore] = None,
               institutional: Optional[ComponentScore] = None) -> AlphaScore:
    """Convenience: run the always-present components and combine with any modifiers."""
    return composite(
        catalyst=score_catalyst(catalyst_inputs),
        narrative=score_narrative(narrative_inputs),
        macro=score_macro(macro_inputs),
        price_volume=score_price_volume(price_volume_inputs) if price_volume_inputs is not None else None,
        options=options,
        institutional=institutional,
    )


# ─── Adapters from existing platform objects ──────────────────────────────────

# Map the scanner's keyword categories to catalyst-type keys above.
_CATEGORY_TO_TYPE: dict[str, str] = {
    "m&a": "m&a",
    "fda": "fda",
    "deal": "contract",
    "earnings": "earnings",
    "financing": "financing",
    "ai": "partnership_named",
    "structure": "product_launch",
    "general": "generic_pr",
}


def catalyst_type_from_categories(categories: list[str]) -> str:
    """Pick the highest-weighted catalyst type among matched categories."""
    best_type = "generic_pr"
    best_w = -1.0
    for c in categories or []:
        t = _CATEGORY_TO_TYPE.get((c or "").strip().lower(), "generic_pr")
        w = catalyst_type_weight(t)
        if w > best_w:
            best_w, best_type = w, t
    return best_type


def catalyst_inputs_from_alert(alert, prior_count_30d: int = 0) -> CatalystInputs:
    """
    Build CatalystInputs from a CatalystAlert. Materiality uses cheap flags the
    scanner already computes (low float = more materially explosive). Kept simple
    and deterministic.
    """
    catalyst_type = catalyst_type_from_categories(getattr(alert, "categories", []) or [])
    gap = getattr(alert, "change_pct", 0.0) or 0.0

    materiality = 50.0
    if getattr(alert, "is_low_float", False):
        materiality = 80.0
    vol_spike = getattr(alert, "volume_spike", None)
    if vol_spike and vol_spike >= 3:
        materiality = max(materiality, 80.0)

    return CatalystInputs(
        catalyst_type=catalyst_type,
        gap_pct=gap,
        prior_count_30d=prior_count_30d,
        materiality=materiality,
    )


# Map AlphaLab Catalyst Radar keyword matches (see catalysts.CATALYST_KEYWORDS)
# to catalyst-type keys above. Direction/bearishness is handled separately by the
# radar's bias; this only captures catalyst *type strength*. Keywords that aren't
# a clean catalyst type (ai mentions, investigations, delistings) fall through to
# generic_pr — the AI *theme* strength is already captured by the narrative score.
_KEYWORD_TO_TYPE: dict[str, str] = {
    "fda approval": "fda",
    "phase 3": "fda",
    "raises guidance": "guidance_raise",
    "cuts guidance": "guidance_raise",
    "beat": "earnings_beat",
    "contract": "contract",
    "agreement": "contract",
    "partnership": "partnership",
    "offering": "financing",
    "registered direct": "financing",
    "shelf registration": "financing",
}


def catalyst_type_from_keywords(keywords: list[str]) -> str:
    """Pick the highest-weighted catalyst type among matched radar keywords."""
    best_type = "generic_pr"
    best_w = -1.0
    for kw in keywords or []:
        t = _KEYWORD_TO_TYPE.get((kw or "").strip().lower(), "generic_pr")
        w = catalyst_type_weight(t)
        if w > best_w:
            best_w, best_type = w, t
    return best_type


def catalyst_inputs_from_radar_row(row: dict, prior_count_30d: int = 0) -> CatalystInputs:
    """
    Build CatalystInputs from a scored Catalyst Radar row (a dict produced by
    alpha_lab.catalysts.score_catalyst). The radar has no price gap, so surprise
    is left neutral; the radar's 0-10 actionability_score becomes the 0-100
    materiality proxy.
    """
    matches = row.get("matched_keywords") or []
    keywords = [str(m.get("keyword", "")) for m in matches]
    catalyst_type = catalyst_type_from_keywords(keywords)
    actionability = float(row.get("actionability_score", 0.0) or 0.0)
    materiality = _clamp(actionability * 10.0)
    return CatalystInputs(
        catalyst_type=catalyst_type,
        gap_pct=0.0,
        prior_count_30d=prior_count_30d,
        materiality=materiality,
    )


def catalyst_inputs_from_idea(idea: dict, prior_count_30d: int = 0) -> CatalystInputs:
    """
    Build CatalystInputs from a stored AlphaLab idea dict by keyword-scanning its
    catalyst/thesis/theme text. Used at the decision layer where the original
    radar row is no longer attached.
    """
    text = " ".join(str(idea.get(k, "")) for k in ("catalyst", "thesis", "theme")).lower()
    keywords = [kw for kw in _KEYWORD_TO_TYPE if kw in text]
    catalyst_type = catalyst_type_from_keywords(keywords)
    return CatalystInputs(
        catalyst_type=catalyst_type,
        gap_pct=0.0,
        prior_count_30d=prior_count_30d,
        materiality=50.0,
    )


def narrative_inputs_for_ticker(ticker: Optional[str],
                                theme_etf_return_4w_pct: Optional[float] = None
                                ) -> NarrativeInputs:
    """Look up theme + current phase for a ticker from the static config."""
    t = (ticker or "").strip().upper()
    theme = TICKER_THEME.get(t, "none")
    phase = THEME_PHASE.get(theme, "expansion")
    return NarrativeInputs(
        theme=theme,
        phase=phase,
        theme_etf_return_4w_pct=theme_etf_return_4w_pct,
    )


def macro_inputs_from_briefing(briefing) -> MacroInputs:
    """
    Derive MacroInputs from the MarketBriefing we already produce each cycle.

    MVP proxy (documented): the briefing exposes 0-10 macro_risk_score and
    liquidity_score but not raw Fed/CPI prints, so:
      - risk_signal is driven by macro_risk_score (low risk => risk-on)
      - liquidity_signal is driven by liquidity_score (abundant => easing)
      - Fed stance and CPI default to neutral (no data in the briefing yet)
    When a daily FRED-backed macro snapshot is wired in, replace this adapter
    with the real readings; the engine itself does not change.
    """
    macro_risk = float(getattr(briefing, "macro_risk_score", 5.0) or 5.0)
    liquidity = float(getattr(briefing, "liquidity_score", 5.0) or 5.0)

    # macro_risk_score: 0=low risk (risk-on), 10=high risk (risk-off)
    spx_above_200ma = macro_risk < 5.0
    # Map risk score to a VIX-like proxy: low risk -> low vix.
    vix_proxy = 12.0 + macro_risk * 2.0          # 0->12, 10->32

    # liquidity_score: 0=tight, 10=abundant. Abundant => falling yields/dollar.
    if liquidity >= 6.5:
        yield_trend = dxy_trend = "falling"
    elif liquidity <= 3.5:
        yield_trend = dxy_trend = "rising"
    else:
        yield_trend = dxy_trend = "flat"

    return MacroInputs(
        fed_stance="neutral_hold",
        cpi_trend="flat",
        spx_above_200ma=spx_above_200ma,
        vix=vix_proxy,
        ten_year_yield_trend=yield_trend,
        dxy_trend=dxy_trend,
    )
