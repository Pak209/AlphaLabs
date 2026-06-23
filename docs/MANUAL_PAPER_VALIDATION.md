# Market-Hours Manual Paper Validation Runbook

Use this once, during regular equity market hours, to validate one
human-approved, analyst-assisted equity idea against Alpaca **paper**. This is a
manual validation only: do not enable automation, deploy code, change scheduler
mode, or contact a live-trading endpoint.

## 1. Pre-market readiness

From the AlphaLabs checkout, before the market opens:

```bash
./ops paper-validation-status
```

Proceed only when every row is `PASS` and the final line is:

```text
ready_for_manual_validation=true
```

This proves the scheduler is still `dry_run`, automation paper trading is
disarmed, approval is required, manual paper trading is enabled, Alpaca is
paper-only and reachable, the dashboard is healthy, the runtime uses one DB,
and the scheduler heartbeat is fresh. A failure is a stop condition; diagnose
it without deploying or changing scheduler mode.

If Python reports `CERTIFICATE_VERIFY_FAILED` or a self-signed certificate in
the chain, stop and rerun the read-only readiness check from a trusted network.
Allowlist `paper-api.alpaca.markets` or use the approved network/VPN path if TLS
interception persists. Never disable certificate verification or install an
unverified CA bundle to make the check pass.

## 2. Select exactly one idea

After the regular equity session opens:

If a fresh candidate must be created, use the create-only `POST /api/ideas` or
`POST /api/ideas/import` surface. Do not use `POST /api/ideas/import-and-test`
for this step: that surface immediately runs execution/risk evaluation. Before
creating the candidate, confirm its equity ticker is absent from the current
Alpaca paper positions. Creation is successful only when the resulting idea and
approval queue rows both remain `needs_review`, the explanation is
`analyst_assisted=true`, and entry, stop, and target levels are populated.

1. Open the dashboard **Approvals** page.
2. Select one card whose asset class is **equity**. Do not use crypto or options
   for the first validation.
3. Confirm the card has a `needs_review` badge. Its presence in this queue and
   its analyst explanation show that it is analyst-assisted and that the human
   approval gate is engaged.
4. Confirm the ticker, thesis, source references, confidence, entry zone, stop
   loss, take profit, and invalidation are sensible and populated. Use **Refresh
   Levels** once if price levels are missing; stop if they remain missing.
5. Do not select or act on a second idea during this run.

## 3. Approve, then place one paper trade

Keep approval and execution as two explicit human actions:

1. On the selected card, click **Approve only**. Do not click **Approve + Paper
   Trade** for this validation.
2. Record the `idea_id` shown in the approval toast (`Idea <id> approved`).
3. Open the dashboard idea table, find the same ticker and thesis, and click its
   **Paper** button exactly once.
4. Read the confirmation carefully and confirm only the Alpaca **PAPER** trade.
   Do not click again while waiting for a response.
5. A successful response displays the Alpaca paper order ID. Record it, then
   open **Paper / Dry-Run Log** and confirm one `paper` / submitted entry for the
   same `idea_id`. Any rejection, timeout, duplicate, or ambiguous response is a
   stop condition—do not retry in this run.

## 4. Capture IDs and check evidence

Run the read-only evidence check with the recorded idea ID:

```bash
python -m alpha_lab.paper_validation_evidence --idea <IDEA_ID>
```

The header reports the linked `trade id` and Alpaca order ID. Record the
`trade_id`, then verify the same chain from that ID:

```bash
python -m alpha_lab.paper_validation_evidence --trade <TRADE_ID>
```

Both commands must identify the same idea, trade, and Alpaca order. They read
the resolved SQLite DB without writing to it or contacting Alpaca.

## 5. Pass / fail

**PASS** only when all of the following are true:

- Pre-market readiness ended with `ready_for_manual_validation=true`.
- Exactly one analyst-assisted equity idea was observed in `needs_review`, then
  manually approved before execution.
- Exactly one manual, non-dry-run order was submitted to Alpaca paper during
  market hours; no retry or second idea was used.
- Both evidence commands show all checks as `PASS` and end with
  `db_evidence_passed=true` for the same idea/trade/order chain.
- The scheduler remained `dry_run`, automation remained disarmed, and the
  paper-only/same-DB/heartbeat conditions did not change during the run.

**FAIL** on any readiness or evidence `FAIL`/`SCHEMA_INCOMPATIBLE`, missing or
blank trade levels, execution before approval, more than one paper trade/order
or submitted audit, mismatched IDs, missing performance linkage, any scheduler
order, or any possible live-endpoint contact. Stop and preserve the evidence;
do not retry, deploy, or loosen a safety gate.

## Prohibited actions

- No automated paper trading and no scheduler-triggered order.
- No deploy, restart-for-deploy, or code/trading-logic change.
- No scheduler-mode change; it stays `dry_run` throughout.
- No live trading, live credentials, or live Alpaca endpoint.
- No second order, second idea, or retry in the same validation run.
