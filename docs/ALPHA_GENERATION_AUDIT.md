# AlphaLabs alpha-generation audit

Written 2026-07-04, after the first optimization pass (scoring-input fixes +
rejection-waterfall telemetry) and alongside `docs/CALIBRATION_PLAN.md`.
Objective: improve **signal quality and trade selection** without touching any
risk control, paper safeguard, or approval workflow. Everything here is either
diagnostics-only or explicitly flagged as a behavior change requiring approval.

---

## 1. Current feature inventory

### Catalyst / news layer (`alpha_lab/catalysts.py`, `live_sources.py`)

| Feature | Basis | State |
|---|---|---|
| Keyword weights | ~35 static keywords, signed bullish/bearish | Live |
| Category | direct / sympathy / broad / low-actionability (× 1.0/0.55/0.35/0.2) | Live |
| Novelty (radar) | keyword count + category + "first/new/wins" words | Live, heuristic |
| Urgency | age buckets from `published_at` (1h/6h/24h/72h) | Live |
| Historical | **static** base rate by catalyst type | Live, never learned |
| Relevance / market impact / sector | ticker mention, keyword mass, theme words | Live |
| Source quality | static table (SEC 96 … manual 60) | Live |
| Confidence | unified: `0.40 + score·0.0045 + source_quality·0.00075` | Live (2026-07-04) |
| Sources | SEC EDGAR, Polygon news, Benzinga news + insider txns, Tiingo, Newsfilter | All optional/keyed; watchlist-limited |

### Alpha Score components (`scoring_engine.py`, weights 0.35/0.20/0.15/0.15/0.10/0.05)

| Component | Inputs | State |
|---|---|---|
| Catalyst | type weight (static 15–95), surprise (gap buckets), novelty (`prior_count_30d`), materiality (radar score) | **novelty input is dead — `prior_count_30d` is never queried, so every event scores "first in 30d"** |
| Price/volume | Polygon intraday gap + relative volume, 0.25% deadband, bias-aligned | Works only with `POLYGON_API_KEY`; neutral otherwise |
| Narrative | static ticker→theme map (~30 tickers), hand-set phase, theme-ETF 4w flow | **flow input never supplied → always neutral 50** |
| Options flow | C/P ratio, rel call volume, OI delta, aggressive premium | **Stub at decision time.** `PolygonOptionsFlowProvider` is fully implemented but only used by the read-only morning preview |
| Institutional | dark-pool notional, blocks, accumulation | Stub; no provider implemented |
| Macro | Fed stance, CPI, SPX>200MA, VIX, 10y/DXY | **Defaults at decision time**; `macro_inputs_from_briefing` adapter exists and is unused in `_score_idea` |

### Technical / other generators

- **Trending stocks** (`market_data.py`): EMA20/50, RSI14, 5-day change, dollar
  volume vs 5-day average, setup classification (pre-breakout / pullback /
  breakdown / extended), close-based support/resistance, quality→confidence.
- **Overnight Futures Pulse**: overnight futures aggregates → regime label +
  watchlist signals (confidence 0.55–0.85); nightly backtest fill into
  `futures_session_snapshots` / `catalyst_futures_reactions`.
- **Crypto**: CoinGecko EMA/RSI/support/resistance for BTC ideas.

### Outcome / label data (already accumulating)

- `signal_evaluations`: alert price, forward move, early-detection score, grades
  — **including rejected ideas** (the regret-analysis denominator).
- `training_rows` view: idea features + entry conviction (alpha components,
  option greeks, spread) + realized P/L per trade.
- `catalyst_futures_reactions`: catalyst timestamp → subsequent futures move.
- Rejection waterfall telemetry: per-gate observed values + thresholds.

## 2. Data-quality issues suppressing signal quality

1. **Dead novelty input** — recycled news scores like fresh news. The
   `catalyst_events` table already holds everything needed to compute
   `prior_count_30d` per (ticker, type).
2. **Radar watchlist ≪ tradeable book** — `CATALYST_WATCHLIST` defaults to ~14
   symbols while `approved_tickers` has ~31: the radar is blind to half the
   book (TSM, ASML, ARM, SPY/QQQ/IWM, the entire energy sleeve…).
3. **Un-anchored surprise** — gap% is session gap at decision time, not the
   move *since the catalyst published*; a stale afternoon catalyst inherits the
   morning gap.
4. **Cross-source duplicate events** — the same story from two feeds persists
   as two events (upsert keys include source), inflating radar novelty and
   duplicate-idea pressure.
5. **Detection latency unmeasured** — `published_at` vs `discovered_at` are both
   stored; nobody reports the gap, though a 3-minute poll cadence is only worth
   as much as the slowest feed.
6. **Macro and narrative-flow neutrality** — two of six composite components sit
   at constants for every candidate, wasting 20% of the composite's weight on
   non-discriminating inputs.

## 3. Highest-impact missing signals (ranked)

1. **Event-anchored price reaction** — % move and relative volume measured from
   `published_at` to now, not session open. The strongest short-horizon
   predictor for catalyst trading and the correct input for both `surprise` and
   PV confirmation. Requires `POLYGON_API_KEY` only.
2. **Empirical catalyst-type base rates** — replace the static
   `CATALYST_TYPE_WEIGHTS` / `_historical_score` guesses with hit rates measured
   from own history (`catalyst_events` × `signal_evaluations`, plus
   `catalyst_futures_reactions` for regime context). Fully backtestable offline
   because the engine is deterministic and pure.
3. **Options-flow activation** — the provider exists; wiring it into
   `_score_idea` turns a permanently-neutral 15% of the composite into signal.
4. **Earnings/event proximity** — days-to-earnings per candidate. Binary-event
   risk is currently invisible; also enables post-earnings-drift setups.
