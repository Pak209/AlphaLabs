# Alpha Validation Platform

AlphaLabs now treats every stored idea as a signal to evaluate, even when no
trade is placed. This keeps the first phase focused on signal quality and early
detection instead of P/L.

## Current Pipeline

1. `POST /api/ideas` normalizes and stores the signal in `alpha_ideas`.
2. The service stamps the current market regime and source tags on the signal.
3. A matching row is created in `signal_evaluations` with:
   - ticker, source, direction, confidence, catalyst, regime, generated time
   - alert price when a real configured quote provider is available
   - a provisional grade based on confidence and catalyst presence
4. `POST /api/signals/evaluate` rechecks current quote data and updates:
   - price after alert
   - move after alert
   - early detection score
   - final grade
5. `GET /api/performance/report` powers the Alpha Report Card. It prefers signal
   validation scores and falls back to trade returns for older rows.

The evaluator does not place orders. Paper trading remains controlled by the
existing dry-run and paper-trading safety flags.

## Scoring

Early Detection Score is a 0-100 signal-quality score:

- 40 points when price moves in the signal direction.
- Up to 40 points for the size of the directional move after alert.
- Up to 20 points from original signal confidence.

Grades map from score:

- A: 85+
- B: 70-84.9
- C: 55-69.9
- D: 40-54.9
- F: below 40

Benchmark-vs-market scoring is not fabricated. Until a configured benchmark
feed is added, `benchmark_move_pct` remains empty and the payload notes
`benchmark_status: unavailable`.

## How To Check

Run signal evaluation without trading:

```bash
.venv/bin/python -m pytest alpha_lab/tests/test_performance.py -q
```

Call the local API:

```bash
curl -s -X POST "http://127.0.0.1:8787/api/signals/evaluate?limit=100"
curl -s "http://127.0.0.1:8787/api/signals/evaluations?limit=20"
curl -s "http://127.0.0.1:8787/api/performance/report"
```

Interpretation:

- `status=provisional`: signal is recorded, but no later price was available yet.
- `status=evaluated`: signal has an early-detection score and final grade.
- `status=price_unavailable`: configured quote providers did not return a usable
  live price; no fake price was used.

## Remaining Work

- Add a real benchmark source such as SPY/QQQ snapshot at alert and evaluation
  time so AlphaLabs can score move-vs-market explicitly.
- Add scheduled daily and weekend summary jobs once the preferred delivery
  channel is decided.
- Keep collecting at least 50-100 evaluated signals before treating trade or
  strategy performance metrics as statistically meaningful.
