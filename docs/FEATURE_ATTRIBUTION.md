# AlphaLabs feature attribution

Built 2026-07-04, on top of the replay framework (`docs/REPLAY_FRAMEWORK.md`).
Purpose: measure which scoring inputs actually correlate with better recorded
outcomes, so composite weights and new features are chosen from evidence.
Strictly read-only diagnostics — no live scoring, threshold, gate, approval,
or paper-safety change.

```
python3 scripts/feature_attribution.py     # prints report, writes JSON to
                                           # alpha_lab/data/attribution/
```

## Methodology

The attribution dataset is the replay dataset (one row per stored idea, with
the bias-signed forward move from `signal_evaluations` as the outcome),
enriched with the baseline replay scores — so every feature is measured
exactly as the live engine computes it, on the same fingerprinted population.

Five analyses, all dependency-free and sized for small-N honesty:

1. **Rank correlation (numeric features).** Tie-aware Spearman ρ between each
   feature and the directional forward move. Rank-based, so it is robust to
   outliers and does not assume linearity — appropriate for 0–100 scores with
   step functions inside them.
2. **Median-split separation (numeric features).** Top half vs bottom half of
   each feature: hit-rate delta and average-move delta. Blunter than ρ but
   readable at any sample size, and the two agreeing is a stronger signal
   than either alone.
3. **Dead-input detection.** A feature whose spread is ~zero across the
   dataset cannot rank anything; it is reported as a *dead input* instead of
   a correlation. This is a data-wiring detector: `sub_novelty` (constant 100
   while `prior_count_30d` is unwired) and `component_macro` (decision-time
   defaults) surface here by design.
4. **Categorical level analysis.** Outcome stats per level of catalyst_type,
   source, regime, bias, timeframe, tier, and idea status — levels below 3
   outcomes are pooled, best-vs-worst average-move spread reported.
5. **Selected vs rejected.** Per-feature median gap between the population the
   current bars select and the one they reject, next to the outcome stats of
   both groups. Read together with the importance ranking:
   - large selection gap + weak outcome correlation → the bar leans on a
     feature that does not predict — **over-weighted**;
   - small selection gap + strong outcome correlation → predictive signal the
     bar barely uses — **under-used**.
6. **Gate regret.** Structured gate traces (`execution_audit.payload_json._gates`)
   joined to outcomes: per first-failed gate, how many rejected ideas went on
   to be directional winners (`regret_rate`, `avg_missed_move_pct`). One vote
   per idea (latest attempt). Legacy free-text rows are counted and skipped —
   they carry no per-gate values.

## Report contents

`feature_attribution_report()` returns (and the CLI prints):

- `importance_ranking` — live numeric features ordered by |ρ| (median-split
  delta as tiebreak), each with n;
- `dead_inputs` — unwired features (fix the wiring, not the weight);
- `numeric_features` / `categorical_features` — full per-feature detail;
- `selected_vs_rejected` — population sizes, outcomes, per-feature gaps;
- `gate_regret` — per-gate rejection counts, regret rate, average missed move;
- `fingerprint` + `caveats` — comparability and small-N warnings.

## Interpretation rules

- **n < 30 outcomes → directional only.** The CLI warns; the calibration plan's
  sample floors apply to any decision taken from this report.
- **Correlation is not a weight.** A strong ρ nominates a feature for a replay
  scenario (`scripts/replay_scenarios.py`), which then shows what selecting on
  it would have done. Attribution nominates; replay quantifies; the calibration
  protocol (shadow → approval) promotes.
- **Dead inputs are wiring work, not weight work.** Raising the weight of a
  constant feature changes nothing; wiring its data source (Phase-2 items in
  `docs/ALPHA_GENERATION_AUDIT.md`) is the actual fix.
- **Emission bias.** Only emitted ideas are visible; features that would have
  rescued radar-rejected candidates cannot appear here.
- **Confidence leaks into the outcome score.** `early_detection_score` embeds
  confidence by construction (20 points), so attribution deliberately measures
  against the raw directional move, never against the detection score.

## Files

- `alpha_lab/attribution.py` — dataset enrichment, five analyses, report
  assembly (pure functions over the replay layer).
- `scripts/feature_attribution.py` — CLI + JSON report writer.
- `alpha_lab/tests/test_attribution.py` — correctness, dead-input flags,
  small-group pooling, gate regret, determinism, read-only verification.
