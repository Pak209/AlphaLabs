# AlphaLabs five-year review — the ten foundational opportunities

Written 2026-07-04, closing the 2026 architecture cycle (pipeline audit →
telemetry → replay → attribution → calibration → outcomes → portfolio →
backtesting design). Perspective: owning this codebase for five years.
Incremental improvements are deliberately ignored; each item below is a
capability that changes what the platform *is*, not what it does this week.

The platform philosophy is preserved throughout and is non-negotiable:
evidence → replay → shadow validation → explicit human approval before any
behavior change; paper-only forever unless a human decides otherwise.

## Executive summary

AlphaLabs' strengths are unusual for a project this young: a deterministic,
pure, scenario-parameterized scoring engine; a decision engine that is a pure
function behind an abstract broker; end-to-end structured telemetry; and a
disciplined evidence loop with append-only operational memory. The safety
architecture is genuinely good.

Its ceiling, however, is set by three things it does not yet have: **data**
(no historical store, features computed from live fetches, a 14-name catalyst
watchlist), **labels** (one ad-hoc forward move at an arbitrary evaluation
time), and **reproducibility of the past** (config tables are latest-only).
Every sophisticated ambition — calibrated probabilities, Kelly sizing,
walk-forward validation, ML anything — is capped by those three. The first
four opportunities below are therefore data-and-measurement foundations; the
rest build the research institution on top of them. A platform that measures
itself honestly for five years will beat a platform that ships clever
features for five years.

## The ten opportunities

### 1. Historical data foundation
**What:** A first-class market-data layer: daily (later intraday) bar cache,
option-chain snapshots, corporate calendar, ingestion jobs with provenance
and gap detection — across an expanded universe (hundreds of names, not the
current watchlist).
**Why it matters:** Today every feature is computed from a live fetch at
decision time and then lost. No stored bars ⇒ no volatility measurement, no
relative strength, no correlation, no backtests, no event-anchored features.
This is the single binding constraint on everything else.
**Depends on:** nothing. This is the root.

### 2. Fixed-horizon, benchmark-adjusted label store
**What:** Replace the single ad-hoc `move_after_pct` with systematic labels
per idea: forward returns at fixed horizons (1d/5d/20d), benchmark- and
beta-adjusted excess returns, target-before-stop indicators, MFE/MAE
(max favorable/adverse excursion).
**Why it matters:** Labels are the denominator of every claim the platform
makes. Attribution, calibration curves, Kelly fractions, and gate-regret
verdicts are all only as good as the outcome variable — and today's outcome
variable has an uncontrolled horizon and no market adjustment (a bullish idea
"wins" in a rally it merely rode).
**Depends on:** #1 (bars supply the horizons and the benchmark).

### 3. Point-in-time everything (config as data)
**What:** Version every table that influences a decision — themes, phases,
keyword weights, catalyst-type weights, risk configs, watchlists — with
as-of semantics, so any past decision can be exactly reproduced and any
historical simulation uses the config that *was* true.
**Why it matters:** Reproducibility is the difference between a research
platform and a pile of scripts. It also unlocks honest backtests (the
designed `config_snapshots`) and turns "why did we take this trade in March?"
from archaeology into a query.
**Depends on:** nothing technically; urgent early because history only
accrues from the day it starts.

### 4. Build the backtesting engine (from the approved design)
**What:** Execute `docs/BACKTESTING_ARCHITECTURE.md` M0–M5: event timeline,
simulated broker behind the *unchanged* live decision engine, exit-policy
engine, experiment tracker, walk-forward runner with the multiple-testing
ledger.
**Why it matters:** It converts five years of accumulating data into five
years of testable hypotheses, with the same gate-trace vocabulary as live.
Mechanics questions (exits, sizing, signal competition) become answerable
immediately; edge questions become answerable as the archive grows.
**Depends on:** #1, #3.

### 5. Unified research registry
**What:** One provenance chain as data: hypothesis → attribution nomination →
replay/backtest runs (config hash, fingerprint) → shadow trial → approval
decision → production change → post-change outcome review. Today these live
across handoff prose, JSON report directories, and approval tables.
**Why it matters:** At five-year scale the scarcest resource is *knowing what
was already tried and why it was rejected*. A registry makes negative results
durable, makes the multiple-testing ledger platform-wide, and makes every
production parameter traceable to the evidence that justified it.
**Depends on:** #4 (its run records are the main content), light otherwise.

### 6. Calibrated probabilistic scoring
**What:** Evolve the composite from hand-assigned 0–100 weights to calibrated
estimates — P(directional win) and expected excess move with intervals —
fitted on accumulated labels (isotonic/logistic at first; the deterministic
engine remains as prior and fallback). Scores become statements that can be
*wrong*, and are scored on their calibration (Brier) continuously.
**Why it matters:** "Composite 74" currently means nothing outside its own
scale. "62% win probability, calibrated on 400 outcomes" is a decision-grade
number — and the only honest input Kelly-style sizing can ever have. This is
the endpoint the empirical-base-rates work has been pointing at.
**Depends on:** #2 (labels), #4 (validation), #5 (tracking). Graduates
component-by-component through the calibration protocol.

