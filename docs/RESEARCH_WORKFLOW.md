# AlphaLabs quantitative research workflow

Status: **framework definition — no live behavior changes.**
Written 2026-07-04, alongside `docs/CALIBRATION_PLAN.md` (threshold governance)
and `docs/ALPHA_GENERATION_AUDIT.md` (feature inventory). This document defines
how new ideas — signals, features, scoring changes, thresholds, data sources,
strategies — are researched, validated, compared, and promoted into production
using the decision telemetry the system already collects.

Tooling lives in `research/` (read-only analysis package; see
`research/README.md`). Nothing in this workflow touches runtime code, the
scheduler, launchd, `.env`, or any trading path. Every production change that
eventually results from it goes through the approval rules in
`CLAUDE.md` / `.ai/agent-rules.md` and the never-loosen list in
`docs/CALIBRATION_PLAN.md`.

---

## 1. The telemetry substrate (what research runs on)

Everything below is already recorded in production; research adds no
collection.

| Surface | Table / source | What it answers |
|---|---|---|
| Idea population | `alpha_ideas` (incl. `status`, `rejection_reason`) | Every idea ever generated, **including rejected ones** |
| Forward outcomes | `signal_evaluations` (alert price, `move_after_pct`, `benchmark_move_pct`, early-detection score, grades) | The label for every idea — rejected ideas keep their evaluations, so counterfactuals are measurable |
| Gate traces | `execution_audit.payload_json._gates` (+ `gate_context`) | Per-attempt observed value, threshold, comparator, pass/fail, enforced/advisory for every gate — replayable offline |
| Decision records | `decision_logs`, `serialize_decision()` output | The full decision with first-failed-gate attribution |
| Pre-idea funnel | `scanner_runs` summaries | Where candidates die before becoming ideas |
| Catalyst features | `catalyst_events` (sub-scores, matched keywords, raw payload) | As-of-decision inputs for catalyst scoring research |
| Realized trades | `trades` + `training_rows` view | Entry conviction (alpha components, option greeks, spread) joined to realized P/L |
| Event reactions | `catalyst_futures_reactions` | Catalyst timestamp → subsequent futures move (event-study backdrop) |
| Human labels | `journal_entries` (`thesis_correct`, `mistake_tag`) | Qualitative error taxonomy |
| Aggregates | `AlphaLabService.rejection_waterfall()`, `scripts/waterfall_snapshot.py` per-session samples | Funnel shape, per-gate failure/near-miss counts, threshold quantiles |

Two structural facts make offline research trustworthy here:

1. **The scoring engine is a pure function** (`alpha_lab/scoring_engine.py`
   over the explicit input models in `scoring_models.py`), so any proposed
   scoring change can be replayed over recorded inputs with no side effects.
2. **Advisory gate records** (`enforced: false`, as used by the dry-run alpha
   gate) already flow through the waterfall — a built-in shadow-testing
   channel that requires no behavior change to read.

### Population discipline (non-negotiable)

- **Structured rows only** for any distributional claim. Legacy free-text
  rejections have no observed values; compare populations only as rates per
  100 attempts, never mixed raw counts (`CALIBRATION_PLAN` §3).
- **Expected structural breaks** from the 2026-07-04 fixes (crypto_long_only
  → ~0, market_open → ~0, alpha composite becoming a real distribution) are
  regime boundaries, not drift. Research windows start at a break, never
  straddle one.
- **Label lag**: `signal_evaluations` fill on the 13:50 PT job; a session's
  labels are complete only after its evaluation pass. Never analyze a window
  whose labels are still provisional unless the report says so.

---

## 2. Research workflow (R0 → R5)

```
R0 intake → R1 feasibility → R2 offline replay → R3 shadow → R4 review → R5 monitor
   (spec)      (data audit)      (backtest)       (advisory)   (human)     (waterfall)
```

**R0 — Intake.** Ideas come from telemetry anomalies (a gate with persistent
near-miss regret, a source with decaying hit rate), audit findings
(`ALPHA_GENERATION_AUDIT` §2 dead inputs), journal lessons, or new-source
proposals. Each becomes a **pre-registered spec** in `research/experiments/`
(copy `TEMPLATE.json`): one falsifiable hypothesis, one primary metric, the
decision rule, and minimum samples — written **before** outcomes are looked
at. The registry index tracks status.

