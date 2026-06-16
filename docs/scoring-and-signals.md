# Scoring & Signal Sources

How AlphaLab turns a raw idea into an alpha score, and why options/dark-pool data
can only ever *raise conviction* — never trigger a trade on their own.

This is reference documentation. Trading behavior is **not** changed by reading or
editing this file. Code lives in `alpha_lab/scoring_engine.py`,
`alpha_lab/options_flow.py`, and `alpha_lab/dark_pool.py`.

---

## 1. The composite formula (35 / 20 / 15 / 15 / 10 / 5)

The composite alpha score is a weighted blend of six 0–100 component scores:

| Weight | Component | What it measures |
| ------ | --------- | ---------------- |
| **35%** | Catalyst | The event/news driving the idea (M&A, earnings, filings, contracts). The anchor of every idea. |
| **20%** | Price / Volume Confirmation | Is price/volume actually confirming the thesis? (relative volume, gap, trend). |
| **15%** | Narrative | Theme/sector alignment (AI, semis, rotations). Adds conviction; can't trade alone. |
| **15%** | Options Flow | Unusual options activity — **conviction modifier only** (see §3). |
| **10%** | Institutional / Dark Pool | TRF prints, blocks, accumulation — **conviction modifier only** (see §3). |
| **5%** | Macro | Regime backdrop (SPX vs 200MA, VIX, yields, DXY). |

Weights are defined in `WEIGHTS` (`scoring_engine.py`) and sum to 1.0 (guarded by a
test). The blend is **renormalized over present components** — see §4.

---

## 2. What "hard-gated" means

A trade idea **cannot** be lifted into a tradeable tier by options or dark-pool
activity unless it is first *confirmed*. Confirmation requires **both**:

- **Catalyst score ≥ 40** (`CATALYST_CONFIRM_MIN`) — the catalyst is strong enough to act on, **and**
- **Price/Volume score ≥ 55** (`PRICE_VOLUME_CONFIRM_MIN`) — price/volume is actively confirming.

If an idea is **not confirmed** but options/institutional data are present, the
**hard gate** fires:

1. The options and institutional components are **excluded** from the weighted blend.
2. `gate_applied = True` and `"confirmation_gate"` is added to `floors_applied`.
3. The composite is **capped at `WATCHLIST_CEILING` (69.9)** — just under the
   `tradeable` threshold of 70. So the idea can never read higher than *watchlist*.

This is the CRITICAL RULE enforced in `composite()`. The valid flow is:

```
Catalyst → Price/Volume Confirmation → Options / Dark Pool Confirmation → Risk Engine → Paper Trade
```

> Note: an idea with **no** options/institutional data at all is *not* gated —
> there is nothing to gate. A catalyst-driven idea still scores on its own merits.

### Price/Volume confirmation is now a live feed

As of 2026-06-14 the price/volume component is fed by a **real intraday snapshot**
(`live_sources.fetch_polygon_intraday`, gated on `POLYGON_API_KEY`) rather than
always returning empty. Previously every idea scored a flat 50 here — below the 55
gate — so price/volume *never* confirmed and the gate could not be cleared. Now
`_price_volume_inputs` (in `service.py`) maps the snapshot to `PriceVolumeInputs`:

- **`gap_pct`** = the day's % change; a **0.25% deadband** ignores noise.
- **`trend_confirms`** = whether the move agrees with the idea's bias (gap > 0 for
  bullish, < 0 for bearish).
- **`relative_volume`** (day vol ÷ prev-day vol) is only counted **when
  `trend_confirms is True`**. Volume backing a move *against* the thesis stays
  neutral — it must not be allowed to clear the gate (a 5× contrary move once
  scored 68 and wrongly confirmed; this is the fix).

Non-equity/option ideas (e.g. crypto) and any feed miss fall back to the prior
empty/neutral inputs, so behavior is unchanged when the key is unset.

---

## 3. Why options & dark-pool data are conviction modifiers only

Unusual options volume or a large dark-pool print is **not** a reason to trade by
itself — it has no direction guarantee and is easily noise. AlphaLab treats both as
*modifiers* that can only add conviction to an idea that already has a real catalyst
and price/volume confirmation:

- **Options Flow** (`options_flow.py`) scores a point system (call-volume multiples,
  C/P ratio, OI changes, large premium). Large put buying pulls the score **down**.
  The points map to a 0–100 component score.
- **Institutional / Dark Pool** (`dark_pool.py`) scores escalating tiers: a single
  >$1M print = +1, repeated prints = +3, multi-day accumulation = +5. A print is
  **not assumed bullish** — bias stays neutral unless an explicit buy/sell direction
  is present at the top tier.

Both only contribute to the composite when the idea is confirmed (§2). When gated,
their scores are still **logged and displayed** for audit — you can see the system
saw a strong options signal and *chose to exclude it* — but they don't move the score.

---

## 4. How no-data providers behave

Providers implement a `fetch(ticker) -> Optional[Inputs]` protocol. Today both
signal-source providers are **stubs** that return `None` ("no data"):
`StubOptionsFlowProvider` and `StubDarkPoolProvider` (defaults in `service.py`).

No-data is **neutral**, never a penalty:

- A no-data component produces a signal with `has_data = False` and is **dropped**
  from the weighted blend. The remaining weights are **renormalized** over the
  present components, so absence neither helps nor hurts the score.
- In the dashboard breakdown panel, a no-data modifier shows a **"no provider data"**
  indicator instead of a fabricated number.

Plugging in a real feed is a drop-in: inject a provider whose `fetch()` returns real
`Inputs`, and the modifier activates with **zero other code changes**.

---

## 5. Which APIs are real vs stubbed

Verified against the code (`live_sources.py`, `market_data.py`, `analyst.py`,
`options_flow.py`, `dark_pool.py`). "Real" sources are gated on an env key and fall
back to sample data when the key is absent.

### Real / live-capable (env-key gated)

| Source | Env key | Used for |
| ------ | ------- | -------- |
| SEC EDGAR | `SEC_USER_AGENT` | Filing catalysts |
| Polygon | `POLYGON_API_KEY` | Market data + news catalysts + intraday price/volume confirmation |
| Benzinga | `BENZINGA_API_KEY` | News catalysts |
| Tiingo | `TIINGO_API_KEY` | News catalysts |
| Newsfilter | `NEWSFILTER_API_KEY` | News catalysts |
| Alpaca | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Paper broker, account, quotes |
| Anthropic | `ANTHROPIC_API_KEY` | LLM analyst layer |

When a key is missing the catalyst radar reports `sample_fallback` / provider
`disabled` rather than failing.

### Stubbed (no real feed wired yet)

| Provider | Stub | Behavior |
| -------- | ---- | -------- |
| Options Flow | `StubOptionsFlowProvider` | Returns `None` → no-data → neutral |
| Dark Pool / TRF | `StubDarkPoolProvider` | Returns `None` → no-data → neutral |

A real options/TRF feed (e.g. an unusual-options or TRF data vendor) has **not**
been selected or wired. Until one is, the two modifiers are always no-data and the
composite is driven by catalyst, price/volume, narrative, and macro.
