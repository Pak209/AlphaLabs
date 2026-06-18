# Lex Review Handoff — AlphaLabs

Living handoff for review (Lex). Updated before the completion of every task.
Keep this current and concise: replace stale information instead of appending history.

_Last updated: 2026-06-18_

## Current Branch
`tooling/codexpro-devspace` (5 commits ahead of `main`, 0 behind).

## Git Status Summary
- Working tree: **clean** (`git status --short` empty).
- HEAD: `e1999c1` — docs: add remote-ops runbook, dated handoff, and Cloudflare stable launcher.
- `main` / `origin/main`: `366597b` — feat: classify SEC offering filings as bearish catalysts.
- **Not pushed.** No upstream tracking configured; the 5 ahead commits are local only.

## This Pass Made Changes (NOT read-only)
This session performed two authorized remediations: a **production scheduler disarm on
the old-Mac runner** and a **working-tree cleanup**. Details below.

## Known Risks
- **Exposure-limit widening is INTENTIONAL (paper-test capacity) — file is RUNTIME-ACTIVE.**
  Commit `dacdca2` widens equity `max_open_positions` 10→20 and crypto 2→25 and swaps
  SOL/BNB→HYPE in `alpha_lab/config.example.json`. This is a **deliberate decision** to
  give AlphaLabs wider capacity to test multiple concurrent ideas/signals in paper mode —
  **not an accidental config risk.** Keep equity=20 / crypto=25; do NOT revert `dacdca2`.
  Despite the `.example` name, the file IS the live default risk config: `service.py:46`
  sets it as `DEFAULT_RISK_CONFIG`, both production entry points use it with no override
  (`scheduler.py:144`, `api.py:39`), and the limit is enforced in
  `paper_trader/decision_engine.py:56`. No alternate `config.json` exists and it is not
  gitignored — so these limits take effect wherever the code runs.
- **Wider limits are acceptable for PAPER ONLY.** The widened concurrency is safe only
  while the runner stays disarmed/dry_run and no automated paper trading is enabled.
  Safety now depends on the *other* gates, not the position-count cap (see below).
- **Dev-Mac scheduler health is ambiguous.** `com.alphalab.scheduler` is loaded
  (PID 43901) and `com.alphalab.dashboard` (PID 88974), but `db_status` reports the
  dev-Mac scheduler heartbeat as **"never"** — the loaded agent is not stamping this
  DB. Do not treat the dev Mac as an authoritative runtime; do not reload it blindly.
- **Branch reconciliation pending.** 5 local commits (incl. `dacdca2`) are unpushed
  and unmerged; no decision yet on PR vs rebase into `main`.

## Stabilization Priorities (active review items)

### 1. Dirty Working Tree
- **Status: RESOLVED this pass.** The 12 modified + 3 untracked files were committed
  into three logical commits; tree is now clean. Affected tests green (36 passed:
  `test_api`, `test_price_volume_feed`, `test_decision_engine`) before committing.
  - `6227f46` **feat** — multi-coin after-hours crypto (BTC/LINK/HYPE) + keyless Yahoo
    price fallback + crypto Alpaca v1beta3 pricing + bearish-crypto reject guard +
    regenerate-explanation endpoint/UI + tests (9 files).
  - `dacdca2` **config** — exposure-limit widening, **isolated and flagged review-before-deploy** (1 file).
  - `e1999c1` **docs** — remote-ops runbook, dated handoff, CodexPro Cloudflare stable
    launcher (secret-scanned: only env-var names / runtime token-file reads, no literals).

### 2. Dev Mac ↔ Old Mac Drift
- **Status: DRIFT PRESENT (expected, gated).** Old-Mac runner is on `main` at `366597b`
  (= `origin/main`), clean. Dev Mac is on `tooling/codexpro-devspace`, 5 commits ahead.
- The 5-commit delta = multi-coin crypto + Yahoo fallback feature work, CodexPro
  tooling/docs, and the exposure-widening config (`dacdca2`).
- Risk centers on `dacdca2` reaching the runner without deliberate review/deploy. No
  deploy was performed; runner code is unchanged.

### 3. Scheduler Paper-Mode Risk
- **Status: WAS UNSAFE → DISARMED this pass.** The old-Mac runner was found
  **paper-armed**: `ALPHALAB_SCHEDULER_MODE=paper`, automation guard `true`, approval
  `false`, scheduler live under launchd KeepAlive — i.e. it could place Alpaca paper
  orders fully unattended during market hours.