**R1 — Feasibility & leakage audit.** Confirm the telemetry already contains
the inputs (as-of decision time) and labels (strictly forward). Complete the
spec's leakage checklist. Do the sample-size arithmetic up front: with the
current ~5–15 accepted decisions/week band, most decision-level questions need
weeks of data — the spec must say how long collection runs before the first
read. If inputs don't exist historically (Class C below), R2 is impossible and
the experiment goes straight to a shadow-collection design.

**R2 — Offline replay.** Run the spec through
`python3 -m research.run_experiment` against the frozen window. The runner
computes the standard battery (§5) and emits a validation report (§7). For
scoring-model changes, replay recorded inputs through the pure scoring
function under baseline and variant parameters and compare on identical
populations. All replays are read-only; simulated pass rates come from
recorded observed values, never from editing live thresholds.

**R3 — Shadow (advisory) phase.** For survivors of R2: propose a
diagnostics-only change adding the variant as advisory gate records
(`enforced: false`) or a parallel-logged score. This is the only step that
touches the repo's runtime files, it is *observationally* inert, and it still
goes through normal review (it is a code change; handoff entry required).
Collect ≥ 3 sessions (Class A/B) or ≥ 5 sessions (Class C/D), then re-run the
experiment on prospective data only.

**R4 — Promotion review.** Human decision against the promotion criteria
(§6), one change per decision, with the evidence pack attached. Anything on
the never-loosen list stops here regardless of evidence strength unless a
human explicitly approves.

**R5 — Post-promotion monitoring.** Five sessions of `waterfall_snapshot.py`
deltas plus the acceptance-volume band. Rollback triggers are pre-committed
(§6, P4). A promoted change that gets rolled back reopens its experiment with
status `rejected` and the observed failure attached.

---

## 3. Idea sources, ranked by evidence already in hand

Standing research queue, refreshed whenever a validation report lands:

1. **Regret mining (weekly):** run regret analysis per quality gate
   (`confidence`, `alpha_composite_tier`, radar floor). A persistent
   `regret_flag` with passing sample gates spawns a Class A experiment.
2. **Dead/degraded inputs:** `ALPHA_GENERATION_AUDIT` §2 items
   (`prior_count_30d` novelty, macro-at-decision, narrative flow) — each is a
   Class B/C experiment with a natural baseline (current behavior).
