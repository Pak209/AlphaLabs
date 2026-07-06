# research/ — offline quantitative research framework

Read-only analysis of the decision telemetry production already collects.
The workflow, promotion ladder, and governance live in
[docs/RESEARCH_WORKFLOW.md](../docs/RESEARCH_WORKFLOW.md); threshold-tuning
rules live in [docs/CALIBRATION_PLAN.md](../docs/CALIBRATION_PLAN.md). This
package never creates ideas, decisions, orders, or trades — every database
connection is opened in SQLite read-only mode and a write through it raises.

## Layout

```
research/
  telemetry.py        # read-only loaders → analysis frames
  metrics.py          # standard metric battery (stdlib only)
  run_experiment.py   # spec runner → validation report (md + json)
  experiments/        # pre-registered specs + registry index (README.md)
  validation/         # generated reports (gitignored except SAMPLE-*)
  tests/              # synthetic-fixture test suite
```

## Frames

- **`idea_outcomes`** — one row per `alpha_ideas` row joined to its
  `signal_evaluations` labels. Includes rejected ideas (they keep their
  evaluations), with direction-signed labels:
  `signed_move_pct`, `excess_move_pct` (signed move minus signed benchmark),
  `hit` (excess > 0), plus `session`, `grade`, `evaluated`.
- **`decision_outcomes`** — one row per *structured* `execution_audit`
  attempt (rows carrying `_gates`), with per-gate observed/threshold/near-miss
  detail, `first_failed_gate`, `accepted`, and the same outcome labels joined
  via `idea_id`. Legacy free-text rows are excluded by design.

## Running an experiment

```bash
# 1. Register a spec (copy the template, take the next EXP id, fill EVERY
#    field before looking at outcomes, add it to experiments/README.md)
cp research/experiments/TEMPLATE.json research/experiments/EXP-0002-my-question.json

# 2. Run it (read-only; production DB path resolves like the app does,
#    or pass --db explicitly)
.venv/bin/python3 -m research.run_experiment \
    research/experiments/EXP-0002-my-question.json

# 3. Read the verdict
#    INSUFFICIENT_DATA  → a sample gate failed; collect more sessions, done.
#    READY_FOR_REVIEW   → apply the spec's pre-registered decision rule and
#                         the promotion criteria (RESEARCH_WORKFLOW §6).
```

Reports land in `research/validation/EXP-NNNN-<utc-stamp>.{md,json}`.
Reports generated from the production database are operational data and stay
out of git; `SAMPLE-EXP-0000.*` (fabricated fixture data) shows the format.

## Analyses available in specs

`summary` · `threshold_step` (with `proposed_thresholds` simulated pass
rates) · `buckets` (lift + Spearman) · `calibration` ·
`session_stability` · `regret` (requires a `gate` name; uses first-failed
attribution against the decision frame).

## Guarantees and limits

- **Read-only:** `telemetry.connect_readonly` uses `file:...?mode=ro`; it
  cannot create or modify the database. The runner writes only report files.
- **No interpretation:** the runner's only verdicts are INSUFFICIENT_DATA and
  READY_FOR_REVIEW. Promotion is a human decision recorded in the handoff log.
- **Structured rows only:** distributional claims never use legacy free-text
  audit rows; populations that straddle the 2026-07-04 structural breaks are
  invalid windows.
- **Never-loosen list:** no experiment outcome authorizes touching the
  controls listed in CALIBRATION_PLAN — evidence produces *proposals* for
  explicit human approval, at most.

## Tests

```bash
.venv/bin/python3 -m pytest research/tests/ -q
```

The suite builds a synthetic database from the real production schema
(`alpha_lab.database.init_db`) and verifies loader semantics (legacy-row
exclusion, bearish sign handling, near-miss flags), metric math (Wilson
intervals, band partitions, regret grouping), report generation, and the
read-only guarantee. It never touches the production database.
