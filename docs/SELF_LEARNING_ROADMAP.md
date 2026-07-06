# AlphaLabs self-learning roadmap

Status: **design — no live behavior changes, no autonomous deployment.**
Written 2026-07-04. Defines how AlphaLabs learns from accumulated outcomes —
historical trades, rejected ideas, replay results, attribution reports, and
backtests — and turns them into **recommendations for human review**. The
system analyzes and proposes; humans decide and deploy. Nothing in this
design gives any component the ability to change a threshold, weight, sizing
rule, or strategy on its own.

Companions: `docs/RESEARCH_WORKFLOW.md` (experiment ladder P0–P4),
`docs/CALIBRATION_PLAN.md` (never-loosen list, tuning protocol),
`docs/ARCHITECTURE.md` (governance plane, ModelPort extension point),
`docs/FEATURE_ATTRIBUTION.md` / `docs/OUTCOME_REPORTING.md` /
`docs/BACKTESTING_ARCHITECTURE.md` (analyzer methodology).

---

## 1. Stance: a recommend-only learner

Four commitments that hold at every phase:

1. **Learning artifacts are data, never code or config.** The learner writes
   recommendation records, evidence packs, and reports under `research/`.
   It has no write path to runtime code, `.env`, config JSON, launchd, the
   scheduler, or the database schema — and the Phase 0 import-boundary
   contracts (`alpha_lab/tests/test_import_boundaries.py`) already make the
   research→runtime direction a test failure.
2. **Every recommendation rides the existing ladder.** Replay (offline) →
   pre-registered experiment → shadow validation (advisory `enforced:false`
   records) → explicit human approval → monitored rollout. No shortcut lane
   exists, including for "obvious" wins.
3. **The never-loosen list is out of scope for automation entirely.** The
   learner may *observe* that a hard safety control binds often; it may not
   even draft a loosening recommendation for one. Those items change only
   through a human-initiated decision (`CALIBRATION_PLAN` §1).
4. **The learner is accountable to its own track record.** Every
   recommendation's eventual fate (accepted/rejected, and post-change
   performance if promoted) is recorded in a decision ledger. A learner
   whose promoted recommendations get reverted loses its recommendation
   budget (§7, safeguard S9).

---

## 2. Self-learning architecture

The loop closes over components that already exist; the new layers are the
recommender, the ledger, and the cycle orchestration.

```
                        ┌─────────────────────────────────────────────┐
                        │            OUTCOME SUBSTRATE (exists)        │
                        │ signal_evaluations · execution_audit gates   │
                        │ decision_logs · trades/training_rows         │
                        │ catalyst_events · catalyst_futures_reactions │
                        │ journal_entries · waterfall snapshots        │
                        └──────────────────────┬──────────────────────┘
                                               │ read-only
                        ┌──────────────────────▼──────────────────────┐
                        │            ANALYZER BANK (exists)            │
                        │ outcomes.outcome_report / near_miss_report   │
                        │ attribution.feature_attribution_report       │
                        │ attribution.gate_regret_report               │
                        │ replay.build_replay_dataset + scenarios      │
                        │ portfolio.build_portfolio_snapshot + whatif  │
                        │ research.metrics battery · backtests         │
                        └──────────────────────┬──────────────────────┘
                                               │ findings (JSON)
                        ┌──────────────────────▼──────────────────────┐
                        │        RECOMMENDER (new, read-only)          │
                        │ detectors → draft REC records with evidence  │
                        │ budget caps · dedupe · expiry · ranking      │
                        └──────────────────────┬──────────────────────┘
                                               │ REC-#### artifacts
        ┌───────────────┬──────────────────────▼───────────────┐
        │  VALIDATION (exists: research ladder)                │
        │  replay scenario → EXP pre-registration → offline    │
        │  battery → shadow advisory records (≥3–5 sessions)   │
        └───────────────┬──────────────────────────────────────┘
                        │ evidence pack
              ╔═════════▼══════════╗     every transition appends to
              ║   HUMAN REVIEW     ║──── the handoff log; approval is
              ║ approve · reject · ║     one change per decision
              ║ defer · descope    ║
              ╚═════════┬══════════╝
                        │ approved only
        ┌───────────────▼──────────────────────────────────────┐
        │  DEPLOYMENT (human hands, never the learner)         │
        │  config/code edit by human or explicitly-approved    │
        │  change · tests updated · P4 five-session monitoring │
        └───────────────┬──────────────────────────────────────┘
                        │ observed post-change performance
        ┌───────────────▼──────────────────────────────────────┐
        │  DECISION LEDGER (new)                               │
        │  verdicts · realized effect vs predicted effect      │
        │  reverts · learner calibration score                 │
        └───────────────────────────────────────────────────────┘
                        │
                        └──── feeds back into recommender ranking
```

