"""
tests/test_signal_sources.py — Options Flow + Dark Pool agents, the price/volume
confirmation component, and the CRITICAL-RULE hard gate in the composite.

The agents and engine are pure deterministic functions, so every test feeds fixed
inputs and asserts exact behavior. No network or mocks.
"""
from alpha_lab import scoring_engine as se
from alpha_lab.scoring_models import (
    CatalystInputs, NarrativeInputs, MacroInputs, PriceVolumeInputs,
)
from alpha_lab.options_flow import (
    OptionsFlowInputs, OptionsFlowProvider, PolygonOptionsFlowProvider,
    StubOptionsFlowProvider, score_options_flow,
    component_from_signal as options_component,
)
from alpha_lab.dark_pool import (
    DarkPoolInputs, StubDarkPoolProvider, score_institutional,
    component_from_signal as institutional_component,
)


# ─── Options Flow agent ───────────────────────────────────────────────────────

def test_options_flow_point_system_bullish():
    # call vol 6x (>5 -> +4), C/P = 100k/20k = 5 (>4 -> +4), OI rising + call vol
    # rising together (+4) = +12 points.
    inp = OptionsFlowInputs(ticker="nvda", call_volume=120_000, put_volume=24_000,
                            avg_call_volume=20_000, open_interest=60_000,
                            prior_open_interest=50_000)
    sig = score_options_flow(inp)
    assert sig.options_score == 12
    assert sig.bias == "bullish"
    assert sig.has_data is True
    assert sig.call_put_ratio == 5.0
    assert sig.open_interest_change == 10_000
    assert sig.summary == "Bullish options activity detected"
    assert sig.component_score > 50          # bullish lifts the component


def test_options_flow_call_volume_buckets():
    base = dict(ticker="X", put_volume=1000, avg_call_volume=1000,
                open_interest=10, prior_open_interest=10)  # OI flat, low C/P
    # 4x normal -> +2 (call vol), C/P 4 -> +2 -> total 4
    assert score_options_flow(OptionsFlowInputs(call_volume=4000, **base)).options_score == 4
    # 11x normal -> +6 (call vol), C/P 11 (>4) -> +4 -> total 10
    assert score_options_flow(OptionsFlowInputs(call_volume=11000, **base)).options_score == 10


def test_options_flow_large_put_buying_is_bearish():
    # No bullish signals; dominant aggressive put premium -> bearish adjustment.
    inp = OptionsFlowInputs(ticker="X", call_volume=1000, put_volume=1000,
                            avg_call_volume=1000, open_interest=10, prior_open_interest=10,
                            put_buy_premium_usd=5_000_000, call_buy_premium_usd=1_000_000)
    sig = score_options_flow(inp)
    assert sig.options_score < 0
    assert sig.bias == "bearish"
    assert sig.component_score < 50
    assert "put buying" in sig.summary.lower()


def test_options_flow_no_data_is_neutral():
    sig = score_options_flow(None, ticker="nvda")
    assert sig.has_data is False
    assert sig.ticker == "NVDA"
    assert sig.component_score == 50.0
    assert options_component(sig) is None       # excluded from the composite


def test_stub_options_provider_returns_none():
    assert StubOptionsFlowProvider().fetch("NVDA") is None


# ─── Live Polygon options provider (HTTP mocked, no network) ───────────────────

def _day_bar(ts_ms, volume):
    return {"t": ts_ms, "v": volume, "o": 1, "c": 1, "h": 1, "l": 1}


class _FakeOptionsProvider(PolygonOptionsFlowProvider):
    """PolygonOptionsFlowProvider with the single HTTP method stubbed by canned
    responses, so the chain-aggregation logic is exercised without a network."""
    def __init__(self, responses, **kw):
        super().__init__(api_key="test", session_date="2025-06-11", **kw)
        self._responses = responses
        self.calls: list[str] = []

    def _get(self, path, params):  # noqa: ARG002
        self.calls.append(path)
        for needle, payload in self._responses.items():
            if needle in path:
                return payload
        return None


def test_polygon_options_provider_implements_protocol():
    assert isinstance(PolygonOptionsFlowProvider(api_key="x"), OptionsFlowProvider)


