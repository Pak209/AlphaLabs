# Which config file governs what (documentation only)

Written for Phase 0 of `docs/CODEBASE_HEALTH_AUDIT.md` (debt item D5). This
file changes NOTHING — it records the current state so nobody edits the wrong
file. The rename/cleanup itself is a P3, approval-gated change because it
touches launch scripts and live risk limits.

## The three `config.example.json` files

| File | Role today | Governs |
|---|---|---|
| `alpha_lab/config.example.json` | **LIVE risk config**, despite the name | `AlphaLabService` default (`DEFAULT_RISK_CONFIG`): min_confidence 0.75, per-trade $1,900 / 2% equity, 10 trades/day, 20 open positions, ~31-ticker watchlist, 4%/8% stop/target, 3% drawdown, `allow_short: true`, plus the `crypto_risk` profile ($250, 3/day, 2% drawdown) and scheduler time slots |
| `config.example.json` (repo root) | **Stale template** — diverges from the live file | Nothing at runtime. Differences that will bite a copier: `max_open_positions` 3 (vs 20), `max_position_size_usd` 500 (vs 1900), `allow_short` false (vs true), 9-ticker watchlist, no `crypto_risk` block |
| `paper_trader/config.example.json` | Template for the legacy standalone `paper_trader` CLI stack (D6) | Only `paper_trader/main.py`-style entry points when pointed at it explicitly |

## Rules until the P3 rename lands

1. To change live paper-trading risk limits: edit **`alpha_lab/config.example.json`**
   — and treat it as a behavior change (calibration protocol + human approval),
   because it is one.
2. Never copy the root `config.example.json` over the alpha_lab one; they have
   diverged (see table).
3. The eventual fix (P3): rename the live file to something honest
   (e.g. `alpha_lab/risk.paper.json`), keep genuinely-example files as
   documentation, update `DEFAULT_RISK_CONFIG` and launch scripts in the same
   approved change.

## Interpreter & dependencies (Phase 0 additions)

- `requirements.txt` — intent (floor versions), used for research/dev installs.
- `requirements.lock` — exact pins from the tested venv (`pip freeze`),
  regenerated deliberately, used to rebuild the service venv reproducibly:
  `pip install -r requirements.lock`.
- Interpreter: venv currently Python 3.9.6 (EOL — flagged by
  `scripts/diagnose_trading_pipeline.py`; migration is P3).