Ownership follows `docs/ARCHITECTURE.md` §3: the substrate belongs to the
store, analyzers to evaluation, the recommender and ledger to research,
deployment to humans via the governance plane. The recommender is a research
component and inherits research's isolation: read-only DB access, no runtime
imports, no scheduler authority.

---

## 3. Recommendation pipeline

### 3.1 Recommendation record (`research/recommendations/REC-NNNN-*.json`)

Same discipline as experiment specs: one artifact per recommendation,
registered before persuasion begins, append-only registry index.

```json
{
  "id": "REC-0001",
  "type": "threshold | scoring | feature | sizing | strategy",
  "status": "draft | validating | shadowing | under_review | approved | rejected | deferred | expired | monitored | confirmed | reverted",
  "title": "One-line change proposal",
  "detector": "gate_regret | attribution_decay | calibration_drift | replay_sweep | sizing_whatif | scorecard | backtest",
  "claim": "Falsifiable statement of the expected improvement, with magnitude",
  "predicted_effect": {"metric": "...", "delta": 0.0, "interval": [0.0, 0.0]},
  "evidence": ["research/validation/EXP-XXXX-*.json", "replay scenario ids"],
  "experiment_id": "EXP-XXXX (required before status leaves draft)",
  "never_loosen_conflict": false,
  "expires": "YYYY-MM-DD (stale evidence must be regenerated)",
  "decision": {"by": null, "at": null, "verdict": null, "note": null},
  "post_change": {"monitor_until": null, "realized_effect": null, "reverted": false}
}
```

`never_loosen_conflict: true` is a terminal flag: the pipeline refuses to
advance such a record past `draft`; it exists only as a human-readable
observation ("this control binds N times/week") for a human to pick up or
not.

### 3.2 Recommendation types and their validation routes

| Type | Examples | Offline validation | Shadow requirement | Extra approval scope |
|---|---|---|---|---|
| **threshold** | radar floor 68, PV deadband, confidence coefficients (`CALIBRATION_PLAN` §1 candidates only) | Threshold-step + regret battery on recorded observed values; simulated pass rate | Advisory gate record at proposed value, ≥3 sessions | Never-loosen items: cannot be drafted at all |
| **scoring** | component weights (0.35/0.20/…), catalyst-type weight table, sub-signal formulas | Replay: re-score recorded rows under scenario (`replay.score_row`), compare rank quality (Spearman vs outcomes) baseline-vs-variant | Parallel-logged variant score on new decisions, ≥3 sessions | CRITICAL-RULE structure untouchable |
| **feature** | wire `prior_count_30d`, macro-at-decision, retire a dead keyword, add a provider input | Attribution report shows the feature's outcome separation; leakage checklist | ≥5 sessions shadow-collection if input wasn't recorded historically (Class C) | Provider cost/keys are human decisions |
| **sizing** | conviction-tiered sizing within caps (`portfolio.conviction_sizing_whatif`), per-theme exposure trims | What-if cohort replay on realized trades; heat/concentration deltas | Advisory "would-have-sized" record alongside real sizing, ≥5 sessions | Hard caps ($1,900 / 2% / drawdown) are the outer bound, never touched |
| **strategy** | enable/disable/scope a generator or source, dedupe window tuning | Source scorecard + walk-forward backtest (`BACKTESTING_ARCHITECTURE` §5) | Full Class D ladder, ≥5 sessions | Watchlist scope additions are human-only |