def test_polygon_options_aggregates_chain_volume():
    # session 2025-06-11 stamped at UTC midnight; an earlier bar is the baseline.
    session_ms = 1749600000000   # 2025-06-11T00:00:00Z
    prior_ms = 1749513600000     # 2025-06-10T00:00:00Z
    responses = {
        "/v2/aggs/ticker/SPY/prev": {"results": [{"c": 600.0}]},
        # two calls, two puts near the money
        "reference/options/contracts": None,  # overridden per type below
    }

    # Distinct payloads per contract_type + per contract require a smarter stub:
    class P(_FakeOptionsProvider):
        def _get(self, path, params):
            self.calls.append(path)
            if "/ticker/SPY/range/" in path:        # underlying session-date close
                return {"results": [{"c": 600.0}]}
            if "reference/options/contracts" in path:
                ct = params.get("contract_type")
                exp = "2025-06-13"
                if ct == "call":
                    return {"results": [
                        {"ticker": "O:SPY250613C00600000", "strike_price": 600, "expiration_date": exp},
                        {"ticker": "O:SPY250613C00605000", "strike_price": 605, "expiration_date": exp},
                    ]}
                return {"results": [
                    {"ticker": "O:SPY250613P00600000", "strike_price": 600, "expiration_date": exp},
                ]}
            if "C00600000" in path:
                return {"results": [_day_bar(prior_ms, 1000), _day_bar(session_ms, 9000)]}
            if "C00605000" in path:
                return {"results": [_day_bar(prior_ms, 500), _day_bar(session_ms, 3000)]}
            if "P00600000" in path:
                return {"results": [_day_bar(prior_ms, 2000), _day_bar(session_ms, 2000)]}
            return None

    prov = P(responses)
    inp = prov.fetch("spy")
    assert inp is not None
    assert inp.ticker == "SPY"
    assert inp.call_volume == 12000          # 9000 + 3000 session-day calls
    assert inp.put_volume == 2000            # 2000 session-day puts
    assert inp.avg_call_volume == 1500.0     # 1000 + 500 prior-day baseline
    # 12000/1500 = 8x normal call vol, C/P = 6 -> bullish flow
    sig = score_options_flow(inp)
    assert sig.bias == "bullish"
    assert inp.call_volume_multiple == 8.0


def test_polygon_options_no_key_returns_none():
    prov = PolygonOptionsFlowProvider(api_key="")
    assert prov.fetch("SPY") is None


def test_polygon_options_empty_chain_returns_none():
    prov = _FakeOptionsProvider({"/ticker/SPY/range/": {"results": [{"c": 600.0}]}})
    # spot resolves but no contract/agg responses -> empty chain -> graceful no-data
    assert prov.fetch("SPY") is None


# ─── Dark Pool / TRF agent ────────────────────────────────────────────────────

def test_institutional_tiers():
    # single $1M+ print only -> +1
    s1 = score_institutional(DarkPoolInputs(ticker="X", largest_print_usd=1_500_000,
                                            dark_pool_notional=1_500_000, block_count=1))
    assert s1.institutional_score == 1
    # repeated large prints -> +3
    s3 = score_institutional(DarkPoolInputs(ticker="X", repeated_large_prints=True,
                                            block_count=3, dark_pool_notional=8_000_000))
    assert s3.institutional_score == 3
    # multi-day accumulation -> +5 (strongest tier wins)
    s5 = score_institutional(DarkPoolInputs(ticker="X", multi_day_accumulation=True,
                                            accumulation_days=4, repeated_large_prints=True,
                                            block_count=5, dark_pool_notional=2e7))
    assert s5.institutional_score == 5
    assert s5.summary == "Institutional accumulation suspected"
    assert s5.component_score == 100.0


def test_institutional_not_assumed_bullish():
    # A strong print cluster with no directional read stays neutral in bias.
    sig = score_institutional(DarkPoolInputs(ticker="X", multi_day_accumulation=True,
                                             accumulation_days=3, dark_pool_notional=1e7))
    assert sig.bias == "neutral"
    # Only an explicit buy direction at the top tier expresses a bullish lean.
    sig_buy = score_institutional(DarkPoolInputs(ticker="X", multi_day_accumulation=True,
                                                 accumulation_days=3, direction="buy",
                                                 dark_pool_notional=1e7))
    assert sig_buy.bias == "bullish"


def test_institutional_no_data_is_neutral():
    sig = score_institutional(None, ticker="nvda")
    assert sig.has_data is False
    assert sig.component_score == 50.0
    assert institutional_component(sig) is None
    assert StubDarkPoolProvider().fetch("NVDA") is None


# ─── Price / Volume confirmation ──────────────────────────────────────────────

def test_relative_volume_buckets():
    assert se.relative_volume_score(None) == 50.0
    assert se.relative_volume_score(3.5) == 100.0
    assert se.relative_volume_score(2.5) == 85.0
    assert se.relative_volume_score(1.2) == 55.0
    assert se.relative_volume_score(0.5) == 35.0


