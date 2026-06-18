# Manual Paper Validation Checklist

Defines what "manual paper validation passed" means before AlphaLabs may move
from `dry_run` toward any automated paper trading. This is the gate that must
pass first; until it does, the old-Mac scheduler stays `dry_run`/disarmed and no
automation paper flag is set. No real-money trading at any point.

The first validation is deliberately conservative: **one** human-selected
**equity** idea, placed manually against the Alpaca **paper** endpoint, with the
scheduler still in `dry_run` and automation paper trades off.

## Pre-Conditions (must all hold before the test)

### Required environment state
- `ALPHALAB_SCHEDULER_MODE=dry_run` (scheduler places nothing on its own).
- `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` unset or not `true` (automation guard
  disarmed — confirms the scheduler cannot place this or any order).
- `ALPHALAB_ALLOW_MANUAL_PAPER_TRADES=true` (manual path is the only enabled
  execution route).
- `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` (human approval enforced for
  analyst-assisted / crypto ideas; see Phase 2 recommendation).
- `ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets` (paper-only; the code
  asserts this and refuses live endpoints).
- `.env` permissions `600`, present, not modified for the test beyond the gates
  above.
- `safe_stabilization_mode: true` from `scheduler_safety_status` /
  `./ops safety-status` at the moment of the test.

### Required API auth state
- Alpaca **paper** credentials present and reachable (`./ops check alpaca` →
  HTTP 200). No live Alpaca key in use.
- Price source reachable for the chosen ticker: Polygon (if `POLYGON_API_KEY`
  set) or the Yahoo keyless fallback (`YAHOO_PRICE_ENABLED=true`) returns a
  non-null validation price, so entry/stop/target are populated (not blank).
- SEC EDGAR reachable if the idea's catalyst depends on it (`./ops check sec`).

### Scheduler state
- Old-Mac scheduler + dashboard LaunchAgents `running`, fresh heartbeat, single
  shared DB (resolver == heartbeat == API db_path — the `./ops health` same-DB
  proof passes).
- Scheduler remains `dry_run` for the entire test. The manual order is placed by
  a human via the manual path, **not** by any scheduler job.

### Approval policy
- `ALPHALAB_REQUIRE_PAPER_APPROVAL=true`. The idea must be explicitly
  **approved** in the Approvals page before the manual paper order is allowed to
  reach Alpaca (for analyst-assisted or crypto ideas). Rejected/expired ideas
  must never execute.

### Allowed asset class for first test
- **Equity only.** No crypto, no options for the first validation.

### Allowed order size / risk (per current `config.example.json`)
- Single order, equity: `max_position_size_usd ≤ 1900` and
  `max_equity_pct_per_trade ≤ 0.02`.
- `min_confidence ≥ 0.75`, ticker on the equity `approved_tickers` watchlist.
- One trade only; well within `max_trades_per_day=10` and
  `max_open_positions=20`. Prefer the smallest meaningful size for the first run.
- Standard guardrails must still apply: market-open, watchlist, confidence,
  duplicate-position, max-trades/day, max-open-positions, drawdown.

## Execution (the single manual test)
1. Confirm all pre-conditions above (`./ops safety-status` + `./ops health`).
2. Manually select ONE equity idea on the approved watchlist; confirm its
   entry/stop/target are populated from a live price.
3. Approve the idea in the Approvals page (human gate).
4. Place the paper order manually (manual paper path), market hours only.
5. Observe the order on the Alpaca **paper** account and in the dashboard.

## Required records after the test

### Logs / audit records
- An execution-audit entry in the Paper / Dry-Run Log showing the submitted
  Alpaca **paper** order (action = submitted), the resolved order payload, and
  that it passed every risk/approval check (no approval-block, no risk-block).
- `alpha_lab/data/audit.jsonl` reflects the attempt.
- launchd scheduler logs show it stayed `dry_run` and did not place the order.

### Database records
- A `trades` row linked to the originating idea id.
- The idea's `approval_status = approved` and status transitioned to executed.
- The order is attributable end-to-end: idea → explanation → approval → trade →
  performance linkage on the Performance page (entry price, qty, P/L tracking).
- Heartbeat + same-DB proof still consistent after the test (no split-brain).

## Pass / fail criteria

**PASS** (all must be true):
- Exactly one equity paper order placed, via the manual path, on the Alpaca
  paper endpoint.
- The scheduler placed nothing and stayed `dry_run`/disarmed throughout.
- Human approval was required and recorded before execution.
- Entry/stop/target were populated from a live price (not blank).
- Audit log + `trades` row + Performance linkage all present and consistent.
- Same-DB proof intact; no errors, no live-endpoint contact.

**FAIL** (any one):
- Order routed to (or attempted against) a live endpoint, or
  `ALPACA_PAPER_BASE_URL` not paper.
- The scheduler placed any order, or `safe_stabilization_mode` was not `true`.
- Order placed without the required approval, or a rejected/expired idea
  executed.
- Blank/None validation price, or risk-guard bypass.
- DB split-brain / heartbeat-path mismatch, or missing audit/trade records.

## Rollback / stop conditions
- Stop immediately and do not retry if any FAIL condition appears.
- Do not flip `ALPHALAB_SCHEDULER_MODE=paper` or arm
  `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` to "fix" a failed manual test.
- If a bad order lands on the paper account, cancel/flatten it on the paper
  account only; investigate via the audit log before any further attempt.
- Leave the runner in `dry_run`/disarmed after the test regardless of outcome;
  automation may only be considered after a clean PASS and explicit human
  decision.

## Why one clean PASS is the gate
The position-concurrency caps were intentionally widened (equity 20 / crypto 25)
for paper-test capacity, so exposure is now bounded by the *other* gates
(scheduler mode, automation flag, per-day count, position size, approval). A
single, fully-attributable manual paper trade proves the entry→approval→
execution→audit→performance chain end-to-end before any of those gates are
loosened toward automation.
