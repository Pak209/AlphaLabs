# AlphaLab Implementation Order — Highest to Lowest ROI

**Assumptions:** one solo developer, account size < $1M (paper), goal is improving paper-trading
results as quickly as possible. ROI = expected alpha improvement per unit of dev effort, adjusted for
dependencies. Effort is in solo-dev days. "Expected alpha improvement" is a directional estimate of how
much each feature lifts paper-trade quality (hit rate × payoff), not a precise forecast.

References: [analyst-brain-framework.md](analyst-brain-framework.md),
[analyst-brain-mvp-engine.md](analyst-brain-mvp-engine.md),
[analyst-brain-v1-plan.md](analyst-brain-v1-plan.md).

---

## TL;DR Ranking

| Rank | Feature | Effort | Expected Alpha Lift | Key Dependency |
|------|---------|--------|---------------------|----------------|
| 1 | MVP Scoring Engine | 5 days | High | None (existing scanners + feeds) |
| 2 | Performance Scoreboard | 2 days | High (indirect) | Paper trades flowing |
| 3 | Catalyst Ranking | 2 days | Medium-High | MVP Scoring Engine |
| 4 | Macro Regime Engine | 2 days | Medium | Macro Score (from MVP) |
| 5 | Narrative Tracking | 3 days | Medium | Narrative Score (from MVP) |
| 6 | Post-Trade Learning | 4 days | Medium (compounding) | Scoreboard + score history |
| 7 | Bottleneck Overlay | 3 days | Low-Medium | Narrative Tracking |

**Build order = the rank column.** Rationale below.

---

## 1. MVP Scoring Engine — *highest ROI, build first*

- **Effort:** ~5 days (the day-by-day plan in [analyst-brain-mvp-engine.md](analyst-brain-mvp-engine.md)).
- **Expected alpha improvement:** **High.** This is the single biggest lever. Today paper trades are
  presumably fired on raw catalysts with no quality filter. A Catalyst/Narrative/Macro composite that
  drops everything below 60 and sizes by tier will cut the worst trades immediately. Most of the lift in
  this entire list comes from simply *not taking bad trades*.
- **Dependencies:** None new. Uses existing catalyst scanners, catalyst history DB, market data feed,
  and free FRED data.
- **Why first:** Everything else either feeds it, ranks its output, or learns from its results. Without
  it, there are no scores to rank, track, or learn from.

## 2. Performance Scoreboard — *build second, before adding more signals*

- **Effort:** ~2 days. A table/dashboard that joins each paper trade to its scores and computes outcome
  metrics: win rate, average P&L, and P&L bucketed by Composite tier (80+, 70–79, 60–69) and by each
  sub-score band.
- **Expected alpha improvement:** **High but indirect.** It produces no signal itself, but it's the
  measurement instrument for every other feature. Without it you are flying blind — you cannot tell
  whether the scoring engine or any later feature actually helped. Building it second means every
  subsequent feature ships with a built-in before/after readout.