### 7. Structured event understanding
**What:** Replace keyword matching as the primary event reader: typed,
structured extraction (event class, deal size vs market cap, guidance
direction and magnitude, named counterparties) using the existing LLM analyst
layer — governed by an eval harness with a golden set, versioned prompts, and
extraction-accuracy tracking, with the keyword engine as deterministic
fallback. Broaden sources and universe in tandem.
**Why it matters:** The catalyst layer is the platform's eyes. A 35-keyword
table over 14 tickers reads press releases the way a regex reads poetry.
Structured magnitudes ("$2B contract for a $500M company") are the
materiality signal the scoring engine currently fakes with heuristics.
**Depends on:** #1 (universe), #5 (eval tracking); the eval harness is the
approval gate for any prompt change.

### 8. Portfolio and risk engine as a shared module
**What:** Extract portfolio logic into one module with a policy interface —
sizing (flat → conviction → fractional Kelly), heat and exposure accounting,
theme/correlation constraints, per-cycle signal competition — consumed
identically by the backtester, the shadow layer, and (only after approval,
policy by policy) the live path.
**Why it matters:** Portfolio decisions are where research becomes P/L, and
today they are flat constants baked into the decision engine. One shared
module means a sizing policy validated in simulation is *bit-for-bit* the
policy that ships — no reimplementation gap. Additive caps (heat, theme)
strengthen safety as capability grows.
**Depends on:** #4 (validation venue), #6 (real sizing inputs), #2.

### 9. Position lifecycle engine
**What:** First-class management from entry to exit: exit policies as data
(stop/target, time stops, trailing, event-driven), an order state machine
with fill-quality telemetry, and paper-vs-sim drift measurement.
**Why it matters:** The platform can open positions but not close them — the
single largest distortion in its own outcome data (slots clog, duplicate
gates fire, P/L is unrealized forever). Every layer above gets cleaner data
the day exits exist. Also the venue where execution assumptions in the
backtester get validated against reality.
**Depends on:** #4 for policy validation; behavior change requires approval
(it touches orders) — the highest-priority approval request in the queue.

### 10. Operational integrity and silent-failure detection
**What:** Continuous data-quality and self-consistency monitoring: source
health (a feed that quietly returns nothing degrades evidence silently),
sample-fallback detection, label-pipeline freshness, paper-vs-sim drift,
config-vs-snapshot drift, dead-input alarms (the attribution layer already
detects these — alert on them), plus runtime supervision beyond one launchd
box.
**Why it matters:** The platform's entire value proposition is that its
evidence is trustworthy. The failure mode that kills five-year projects is
not a crash — it is six months of subtly wrong data discovered during an
important decision. Monitoring the *evidence pipeline itself* is what makes
every other investment durable.
**Depends on:** nothing; starts now and never finishes.

## Suggested implementation order

```
Year 1:  #1 data foundation ─┬─ #3 point-in-time (start week 1 — history
                             │   only accrues forward)
         #10 ops integrity ──┤   (continuous from day 1)
         #2 label store ─────┤
         #4 backtest engine ─┘
Year 2:  #5 research registry, #9 lifecycle engine (approval),
         #7 event understanding (begins; universe grows with #1)
Year 3+: #6 calibrated scoring (as labels reach sample floors),
         #8 portfolio engine (policy by policy, approval by approval)
```

The ordering rule: capabilities that *accumulate* (data, snapshots, labels,
monitoring) start earliest because their value is proportional to elapsed
time; capabilities that *consume* (calibration, sizing) wait for the sample
floors the calibration plan already defines.

## Research forever vs production capabilities

**Production track (graduate through shadow → approval, in this order):**
exit management (#9); conviction-weighted sizing under existing caps;
additive heat and theme caps; per-cycle batch selection; calibrated
score components (#6) one at a time; fractional Kelly (≤ ¼, capped by
existing per-trade limits) only after calibration survives ≥ 2 quarters
out-of-sample.

**Research forever (valuable as instruments, never allowed to trade):**
- **Full-Kelly or uncapped optimal-f sizing** — estimation error at this
  scale makes it indistinguishable from gambling; the caps are the product.
- **LLM-autonomous trade decisions** — the analyst layer extracts, explains,
  and proposes; a model output is never an order. Extraction accuracy is
  measurable; judgment is not.
- **Mean-variance / correlation-matrix optimization** — with dozens of
  positions and weeks of history, the matrix is noise; use constraint-style
  caps instead. Revisit only if the platform someday has thousands of
  observations per pair — and probably not even then.
- **Intraday microstructure strategies** — the data, latency, and cost
  modeling requirements are a different platform; explicitly out of scope.
- **Live-money trading** — remains a human decision outside this document's
  scope by standing policy; nothing here changes the paper-only posture.

Everything in the production track passes through the same gate: evidence
pack on the registry, shadow validation on live dry-runs, explicit human
approval, single change, rollback criteria. That protocol is the platform's
most valuable asset. It is also the one thing that must never be optimized
away for speed.