### 3.3 Pipeline stages

1. **Detect** — analyzer bank findings cross a materiality floor (e.g.
   regret_flag true with passing sample gates for 2 consecutive weeks).
2. **Draft** — recommender writes the REC record with predicted effect and
   ranks it by *expected value of information* (effect size × confidence ×
   decision-cost asymmetry). Budget: at most **3 active recommendations**
   per weekly cycle (S6).
3. **Validate offline** — REC gets its pre-registered EXP; replay/backtest
   evidence generated by `research/run_experiment.py` and
   `scripts/replay_scenarios.py`. Sample gates must pass.
4. **Shadow** — diagnostics-only advisory records collected prospectively;
   shrinkage check (prospective effect ≥ 50% of offline effect).
5. **Review** — human verdict at checkpoint A4 (§6); the evidence pack is
   the REC record plus its validation reports, nothing verbal.
6. **Deploy** — a human (or a human-approved change) edits the config/code;
   the learner never does. Tests updated in the same change.
7. **Monitor** — P4 five-session watch; realized effect written back into
   the REC; auto-revert triggers per `RESEARCH_WORKFLOW` §6.
8. **Ledger update** — verdict + realized-vs-predicted effect recorded;
   recommender calibration score updated (§5 monthly).

---

## 4. Data inputs and outputs

### Inputs (all existing, all read-only)

| Input | Source | Feeds |
|---|---|---|
| Forward outcomes incl. rejected ideas | `signal_evaluations` | every detector's labels; regret analysis denominators |
| Per-gate observed/threshold traces | `execution_audit.payload_json._gates` | threshold detectors, near-miss mining |
| Realized trade returns + entry conviction | `trades` / `training_rows` view | ground-truth arbiter for proxy labels; sizing what-ifs |
| Idea features at decision time | `alpha_ideas`, `catalyst_events` | feature attribution, replay datasets |
| Replay scenario results | `alpha_lab/replay.py`, `scripts/replay_scenarios.py` | scoring recommendations |
| Attribution reports | `alpha_lab/attribution.py` (`feature_attribution_report`, `gate_regret_report`) | feature + threshold detectors |
| Outcome reports | `alpha_lab/outcomes.py` (`outcome_report`, `near_miss_report`) | weekly report core |
| Portfolio snapshots + what-ifs | `alpha_lab/portfolio.py` | sizing recommendations |
| Waterfall snapshots (per session) | `scripts/waterfall_snapshot.py` output | funnel drift, volume-band checks |
| Backtests / event studies | `catalyst_futures_reactions`, backtesting architecture | catalyst-weight and strategy recommendations |
| Human labels | `journal_entries` (`thesis_correct`, `mistake_tag`) | error-taxonomy detector; qualitative cross-check |
| Decision ledger (new) | `research/recommendations/` | meta-learning: recommender calibration |

### Outputs (all artifacts, none executable)

| Output | Location | Consumer |
|---|---|---|
| REC records + registry index | `research/recommendations/` | human review, ledger |
| Evidence packs (validation reports) | `research/validation/` | checkpoint A4 |
| Weekly Learning Report | `research/validation/` (untracked, like all generated reports) | Pak/Lex weekly read |
| Monthly Learning Retrospective | same | monthly review + handoff entry |
| Recommender calibration scorecard | inside the monthly retrospective | recommendation budget (S9) |
| Handoff entries at every status transition | `.ai/LEX_REVIEW_HANDOFF.md` | cross-agent memory |

---

## 5. Learning cadence

### Weekly cycle (weekend, after Friday's evaluation job)

1. **Data-quality preflight** (abort the cycle, not the standards, if it
   fails): label coverage ≥ 80% for the closed week, waterfall snapshot
   present for ≥ 4 of 5 sessions, no provider silently degraded to neutral
   (S5).
2. Run the analyzer bank: `outcome_report`, `feature_attribution_report`,
   `gate_regret_report`, portfolio snapshot, waterfall week-over-week delta.
