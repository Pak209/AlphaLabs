"""
tests/test_scoring.py — unit tests for the MVP Analyst Brain scoring engine.

The engine is a pure, deterministic function of its inputs, so every test feeds a
fixed input and asserts the exact expected number. No mocks or network required.
Reference: docs/analyst-brain-mvp-engine.md
"""
from alpha_lab.scoring_models import (
    CatalystInputs, NarrativeInputs, MacroInputs, AlphaScore,
)
from alpha_lab import scoring_engine as se


# ─── Catalyst sub-signals ─────────────────────────────────────────────────────

def test_catalyst_type_weight_lookup():
    assert se.catalyst_type_weight("m&a") == 95
    assert se.catalyst_type_weight("fda") == 90
    assert se.catalyst_type_weight("financing") == 35
    # unknown type falls back to generic
    assert se.catalyst_type_weight("nonsense") == 15
    assert se.catalyst_type_weight("M&A") == 95  # case-insensitive


def test_novelty_score_tiers():
    assert se.novelty_score(0) == 100
    assert se.novelty_score(1) == 50
    assert se.novelty_score(2) == 20
    assert se.novelty_score(9) == 20


def test_surprise_score_buckets():
    assert se.surprise_score(10) == 100
    assert se.surprise_score(8) == 100
    assert se.surprise_score(6) == 80
    assert se.surprise_score(4) == 60
    assert se.surprise_score(2) == 40
    assert se.surprise_score(0.5) == 20
    assert se.surprise_score(-9) == 100   # uses absolute value


def test_score_catalyst_exact():
    # type m&a=95, gap 6%->80, 0 prior->100, materiality 50
    # 95*.4 + 80*.25 + 100*.2 + 50*.15 = 38 + 20 + 20 + 7.5 = 85.5
    inp = CatalystInputs(catalyst_type="m&a", gap_pct=6.0,
                         prior_count_30d=0, materiality=50)
    cs = se.score_catalyst(inp)
    assert cs.score == 85.5
    assert len(cs.signals) == 4
    assert "85.5" in cs.explanation


# ─── Narrative sub-signals ────────────────────────────────────────────────────

def test_flow_direction_buckets():
    assert se.flow_direction_score(None) == 50
    assert se.flow_direction_score(10) == 100
    assert se.flow_direction_score(3) == 75
    assert se.flow_direction_score(0) == 50
    assert se.flow_direction_score(-3) == 25
    assert se.flow_direction_score(-9) == 0


def test_score_narrative_exact():
    # ai theme=100, expansion phase=85, flow None->50
    # 100*.5 + 85*.3 + 50*.2 = 50 + 25.5 + 10 = 85.5
    inp = NarrativeInputs(theme="ai", phase="expansion")
    ns = se.score_narrative(inp)
    assert ns.score == 85.5


def test_score_narrative_no_theme_is_low():
    inp = NarrativeInputs(theme="none", phase="fading")
    ns = se.score_narrative(inp)
    # 20*.5 + 20*.3 + 50*.2 = 10 + 6 + 10 = 26
    assert ns.score == 26.0


# ─── Macro sub-signals ────────────────────────────────────────────────────────

def test_risk_signal_clamps_and_responds():
    # risk-on: above 200ma + low vix => 50 + 25 + 25 = 100
    assert se.risk_signal(True, 15) == 100
    # risk-off: below 200ma + high vix => 50 - 25 - 25 = 0
    assert se.risk_signal(False, 30) == 0
    # neutral vix band
    assert se.risk_signal(True, 20) == 75


def test_liquidity_signal():
    assert se.liquidity_signal("falling", "falling") == 100
    assert se.liquidity_signal("rising", "rising") == 0
    assert se.liquidity_signal("flat", "flat") == 50


def test_score_macro_exact():
    # fed neutral_hold=60, cpi flat=60, risk(True,20)=75, liq(flat,flat)=50
    # 60*.35 + 60*.25 + 75*.25 + 50*.15 = 21 + 15 + 18.75 + 7.5 = 62.25 -> 62.2 (banker's? no, round half)
    inp = MacroInputs(fed_stance="neutral_hold", cpi_trend="flat",
                      spx_above_200ma=True, vix=20.0,
                      ten_year_yield_trend="flat", dxy_trend="flat")
    ms = se.score_macro(inp)
    assert ms.score == round(62.25, 1)


# ─── Composite + floors + tiers ───────────────────────────────────────────────

def test_composite_no_floor():
    cat = se.score_catalyst(CatalystInputs(catalyst_type="m&a", gap_pct=6.0))
    nar = se.score_narrative(NarrativeInputs(theme="ai", phase="expansion"))
    mac = se.score_macro(MacroInputs(spx_above_200ma=True, vix=15,
                                     ten_year_yield_trend="falling",
                                     dxy_trend="falling"))
    alpha = se.composite(cat, nar, mac)
    assert isinstance(alpha, AlphaScore)
    assert alpha.floors_applied == []
    # recompute base by hand from component scores. With no price/volume,
    # options, or institutional data, only catalyst/narrative/macro are present,
    # so their weights (0.35/0.15/0.05) renormalize over their sum (0.55).
    total_w = 0.35 + 0.15 + 0.05
    expected = round((0.35 * cat.score + 0.15 * nar.score + 0.05 * mac.score) / total_w, 1)
    assert alpha.composite_score == expected