- **Remediation (old Mac, over Tailscale `danielkimoto@100.91.41.60`):**
  - Backed up `.env` → `.env.bak.20260618-153925` (line-count parity 18=18, no corruption).
  - Flipped ONLY the two gates: `ALPHALAB_SCHEDULER_MODE` paper→dry_run and
    `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` true→false. No other lines/secrets touched.
  - Reloaded: `launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler` (new PID 81021).
  - Verified `scheduler_safety_status`: `safe_stabilization_mode: true`,
    `paper_trades_can_be_triggered_by_scheduler: false`; fresh `dry_run` heartbeat at
    `2026-06-18T15:45 PT` (process healthy, not crash-looping).
- Keep dry_run + disarmed guard until a paper-trading window is intentionally opened.
- Note: `ALPHALAB_REQUIRE_PAPER_APPROVAL=false` remains on the runner (manual-trade
  approval gate off) — unchanged this pass; flag if approval should be required.

---

## Latest Task

### Task Summary
Resolved the `dacdca2` review: the exposure-limit widening is **intentional paper-test
capacity, KEPT (equity=20, crypto=25), not reverted.** Confirmed `config.example.json` is
runtime-active. Reframed the handoff from "accidental config risk" to "intentional decision
with safety dependent on the other gates." No config/code changed.

### Decisions Recorded
1. **`config.example.json` is runtime-active** — the live default risk config for the
   scheduler (`scheduler.py:144`) and API (`api.py:39`) via `DEFAULT_RISK_CONFIG`
   (`service.py:46`); enforced at `paper_trader/decision_engine.py:56`. No alternate
   `config.json`; not gitignored.
2. **`max_open_positions` widening (equity 20, crypto 25) is intentional** for paper-test
   capacity to exercise multiple concurrent ideas/signals. Do NOT revert `dacdca2`.
3. **Wider position count is acceptable for PAPER ONLY.** With the position-count cap
   deliberately loosened, remaining safety must be enforced by controlling:
   - **scheduler mode** — keep `ALPHALAB_SCHEDULER_MODE=dry_run`
   - **automation paper-trade flag** — keep `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` off
   - **max trades per day** — equity `max_trades_per_day=10`, crypto `=3` (current)
   - **position size** — equity `max_position_size_usd=1900` / `max_equity_pct_per_trade=0.02`;
     crypto `max_position_size_usd=250` / `max_equity_pct_per_trade=0.01` (current)
   - **approval policy** — `ALPHALAB_REQUIRE_PAPER_APPROVAL` (currently false on runner)
4. **Hard guardrails this stabilization window:** old-Mac scheduler stays disarmed/dry_run;
   NO automated paper trading until manual paper validation passes; no deploy, no scheduler
   re-arm, no trades.

### Files Changed
- `.ai/LEX_REVIEW_HANDOFF.md` (this update only). **No config/code changed; `dacdca2` kept.**

### Commands Run
- None this pass beyond `git status` (handoff edit only). Prior pass: `git show dacdca2`,
  Grep/Read of config load path — all read-only.

### Git State
- Branch `tooling/codexpro-devspace`, 5 commits ahead of `main`, **not pushed**.
  Working tree: only `.ai/LEX_REVIEW_HANDOFF.md` modified. Runner unchanged.

### Safety Notes
- Handoff edit only. No deploy, push, trades, scheduler start/re-arm, `.env`, launchd, or
  runtime-code changes. Widened limits remain (intentional); safety rests on the gates above.

### What Lex Should Inspect Next
- Whether the current limits are reasonable for **paper-only** testing (equity 20 / crypto 25
  concurrent) and whether any additional guardrails are needed before any deployment.
- Confirm the per-day / position-size / approval gates above are tight enough to bound
  exposure now that the concurrency cap is loosened.
- Before ANY future deploy or scheduler re-arm: require passing manual paper validation first.

### Open Questions
- What defines "manual paper validation passed" (criteria/duration) before automation may arm?
- Should `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` be set on the runner as defense-in-depth
  while concurrency is wide?

### Recommended Next Step
- Lex reviews limit reasonableness + guardrails for paper-only testing. Keep scheduler
  dry_run/disarmed until manual paper validation passes; no deploy or re-arm before then.