def test_price_action_confirmation():
    assert se.price_action_score(0.0, None) == 50.0     # unknown -> neutral
    assert se.price_action_score(5.0, False) == 20.0    # moving against thesis
    assert se.price_action_score(5.0, True) == 90.0     # strong confirming move


def test_score_price_volume_confirms():
    pv = se.score_price_volume(PriceVolumeInputs(relative_volume=3.5, gap_pct=5.0,
                                                 trend_confirms=True))
    # 100*.6 + 90*.4 = 96
    assert pv.score == 96.0


# ─── Composite + hard gate (the CRITICAL RULE) ────────────────────────────────

def _strong_catalyst():
    return se.score_catalyst(CatalystInputs(catalyst_type="m&a", gap_pct=6.0))


def _ai_narrative():
    return se.score_narrative(NarrativeInputs(theme="ai", phase="expansion"))


def _neutral_macro():
    return se.score_macro(MacroInputs())


def _confirming_pv():
    return se.score_price_volume(PriceVolumeInputs(relative_volume=3.0, gap_pct=5.0,
                                                   trend_confirms=True))


def _bullish_options():
    return options_component(score_options_flow(
        OptionsFlowInputs(ticker="NVDA", call_volume=120_000, put_volume=20_000,
                          avg_call_volume=20_000, open_interest=60_000,
                          prior_open_interest=50_000)))


def _accumulation():
    return institutional_component(score_institutional(
        DarkPoolInputs(ticker="NVDA", multi_day_accumulation=True, accumulation_days=3,
                       direction="buy", dark_pool_notional=1e7)))


def test_confirmed_idea_uses_modifiers():
    alpha = se.composite(_strong_catalyst(), _ai_narrative(), _neutral_macro(),
                         price_volume=_confirming_pv(),
                         options=_bullish_options(), institutional=_accumulation())
    assert alpha.confirmed is True
    assert alpha.gate_applied is False
    assert alpha.options_score is not None       # modifiers counted
    assert alpha.institutional_score is not None
    assert alpha.tier in ("tradeable", "high_conviction")


def test_unusual_options_cannot_trigger_alone():
    """CRITICAL RULE: strong options + dark pool but weak catalyst / no confirmation
    must be gated — modifiers excluded and tier capped below 'tradeable'."""
    weak_catalyst = se.score_catalyst(CatalystInputs(catalyst_type="generic_pr", gap_pct=0.0))
    no_confirm = se.score_price_volume(PriceVolumeInputs(relative_volume=0.4, trend_confirms=False))
    alpha = se.composite(weak_catalyst, _ai_narrative(), _neutral_macro(),
                         price_volume=no_confirm,
                         options=_bullish_options(), institutional=_accumulation())
    assert alpha.confirmed is False
    assert alpha.gate_applied is True
    assert "confirmation_gate" in alpha.floors_applied
    assert alpha.options_score is None           # excluded — cannot lift the idea
    assert alpha.institutional_score is None
    assert alpha.tier in ("watchlist", "ignore")
    assert alpha.composite_score <= se.WATCHLIST_CEILING


def test_missing_confirmation_gates_even_with_strong_catalyst():
    # Strong catalyst but NO price/volume confirmation present + modifiers present
    # -> still gated (confirmation is required to activate the modifiers).
    alpha = se.composite(_strong_catalyst(), _ai_narrative(), _neutral_macro(),
                         price_volume=None,
                         options=_bullish_options(), institutional=_accumulation())
    assert alpha.confirmed is False
    assert alpha.gate_applied is True
    assert alpha.options_score is None
    assert alpha.composite_score <= se.WATCHLIST_CEILING


def test_catalyst_only_idea_not_gated():
    # No options/institutional signals at all -> nothing to gate; a catalyst-driven
    # idea still scores on its own merits (legacy behavior preserved).
    alpha = se.composite(_strong_catalyst(), _ai_narrative(), _neutral_macro(),
                         price_volume=_confirming_pv())
    assert alpha.gate_applied is False
    assert alpha.options_score is None
    assert alpha.institutional_score is None


def test_weights_sum_to_one():
    assert round(sum(se.WEIGHTS.values()), 6) == 1.0


def test_determinism_full_stack():
    args = (_strong_catalyst(), _ai_narrative(), _neutral_macro())
    kwargs = dict(price_volume=_confirming_pv(), options=_bullish_options(),
                  institutional=_accumulation())
    a = se.composite(*args, **kwargs)
    b = se.composite(*args, **kwargs)
    assert a.model_dump() == b.model_dump()
