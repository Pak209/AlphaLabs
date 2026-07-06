# Experiment registry

One JSON spec per experiment, pre-registered **before** looking at outcomes.
Copy `TEMPLATE.json`, take the next `EXP-NNNN` id, fill every field, and add a
row here in the same change. Specs are append-only once `status` leaves
`registered`: record status transitions by editing `status` and appending to
this index — never rewrite a hypothesis or decision rule after data has been
seen (that invalidates the pre-registration; open a new experiment instead).

Statuses: `registered → running → reported → promoted | rejected | closed`
(plus `sample` for synthetic fixtures).

| id | class | status | title | spec |
|---|---|---|---|---|
| EXP-0000 | A | sample | Synthetic framework demonstration (fabricated data) | [spec](EXP-0000-synthetic-sample.json) |
| EXP-0001 | A | registered | Does the 0.75 execution confidence bar sit on a real outcome step? | [spec](EXP-0001-confidence-threshold-step.json) |

Experiment classes (see `docs/RESEARCH_WORKFLOW.md` §4):

- **A** — threshold calibration of an existing gate (governed by `docs/CALIBRATION_PLAN.md`)
- **B** — scoring-model change (weights, sub-signal formulas; replayable offline)
- **C** — new signal / feature / data source (needs a shadow phase; no historical inputs)
- **D** — new idea generator or strategy (full promotion ladder including paper stage)
