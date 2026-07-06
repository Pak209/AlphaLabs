# AlphaLabs offline replay framework

Built 2026-07-04 (Phase 1, item 1 of `docs/ALPHA_GENERATION_AUDIT.md`).
Purpose: make every future scoring change **measurable before it reaches paper
trading**. A proposed weight table, threshold, or feature is expressed as a
*scenario*, re-scored over stored history, and judged against outcomes the
platform already recorded — entirely offline.

Strictly read-only: the replay opens the DB with SELECTs only; it never
creates ideas, decisions, orders, trades, or approvals, and it changes nothing
about live scoring. Verified by test
(`test_replay_is_deterministic_and_read_only`).

## Architecture

```
stored history                    replay (offline)                evidence
──────────────                    ────────────────                ────────
alpha_ideas ──┐                   ReplayScenario("baseline")  ┐
signal_evalu- ├─ build_replay_ ─► ReplayScenario("candidate") ├─► metrics per
  ations      │    dataset()      ...                         │   scenario +
trades (P/L) ─┘   (fingerprinted)   └── score_row() reuses    │   baseline
                                        the LIVE engine with  │   comparison
                                        override params       ┘   (JSON report)
```

- **`alpha_lab/replay.py`** — dataset builder, `ReplayScenario`, per-row
  scoring, metrics, baseline comparison, report assembly.
- **`scripts/replay_scenarios.py`** — CLI; prints the comparison table and
  writes a timestamped JSON report to `alpha_lab/data/replay/`.
- **Engine parameterization** — `score_catalyst(..., type_weights=)` and
  `composite(..., weights=, catalyst_confirm_min=, price_volume_confirm_min=)`
  accept overrides whose `None` defaults reproduce the live constants exactly
  (regression-tested). The replay therefore reuses the live formulas — they
  cannot drift apart — and the no-override scenario **is** the live engine.
- **Safety structure is not parameterizable.** The confirmation gate's
  *existence*, watchlist ceiling, and macro/catalyst floors cannot be disabled
  by any scenario; scenarios explore weights, thresholds, and inputs only.

## Dataset

One row per stored idea, joined to its recorded outcome:

| Field | Source | Notes |
|---|---|---|
| idea features | `alpha_ideas` | ticker, bias, confidence, catalyst_type/score, source, regime |
| forward move | `signal_evaluations.move_after_pct` | only rows with `status='evaluated'` count as outcomes |
| `directional_move_pct` | derived | move signed toward the idea's bias (bearish −5% market move = +5% directional) |
| `hit` | derived | directional move > 0 |
| stored PV / composite / realized P/L | `trades` aggregate | what the live engine saw at entry, when a trade exists |

Every dataset carries a **fingerprint** (row count, evaluated count, time
window, id hash). Comparing results across different fingerprints raises —
metrics are only comparable on identical datasets.

## Scenarios

JSON-loadable knobs (see `ReplayScenario`):

```json
[{"name": "financing-45",
  "description": "What if financing catalysts scored 45 instead of 35?",
  "catalyst_type_weights": {"financing": 45},
  "composite_weights": {"catalyst": 0.40, "price_volume": 0.20, "narrative": 0.10,
                         "options": 0.15, "institutional": 0.10, "macro": 0.05},
  "catalyst_confirm_min": 40,
  "price_volume_confirm_min": 55,
  "paper_composite_min": 70,
  "min_confidence": 0.75}]
```

Unknown fields are rejected (typo protection). Python-defined scenarios may
additionally set a **`feature_hook`** — `callable(row) -> dict` supplying
`catalyst_inputs`, `price_volume_inputs`, `options`, or `institutional` per
row. This is how a *future feature* (event-anchored move, prior_count_30d
novelty, options-flow backfill…) is evaluated before it exists in live code:
compute the candidate inputs offline, feed them through the hook, compare.

## Metrics (per scenario)

| Metric | Definition | Question it answers |
|---|---|---|
| `n_selected`, `selection_rate` | rows with composite ≥ `paper_composite_min` AND confidence ≥ `min_confidence` | how much would trade volume change? |
| `selected` / `rejected` outcome stats | hit rate, avg/median/p25/p75 directional move | do selected ideas actually outperform? |
| `selection_edge_pct` | selected avg move − rejected avg move | is selection adding value at all? |
| `rank_correlation_composite_vs_move` | Spearman ρ (tie-aware, n ≥ 3) | does a higher composite mean a better outcome? |
| `calibration_bands` | outcomes per fixed composite band (0–45, 45–60, 60–70, 70–80, 80+) | is the 70 bar sitting at a real step? (calibration plan §4 threshold-step test) |
| `pv_source_counts` | feature_hook / stored_trade_entry / neutral_reconstruction | how much of the dataset had real PV data? |
| vs baseline | newly_selected / newly_dropped with their outcomes | exactly which trades a change adds/removes, and whether they were winners |

## Usage

```bash
cd ~/AlphaLab
set -a; source .env; set +a

# Baseline health: selection rate, edge, rank correlation, calibration bands
python3 scripts/replay_scenarios.py

# Candidate evaluation
python3 scripts/replay_scenarios.py --scenarios my_scenarios.json
```

The console warns when fewer than 30 evaluated outcomes exist (the calibration
plan's minimum); reports still write so early runs document the growing sample.

## Workflow tie-in (calibration plan §2)

A Phase-2 behavior proposal must attach a replay report showing, on the same
fingerprint: baseline vs candidate selection counts, the outcome stats of
newly-selected and newly-dropped sets, and the calibration bands. Then the
change goes through shadow (advisory gate record) → approval → single change.
Replay evidence complements — never replaces — the shadow phase, because
replay sees only ideas that were *stored*, not signals the radar never emitted.

## Known limitations (report honestly alongside results)

1. **Emission bias** — the dataset contains only ideas that passed radar
   emission; scenarios that would loosen radar candidacy cannot be evaluated
   from idea history (that needs `catalyst_events` replay — future extension).
2. **PV reconstruction** — rows without a stored trade PV score replay with a
   neutral PV component; `pv_source_counts` quantifies the gap. It shrinks as
   sessions run with `POLYGON_API_KEY` configured.
3. **Point-in-time drift** — narrative themes/phases and macro inputs are
   *current* tables, not historical snapshots; catalyst_type/score are stored
   point-in-time and safe.
4. **One-horizon outcomes** — `move_after_pct` reflects the evaluation job's
   timing, not a fixed horizon; treat cross-timeframe comparisons carefully.
5. **Small N** — with today's ~dozens of evaluated ideas, use replay to rank
   scenarios directionally, not to certify them; the ≥ 30-outcome floor from
   the calibration plan applies to any decision.