3. Refresh detector states; draft/advance/expire REC records within budget.
4. Emit the **Weekly Learning Report**: what changed in outcomes this week,
   detector findings, active REC statuses, sample-gate progress bars for
   registered experiments ("EXP-0001: 143/200 evaluations"), and explicitly
   **"no recommendation"** when nothing clears the materiality floor —
   silence is a valid, reported result.
5. Append a handoff entry (audit entry if nothing actionable).

### Monthly cycle (first weekend of month)

1. Replay scenario sweep (`scripts/replay_scenarios.py`) over the trailing
   quarter: scoring-weight and catalyst-weight scenario grid vs baseline.
2. Calibration re-fit *proposal*: stated-confidence vs realized hit-rate by
   source/regime; drafts a scoring REC if reliably miscalibrated.
3. Sizing review: `conviction_sizing_whatif` cohort results vs actual sizing.
4. Proxy-label audit: excess-move hit rate vs `training_rows.realized_return`
   divergence (S4).
5. **Ledger retrospective**: every REC decided ≥ 1 month ago — predicted vs
   realized effect; deferred/rejected RECs re-scored against what actually
   happened (would it have helped?); recommender calibration score updated.
6. Decay check on previously promoted changes (re-run their EXP batteries).

### Quarterly

Full re-validation of all promoted experiments (already required by
`RESEARCH_WORKFLOW` §8); registry prune; roadmap review of this document.

---

## 6. Human approval checkpoints

| # | Checkpoint | Question the human answers | Without approval |
|---|---|---|---|
| A1 | Cycle output triage (weekly) | Which drafted RECs are worth pursuing? | RECs sit in `draft`; nothing else happens |
| A2 | Experiment registration | Is the hypothesis/decision-rule sound? (pre-registration review) | No offline validation runs |
| A3 | Shadow deployment | Approve the diagnostics-only advisory-record change (it *is* a code change, reviewed like any other) | No prospective evidence can be collected |
| A4 | Promotion decision | Adopt the change? One change, explicit scope, rollback trigger named | Nothing deploys — terminal state `rejected`/`deferred` |
| A5 | Post-monitoring sign-off | Did realized effect match? Keep or revert; ledger closes the record | Change reverts by default if triggers fire |

**Automation boundary (what the learner may do without any human):** read
telemetry; run analyzers; draft/rank/expire REC records; run replays and
offline batteries against recorded data; write reports and handoff audit
entries. **What it may never do, at any phase of this roadmap:** edit
thresholds, weights, config files, runtime code, or the DB schema; create,
arm, or modify scheduler/launchd jobs; place or approve any order; advance a
`never_loosen_conflict` record; merge or deploy anything, including its own
shadow instrumentation.

---

## 7. Failure modes and safeguards

| # | Failure mode | Mechanism | Safeguard |
|---|---|---|---|
| S1 | **Overfitting / data mining** — 20 detectors × weekly runs will find "signals" in noise | Multiple comparisons over a small N | Pre-registration before persuasion; sample gates (`CALIBRATION_PLAN` §2 floors); one primary metric per EXP; new hypotheses test on *later* windows; shrinkage check at shadow |
| S2 | **Regime shift** — a recommendation learned in one regime deployed into another | Non-stationary market | Session-stability + regime-split requirement in every battery; structural-break windowing (never straddle known breaks); monthly decay checks |
| S3 | **Selection-bias feedback loop** — the system learns mostly from ideas *it* let through | Gating truncates the outcome distribution | Rejected ideas keep `signal_evaluations` (the counterfactual denominator already exists); regret analysis is a first-class detector; acceptance-volume band monitored |
| S4 | **Goodhart on proxy labels** — optimizing excess-move hit rate away from realized P/L | Proxy ≠ objective | Monthly proxy-label audit vs `training_rows.realized_return`; any REC whose two labels disagree is frozen pending human read |
| S5 | **Silent data degradation** — provider outage makes inputs neutral; learner reads absence as signal | Absence-as-neutral scoring design | Data-quality preflight gates every cycle; coverage floors abort the cycle with a report, never a guess |
| S6 | **Recommendation flooding** — alert fatigue converts review into rubber-stamping | Human attention is the scarce resource | Budget of 3 active RECs; materiality floors; dedupe against open RECs; explicit "no recommendation" reporting |
| S7 | **Stale evidence** — a REC approved months after its window | Market moved on | `expires` field; advancing an expired REC requires regenerated evidence |
| S8 | **Compounding changes** — two promoted changes interact; attribution of effect becomes impossible | Simultaneous deployment | One change per decision (existing rule); ≥ 5 monitored sessions between promotions |
| S9 | **Learner miscalibration** — predicted effects systematically overstate | Optimism bias in search | Ledger tracks predicted-vs-realized; 2 consecutive reverted promotions → recommendation budget drops to 0 until a human re-opens it (learning-system kill switch) |
| S10 | **Narrative laundering** — LLM-analyst prose makes weak evidence persuasive | Rhetoric outrunning statistics | Evidence pack is machine-computed numbers; narrative fields are decoration; review checklist asks "which table supports this?" |
| S11 | **Boundary erosion** — learner code grows a write path over the years | Slow scope creep | Phase 0 import contracts already fail research→runtime imports; extend with a "learner writes only under research/" test when L1 lands; read-only DB connections enforced in code (`research.telemetry.connect_readonly`) |

