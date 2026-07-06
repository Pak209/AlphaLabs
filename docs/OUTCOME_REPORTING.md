# AlphaLabs outcome reporting

Built 2026-07-04, completing the diagnostics loop:
**attribution nominates → replay quantifies → calibration promotes → outcomes verify.**
Where attribution asks *which inputs predict* and replay asks *what a change
would have selected*, this layer reports what the pipeline **actually did** and
what happened next. Strictly read-only — no live behavior, thresholds, gates,
approvals, or paper-mode changes.

```
python3 scripts/outcome_report.py     # prints tables, writes JSON to
                                      # alpha_lab/data/outcomes/
```

## Definitions

| Term | Meaning |
|---|---|
| outcome | bias-signed forward move from `signal_evaluations` (evaluated rows only) — same definition as replay/attribution, so numbers agree across all three reports |
| accepted | `idea_status` ∈ {accepted, tested, traded} — the decision engine accepted it (dry-run or paper) |
| rejected | `idea_status` = rejected |
| near-miss | latest structured attempt failed a numeric `>=` gate by ≤ 10% of its threshold (same rule as the rejection waterfall) |

## Report sections

1. **Overall** — idea counts by status, hit rate, move distribution.
2. **Score-band tables** — outcomes per replayed-composite band (0–45, 45–60,
   60–70, 70–80, 80+; the calibration plan's threshold-step test) and per
   confidence band (<0.6, 0.6–0.7, 0.7–0.75, 0.75–0.85, 0.85+ — the 0.7–0.75
   band is the near-miss zone for the execution bar).
3. **Source / catalyst-type / bias breakdowns** — which generators and event
   classes actually make money on paper, sorted by average move.
4. **Accepted vs rejected** — outcome stats for both populations plus the
   `acceptance_edge_pct` (accepted avg move − rejected avg move). This is the
   single number that says whether the pipeline's selectivity adds value:
   persistently ≤ 0 means the gates are filtering the wrong things.
5. **Gate-result table** — outcomes grouped by first failed gate, with the
   accepted population as the reference row: *what kind of performance is each
   gate rejecting?*
6. **Near-miss performance** — the calibration plan's regret analysis, per
   gate: ideas that *barely* failed, their outcomes vs the accepted reference,
   and an explicit verdict line ("strict at the margin" vs "placement looks
   right"), with example ideas and their shortfalls.

## How this feeds the calibration protocol

- The **near-miss section is the §2 evidence pack's regret analysis**: a
  proposal to move a threshold cites this table on ≥ 30 outcomes.
- The **score-band tables answer §4 metric 1** (threshold-step test): a
  well-placed bar shows a visible outcome step across its band boundary.
- The **acceptance edge is §4's headline selectivity metric**, now computed
  continuously instead of ad hoc.
- Run cadence: alongside `waterfall_snapshot.py` after each session; the JSON
  reports in `alpha_lab/data/outcomes/` form the session-over-session series.

## Caveats

- Outcomes exist only for evaluated ideas; the report shows `n_with_outcome`
  everywhere rather than hiding coverage.
- Below 30 outcomes the CLI warns and every comparison is directional.
- Gate-result and near-miss sections cover structured-trace ideas only
  (post-telemetry); legacy free-text rejections have no per-gate values.
- Emission bias applies: only emitted ideas are visible.

## Files

- `alpha_lab/outcomes.py` — row builder (replay dataset + pipeline status +
  latest structured gate trace) and report sections.
- `scripts/outcome_report.py` — CLI + JSON writer.
- `alpha_lab/tests/test_outcomes.py` — seeded accepted/hard-reject/near-miss
  populations, verdict logic, banding, determinism, read-only verification.