- **Dependencies:** Paper trades must be flowing with their score breakdowns attached (delivered by #1).
- **Why this high:** Cheap, and it converts all later work from guesswork into measured iteration. The
  ROI of every feature after this is higher because you can verify it.

## 3. Catalyst Ranking — *cheap leverage on the strongest signal*

- **Effort:** ~2 days. Sort/queue catalysts by Catalyst Score (and Composite) so the highest-conviction
  ideas surface first; add a daily top-N ranked list and dedup of near-identical catalysts.
- **Expected alpha improvement:** **Medium-High.** Catalyst is the heaviest-weighted, most predictive
  component. Ranking concentrates attention and capital on the best ideas and prevents the queue from
  being flooded by marginal ones — directly improves average trade quality in a small account where you
  can only hold a handful of positions.
- **Dependencies:** MVP Scoring Engine (#1).
- **Why here:** Tiny effort on top of #1, operates on the highest-edge signal. Comes after the
  scoreboard so its impact is measurable.

## 4. Macro Regime Engine — *promote the daily Macro Score into a regime gate*

- **Effort:** ~2 days. Extend the MVP's daily Macro Score into an explicit regime label
  (risk-on / neutral / risk-off / defensive) plus a global sizing/throttle rule: e.g., suppress new
  longs when risk-off, scale unit size by regime.
- **Expected alpha improvement:** **Medium.** Macro rarely creates winners but reliably prevents
  clusters of losers (avoiding longs into a risk-off tape). For a <$1M account, drawdown avoidance is
  worth more than marginal upside. The MVP already computes the score; this turns it into a portfolio-level
  switch.
- **Dependencies:** Macro Score from MVP (#1).
- **Why here:** Higher leverage than narrative work because it's account-wide (one switch affects every
  trade), and the underlying score already exists, so the marginal effort is low.

## 5. Narrative Tracking — *make the static narrative inputs live*

- **Effort:** ~3 days. Automate what the MVP holds in static config: track theme-ETF flows/returns on a
  schedule, auto-update phase (expansion/peak/fading) from price+flow trends, and flag rotation between
  themes.
- **Expected alpha improvement:** **Medium.** Narrative is a real multiplier and being in an *expanding*
  theme materially improves follow-through. But the MVP already captures most of this statically; this
  feature mainly removes manual upkeep and catches phase transitions a bit earlier. Incremental, not
  transformational.
- **Dependencies:** Narrative Score from MVP (#1); benefits from the Scoreboard (#2) to prove the live
  version beats the static one.
- **Why here:** More effort than #3/#4 for a smaller, slower-moving edge, but still ahead of learning
  and bottleneck work because it improves a core composite input.

## 6. Post-Trade Learning — *compounding ROI, but needs data first*

- **Effort:** ~4 days. A feedback loop: periodically recompute which sub-signals and weights correlate
  with realized P&L, and propose weight adjustments (e.g., reweight catalyst_type_weights, tune
  thresholds). Keep it rule-based and human-approved at first — no autonomous retraining.
- **Expected alpha improvement:** **Medium, and compounding.** Each tuning cycle nudges the engine
  toward what actually works in *your* paper environment. The catch: it needs a meaningful sample of
  scored trades and outcomes before it can say anything reliable, so its ROI is near-zero on day one and
  grows over weeks.
- **Dependencies:** Scoreboard (#2) for outcomes + accumulated score history. Genuinely cannot start
  earlier — no data to learn from.
- **Why this low:** High eventual value but gated on data accumulation; doing it earlier wastes effort on
  too small a sample. Sequence it once weeks of trades exist.

## 7. Bottleneck Overlay — *intellectually valuable, lowest near-term ROI*

- **Effort:** ~3 days for the MVP overlay (static `ticker→layer` tag + manual `is_current_bottleneck`
  flag → small composite bonus, per [analyst-brain-v1-plan.md](analyst-brain-v1-plan.md)). The full
  framework engine (lead-time, margin, transcript mining) is far more and explicitly out of scope.
- **Expected alpha improvement:** **Low-Medium near term.** It's a differentiator and can find
  structural winners early, but as a static overlay it adds only a small bonus and overlaps heavily with
  Narrative Tracking. The full version's edge is real but the effort-to-payoff ratio in the first month
  is the weakest on this list.
- **Dependencies:** Narrative Tracking (#5) — themes and layers share most of the same plumbing.
- **Why last:** Highest concept value, lowest immediate, measurable paper-trade lift per dev-day.
  Revisit once #1–#6 are in and the scoreboard shows where remaining edge is missing.

---

## Sequencing Logic (one-paragraph summary)

Build the **engine** first because it removes the worst trades (the biggest single lift), then the
**scoreboard** so every later change is measured rather than guessed. **Catalyst Ranking** and the
**Macro Regime** gate are next: both are cheap extensions of signals the engine already produces and
both act as high-leverage filters (best-ideas-first, and account-wide risk-off throttle). **Narrative
Tracking** follows as an incremental upgrade of an existing input. **Post-Trade Learning** waits until
enough trades exist to learn from, after which it compounds. **Bottleneck Overlay** comes last: real
long-term edge, but the lowest measurable paper-trade ROI per dev-day in the first month.