Plus the standing rollback triggers from `RESEARCH_WORKFLOW` §6 P4
(acceptance band, never-loosen fire rates, drawdown events, order-volume
pressure) — those revert *changes*; S9 suspends the *learner*.

---

## 8. Implementation roadmap

Each phase is separately approvable; none changes live behavior. "Approval"
= explicit human sign-off recorded in the handoff log.

**L0 — Contracts and cycle skeleton** (research-only; no approval barriers
beyond normal review). REC schema + registry under
`research/recommendations/`; weekly-report generator that composes the
existing analyzers (`outcome_report`, `feature_attribution_report`,
`gate_regret_report`, portfolio snapshot, waterfall delta) into one Markdown
report, run manually. Ledger file format. Exit: two consecutive manual
weekly reports produced; zero runtime diffs.

**L1 — Detector formalization + boundary test** (research-only). Materiality
floors and budget/dedupe/expiry logic; the four core detectors (gate regret,
calibration drift, attribution decay, scorecard shift) emitting draft RECs;
the S11 write-path boundary test added to the Phase 0 rails. Exit: a full
cycle produces ranked drafts with evidence links, still manually triggered.

**L2 — Shadow instrumentation generalization** (**approval required** — it
touches runtime telemetry emission, diagnostics-only). Generalize the
advisory-gate mechanism so any registered EXP can attach a shadow threshold
or parallel-logged variant score (`enforced:false` records, exactly like the
dry-run alpha gate today). Exit: one REC completes offline→shadow with the
shrinkage check computed automatically.

**L3 — Ledger + meta-learning** (research-only). Decision ledger wired into
monthly retrospective; predicted-vs-realized scoring; S9 budget mechanics.
Exit: first monthly retrospective covering ≥ 3 decided RECs.

**L4 — Sizing and strategy recommenders** (research-only analysis;
prerequisites are behavioral: exit management and richer fill data, each
separately human-approved per `CALIBRATION_PLAN` §6). What-if sizing
cohorts and walk-forward strategy backtests become first-class detectors.
Exit: first sizing REC with full evidence pack through checkpoint A4
(whatever the verdict).

**L5 — Optional model-based scoring proposals** (design gate: revisit this
document first). ML models behind the `ModelPort` seam
(`ARCHITECTURE` §5) as *scoring-recommendation generators* — a model's
output enters the composite only as a REC through the full ladder, with the
explainability contract (sub-signal breakdown) non-negotiable. If a model
cannot explain its score, it cannot be recommended, regardless of backtest
performance.

Cadence for the roadmap itself: reassess after every phase; L2 is the only
phase before L5 that touches runtime, and it is diagnostics-only. Nothing
here — at any phase — arms paper mode, changes an execution path, or gives
the learner deployment authority. That property is permanent, not
transitional.