5. **Relative strength vs sector ETF** — candidate return minus mapped theme
   ETF return over the same window separates idiosyncratic catalyst moves from
   beta; computable from bars already fetched for Trending Stocks.
6. **Short interest / float context** — FINRA bi-monthly short interest + float
   size: squeeze potential for bullish catalysts, dilution sensitivity for
   offering (bearish) catalysts. Free, low cadence, easy join.
7. **Structured insider signal** — Benzinga insider transactions are already
   fetched but only keyword-matched; structure them (buy $ vs market cap,
   cluster of buyers, C-suite vs 10% holder).
8. **LLM structured extraction** — the analyst layer (off by default) can
   extract deal size, guidance direction, and materiality-vs-market-cap as
   *features* (numbers), not prose; deterministic fallback already exists.
9. **Theme-ETF flow automation** — 4-week returns for SMH/XLE/etc. fill the
   narrative flow input with one cached quote call per theme per day.
10. **Continuation statistics for swing timeframe** — gap-and-go vs fade base
    rates by setup type from own `signal_evaluations`, informing the
    intraday-vs-swing timeframe choice the radar currently hard-codes.

## 4. Data source recommendations

**Already integrated — unlock by configuration (human action, no code):**
`POLYGON_API_KEY` on the runner (intraday PV, options chain, news),
`SEC_USER_AGENT` (EDGAR), `BENZINGA_API_KEY` (news + insiders),
`CATALYST_WATCHLIST` expanded to match `approved_tickers`.

**Free, small new fetchers (code, but no vendor relationship):**
- Yahoo chart endpoint (already used for price fallback) → theme-ETF 4w returns
  and sector relative strength.
- FRED (no key for CSV endpoints) → real Fed funds / CPI / 10y / DXY trends for
  `MacroInputs`, replacing decision-time defaults.
- FINRA short-interest files (bi-monthly CSV) → short interest feature.
- Earnings dates: Polygon reference endpoint (if entitled) or Yahoo
  quoteSummary as fallback → days-to-earnings.

**Paid, later, only after the free features prove out:** intraday options sweeps
(Polygon options advanced tier / Unusual Whales) and dark-pool prints (FINRA ATS
weekly is free but 2–4 weeks delayed — acceptable for the *multi-day
accumulation* input, not for day-of signals).

## 5. Ranking & selection improvements

- **Cross-sectional ranking (diagnostics first):** per poll cycle, record each
  candidate's composite percentile within the cycle. Measure Spearman rank
  correlation between percentile and forward outcome before considering any
  top-N selection rule. Absolute thresholds treat a quiet tape and a busy tape
  identically; rank data shows whether that costs anything.
- **Calibration curve:** composite band → realized hit rate from
  `signal_evaluations` (the §4 threshold-step test in the calibration plan).
- **Offline replay harness (the key backtesting asset):** the scoring engine is
  deterministic and side-effect-free, and events + outcomes are persisted — so
  candidate weight tables can be re-scored against history in seconds, entirely
  offline. This is the mechanism that turns items 2, 5, 6 above into measured
  decisions instead of opinions.

## 6. Prioritized implementation roadmap

### Phase 0 — configuration only (human, this week)
0a. Set `POLYGON_API_KEY` on the runner (PV confirmation + options flow + news).
0b. Expand `CATALYST_WATCHLIST` to the full approved book.
0c. Verify `SEC_USER_AGENT` present on the runner.

### Phase 1 — diagnostics-only (no approval needed; build now)
1. **Replay harness** `scripts/replay_catalyst_scoring.py`: re-score stored
   `catalyst_events` under the current (or a candidate) weight table, join to
   `signal_evaluations` outcomes, report hit rate and average forward move by
   catalyst type, score band, source, and regime.
2. **Shadow features:** compute and *record* (never score) event-anchored move,
   relative strength vs theme ETF, days-to-earnings, and would-be
   `prior_count_30d` into the signal-evaluation payload, so predictive power is
   measured on live data before any of them touches the composite.
3. **Calibration-curve + rank report:** composite/confidence band → outcome;
   per-cycle percentile recording.
4. **Detection-latency report:** `published_at` vs `discovered_at` per source.
5. **Cross-source duplicate-event report:** candidate merge keys, measured
   duplication rate.

### Phase 2 — behavior changes (approval required, one at a time, each backed by Phase-1 evidence)
6. Wire `prior_count_30d` from `catalyst_events` into novelty.
7. Feed `MacroInputs` from the latest saved briefing (adapter exists).
8. Inject `PolygonOptionsFlowProvider` into `_score_idea`.
9. Supply theme-ETF 4w flow to the narrative component.
10. Event-anchored surprise replacing session gap.
11. Empirical catalyst-type weights (from replay-harness results, via the
    calibration plan's shadow-then-approve protocol).
12. Earnings-proximity feature/gate.
13. Equity exit management (carried over from the calibration plan — biggest
    unblocker of position-slot pressure; not an alpha feature per se).

Ordering rationale: Phase 0 items cost nothing and two of them (key + watchlist)
directly gate how much *data* every later step gets. Phase 1 builds the
measurement loop so every Phase 2 proposal arrives with an evidence pack. Phase
2 is sequenced by expected effect size over implementation risk: dead-input
fixes (6–9) before formula changes (10–11) before new gates (12).

## 7. Explicitly out of scope

No threshold loosening, no gate removal, no scheduler/paper-mode changes, no
`.env` edits by agents, and nothing that bypasses the approval workflow. All
Phase 2 items follow `docs/CALIBRATION_PLAN.md` §2 (shadow → evidence pack →
single approved change → rollback criteria).
