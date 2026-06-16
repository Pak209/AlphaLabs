# AlphaLab Trading Pipeline Audit

Generated: 2026-06-15

## Current Pipeline

AlphaLab creates normalized ideas from manual inputs, catalyst scans, daily briefs, BTC after-hours scans, or trending-stock scans. Ideas carry `strategy_tags`/`strategies`; if no strategy tag is provided, AlphaLab now assigns a fallback label from the idea theme/source, or `untagged`.

Trade execution starts in `AlphaLabService.place_trade()`. It runs `run_decision()`, which evaluates the signal through the risk engine, writes a `decision_logs` row, and returns an order payload only if the setup passes guardrails.

Execution endpoints and jobs:

- `POST /api/ideas/{id}/dry-run-trade` runs `place_trade(..., dry_run=True)`.
- `POST /api/ideas/{id}/paper-trade` runs `place_trade(..., dry_run=False)`.
- `POST /api/strategies/test-trending` can dry-run or paper-test current strategy candidates.
- `POST /api/ideas/import-and-test` accepts `execution_mode=dry_run|paper`; `paper` requires `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true`.
- Scheduler jobs call catalyst/daily-brief/crypto polling with dry-run unless `ALPHALAB_SCHEDULER_MODE=paper`.

## Alpaca Mode And Safety

Alpaca credentials are read from:

- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_PAPER_BASE_URL`

The Alpaca client refuses to initialize unless `ALPACA_PAPER_BASE_URL` is exactly `https://paper-api.alpaca.markets`. Live endpoints are rejected before order placement.

Dry-run mode does not call `broker.place_order()`. It writes the decision/trade/order records with a synthetic `{"dry_run": true, "message": "No order placed"}` response.

Paper mode calls Alpaca only after risk checks and approval checks pass. Submitted paper order responses are stored in both `orders.response_json` and `execution_audit.response_json`; the Alpaca order id is stored in `orders.alpaca_order_id` and `execution_audit.alpaca_order_id`.

## Persistence

Primary tables:

- `alpha_ideas`: normalized signal ideas.
- `idea_strategies`: many-to-many link from ideas to strategy labels.
- `decision_logs`: full serialized risk decision and order payload.
- `trades`: dry-run and paper trade records, including realized/unrealized P/L fields.
- `orders`: order request and Alpaca response payloads.
- `execution_audit`: every attempt, including rejected/skipped/broker-error cases.
- `positions`: latest synced Alpaca paper positions.

Rejected, failed, blocked, skipped, and approval-gated attempts are written to `execution_audit` even when no trade row is created.

## What Was Broken

- The Strategies page displayed only a thin win-rate line, so it could look inactive even when paper orders and dry-runs existed.
- Historical trades could exist without a linked strategy label if the source idea had no strategies.
- Strategy metrics did not expose open/closed counts, dry-run versus paper counts, realized/unrealized P/L, confidence, or recent trades.
- Execution audit rows did not include explicit execution context such as dry-run status and Alpaca base URL.

## What Was Fixed

- Strategy labels are now guaranteed for new ideas, with a safe `untagged` fallback.
- Existing trades missing strategy labels are backfilled to `untagged`.
- Strategy stats now include total trades, paper trades, dry-run trades, open/closed trades, win rate, realized P/L, unrealized P/L, average confidence, and recent trades.
- Execution audit payload/response JSON now includes `_execution` context with dry-run status and Alpaca paper endpoint status.
- The Strategies page now explains whether there are no trades, unlinked trades, dry-run-only activity, or unavailable metrics.
- Added `scripts/diagnose_trading_pipeline.py`.

## How To Check

Run:

```bash
./.venv/bin/python scripts/diagnose_trading_pipeline.py
```

Run the dry-run test suite:

```bash
./.venv/bin/python -m pytest alpha_lab/tests paper_trader/tests -q
```

Run a dry-run sample without placing an Alpaca order:

```bash
npm run paper:dry-run
```

Check the Strategies API:

```bash
curl -s http://127.0.0.1:8787/api/stats/strategies
```

Check recent execution attempts:

```bash
curl -s http://127.0.0.1:8787/api/execution-audit
```

Optional paper test order remains intentionally manual. Only use it if you explicitly want a tiny Alpaca paper order and your `.env` is already configured for paper trading:

```bash
ALPHALABS_ALLOW_PAPER_TEST_ORDER=1 ./.venv/bin/python scripts/diagnose_trading_pipeline.py
```

Without `ALPHALABS_ALLOW_PAPER_TEST_ORDER=1`, the diagnostic reports state and does not place an order. With that flag, it uses a temporary risk config capped at a tiny notional and still refuses to run unless `ALPACA_PAPER_BASE_URL` is the Alpaca paper endpoint.