3. **Calibration drift:** stated confidence vs realized hit rate by source
   and regime. Miscalibrated sources are formula candidates
   (`CALIBRATION_PLAN` candidate #2).
4. **Source scorecards:** per-source hit rate / excess move / early-detection
   distributions decide where generator work is worth doing (Class D).
5. **Event studies:** `catalyst_futures_reactions` + `catalyst_events` to
   re-derive the catalyst-type weight table from measured reactions
   (`CALIBRATION_PLAN` candidate #4).

---

## 4. Experiment classes

| Class | Scope | Offline replay? | Shadow required? | Governing constraint |
|---|---|---|---|---|
| **A** | Threshold calibration of an existing gate | Yes — observed values are recorded | Yes (≥ 3 sessions) | `CALIBRATION_PLAN` decision matrix + never-loosen list |
| **B** | Scoring-model change (weights, sub-signal formulas) | Yes — pure-function replay over recorded inputs | Yes (≥ 3 sessions) | CRITICAL-RULE structure untouchable without approval |
| **C** | New signal / feature / data source | No historical inputs — shadow-collect first | Yes (≥ 5 sessions of collection *before* any claim) | Provider costs/keys are human decisions |
| **D** | New idea generator / strategy | Partially (on generic labels) | Yes (≥ 5 sessions), then dry-run acceptance stage | Full ladder; watchlist scope is human-controlled |

---

## 5. Standard metric battery

Every experiment reports the same battery (`research/metrics.py`), so results
are comparable across experiments and over time:

- **Primary label:** direction-signed excess move
  (`signed move − signed benchmark move`); **hit** = excess > 0. Secondary
  labels: raw signed move, `early_detection_score`, and — where trades exist —
  `training_rows.realized_return`.
- **Outcome summary:** hit rate (95% Wilson CI), mean excess move (95% CI),
  label coverage.
- **Threshold-step test:** below / near-miss / above bands around a cutoff;
  a real threshold shows non-overlapping intervals at the step
  (`CALIBRATION_PLAN` §4.1).
- **Regret analysis:** accepted vs near-miss-rejected vs far-rejected forward
  outcomes with first-failed attribution (§4.2).
- **Bucket lift + Spearman:** monotonicity of score vs outcome — a score that
  doesn't rank outcomes can't justify a threshold on it.
- **Calibration table:** stated confidence vs realized hit rate.
- **Session stability:** per-session means and positive-session share — an
  edge concentrated in one session is noise until proven otherwise.
- **Simulated pass rates** at proposed thresholds, from recorded values only.

**Comparison rules.** Baseline is always current production behavior replayed
on the same window, same population, same labels. Compare interval bounds,
not point estimates. A challenger beats the champion only if its primary
metric interval clears the champion's on the shared population AND no
guardrail metric degrades. When two challengers tie, the simpler one (fewer
parameters, fewer data dependencies) wins by default.

**Multiplicity discipline.** One primary metric per experiment, pre-registered.
Everything else in the report is exploratory and can only spawn *new*
pre-registered experiments, not conclusions. Re-reading the same window with a
new hypothesis is a new experiment against a *later* window.

---

## 6. Promotion criteria (P0 → P4)

A change is promotable only through this ladder, in order, one change per
decision. "CI" means the 95% interval from the battery.

**P0 — Registered.** Spec merged in `research/experiments/` with: unique id,
falsifiable hypothesis, single primary metric, decision rule phrased against
interval bounds, leakage checklist complete, class assigned, never-loosen
acknowledgment, minimum samples consistent with `CALIBRATION_PLAN` §2 floors
(≥ 50 structured evaluations and ≥ 10 failures per analyzed gate; ≥ 30
accepted decisions for outcome-linked claims; ≥ 200 evaluations for
confidence-formula work; ≥ 5 sessions always).

**P1 — Offline-validated.** On a frozen window that meets the spec's sample
gates: primary-metric improvement whose CI excludes the null; monotonicity or
step evidence where the change is a threshold/score; guardrails intact
(acceptance volume projected to stay in the 5–15/week band; no never-loosen
gate projected to fire more often); structured rows only; verdict recorded in
a committed-or-archived validation report.

**P2 — Shadow-validated.** Advisory records collected prospectively (≥ 3
sessions Class A/B, ≥ 5 Class C/D): prospective effect retains ≥ 50% of the
offline effect size (shrinkage check); advisory/live disagreements are
explained; no guardrail breach observed live.

**P3 — Approved.** Explicit human approval; one threshold/feature per change;
never-loosen items untouched (or the approval explicitly names the item);
tests updated in the same change; handoff entry appended with the evidence
pack; a named rollback trigger and a named owner for the P4 watch.

**P4 — Production-monitored.** Five sessions of post-change waterfall deltas.
**Auto-revert** (no debate, revert first) if any of: acceptance rate leaves
the 5–15/week band; any never-loosen gate fires more often than its
pre-change baseline; any daily-drawdown event; order volume pressures
`max_trades_per_day`. A reverted change re-enters at P0 with the failure as
evidence.

**Hard stops at every stage:** nothing in this workflow arms paper mode,
touches `.env`, launchd, or the scheduler; re-arming paper trading is a
separate human decision outside research scope, always.

---

## 7. Validation reports

Generated by `python3 -m research.run_experiment <spec>` into
`research/validation/` as Markdown + JSON (see committed sample
`research/validation/SAMPLE-EXP-0000.md`, fabricated data). Contract:

1. Header: experiment id/title, class, spec status, window, population size,
   label coverage, session count, **verdict**.
2. Pre-registered hypothesis and decision rule, echoed verbatim.
3. Sample-gate table (observed vs required — the interpretability gate).
4. The full battery, intervals everywhere.
5. Reproduction command.

Runner verdicts are deliberately limited to **INSUFFICIENT_DATA** (a sample
gate failed; no interpretation permitted) and **READY_FOR_REVIEW** (battery
computed; the human applies the decision rule). The tool never says
"promote" — promotion language belongs to the P3 human decision, recorded in
the handoff log.

Reports generated from the production database stay untracked (gitignored in
`research/validation/`, same policy as `reports/`); the spec, the decision,
and the handoff entry are the durable record.

---

## 8. Operating cadence

- **Per session (existing):** scheduler dry-run cadence collects; one
  `waterfall_snapshot.py` sample after the close (`CALIBRATION_PLAN` §5).
- **Weekly:** regret mining pass over the quality gates; source scorecard
  refresh; registry status review (experiments stuck `running` past their
  sample horizon get a decision: extend or close).
- **Per experiment:** R0–R5 as above; every status transition appends a
  handoff entry (`.ai/LEX_REVIEW_HANDOFF.md`) — registration, first read,
  shadow start, promotion decision, rollback.
- **Quarterly:** re-run every promoted experiment's battery on the newest
  window (decay check); prune the registry.