def test_catalyst_floor_caps_score():
    # generic_pr catalyst with no move => catalyst score < 40 -> cap at 45
    cat = se.score_catalyst(CatalystInputs(catalyst_type="generic_pr", gap_pct=0.0))
    assert cat.score < 40
    nar = se.score_narrative(NarrativeInputs(theme="ai", phase="expansion"))
    mac = se.score_macro(MacroInputs(spx_above_200ma=True, vix=15))
    alpha = se.composite(cat, nar, mac)
    assert "catalyst_floor" in alpha.floors_applied
    assert alpha.composite_score <= 45.0


def test_macro_floor_caps_score():
    cat = se.score_catalyst(CatalystInputs(catalyst_type="m&a", gap_pct=9.0))
    nar = se.score_narrative(NarrativeInputs(theme="ai", phase="expansion"))
    # hostile macro: hiking, rising inflation, risk-off => macro < 30
    mac = se.score_macro(MacroInputs(fed_stance="hiking", cpi_trend="rising2",
                                     spx_above_200ma=False, vix=30,
                                     ten_year_yield_trend="rising",
                                     dxy_trend="rising"))
    assert mac.score < 30
    alpha = se.composite(cat, nar, mac)
    assert "macro_floor" in alpha.floors_applied
    assert alpha.composite_score <= 50.0


def test_tier_thresholds():
    assert se.tier_for(80) == "high_conviction"
    assert se.tier_for(79.9) == "tradeable"
    assert se.tier_for(70) == "tradeable"
    assert se.tier_for(69.9) == "watchlist"
    assert se.tier_for(60) == "watchlist"
    assert se.tier_for(59.9) == "ignore"


def test_determinism():
    """Same inputs must always produce identical output."""
    ci = CatalystInputs(catalyst_type="contract", gap_pct=4.2, prior_count_30d=1)
    ni = NarrativeInputs(theme="semiconductors", phase="peak",
                         theme_etf_return_4w_pct=2.0)
    mi = MacroInputs(fed_stance="cutting", cpi_trend="falling1")
    a = se.score_idea(ci, ni, mi)
    b = se.score_idea(ci, ni, mi)
    assert a.model_dump() == b.model_dump()


# ─── Adapters ─────────────────────────────────────────────────────────────────

def test_narrative_inputs_for_known_ticker():
    inp = se.narrative_inputs_for_ticker("NVDA")
    assert inp.theme == "ai"
    inp2 = se.narrative_inputs_for_ticker("ZZZZ")
    assert inp2.theme == "none"


def test_catalyst_inputs_from_alert_like_object():
    class _Alert:
        categories = ["m&a", "deal"]
        change_pct = 7.5
        is_low_float = True
        volume_spike = 5.0
    ci = se.catalyst_inputs_from_alert(_Alert(), prior_count_30d=0)
    # m&a outranks deal/contract
    assert ci.catalyst_type == "m&a"
    assert ci.gap_pct == 7.5
    assert ci.materiality == 80.0   # low float bumps materiality


def test_macro_inputs_from_briefing_like_object():
    class _Briefing:
        macro_risk_score = 2.0     # low risk -> risk-on
        liquidity_score = 8.0      # abundant -> easing
    mi = se.macro_inputs_from_briefing(_Briefing())
    assert mi.spx_above_200ma is True
    assert mi.ten_year_yield_trend == "falling"
    ms = se.score_macro(mi)
    assert ms.score > 60   # supportive macro


# ─── AlphaLab-specific adapters ───────────────────────────────────────────────

def test_catalyst_type_from_keywords_picks_strongest():
    # contract (85) outranks partnership (30)
    assert se.catalyst_type_from_keywords(["partnership", "contract"]) == "contract"
    assert se.catalyst_type_from_keywords(["fda approval"]) == "fda"
    assert se.catalyst_type_from_keywords(["nothing here"]) == "generic_pr"


def test_catalyst_inputs_from_radar_row():
    row = {
        "ticker": "NVDA",
        "matched_keywords": [{"keyword": "contract"}, {"keyword": "partnership"}],
        "actionability_score": 7.0,   # -> materiality 70
    }
    ci = se.catalyst_inputs_from_radar_row(row)
    assert ci.catalyst_type == "contract"
    assert ci.materiality == 70.0
    assert ci.gap_pct == 0.0


def test_catalyst_inputs_from_idea_keyword_scan():
    idea = {"catalyst": "Company announces a major FDA approval", "thesis": "", "theme": ""}
    ci = se.catalyst_inputs_from_idea(idea)
    assert ci.catalyst_type == "fda"
    # no catalyst keywords -> generic
    assert se.catalyst_inputs_from_idea({"thesis": "broad market chatter"}).catalyst_type == "generic_pr"
