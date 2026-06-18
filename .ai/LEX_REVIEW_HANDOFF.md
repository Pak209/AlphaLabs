# Lex Review Handoff — AlphaLabs

Living handoff for review (Lex). Updated before the completion of every task.
Keep this current and concise: replace stale information instead of appending history.

_Last updated: 2026-06-18_

## Current Branch
`tooling/codexpro-devspace` (6 commits ahead of `main`, 0 behind).

## Git Status Summary
- Working tree (before this pass): clean. This pass adds `docs/MANUAL_PAPER_VALIDATION.md`
  (new) + this handoff edit; nothing committed/pushed.
- HEAD: `be3757c` — docs: add Lex review handoff.
- `main` / `origin/main`: `366597b` — feat: classify SEC offering filings as bearish catalysts.
- **Not pushed.** No upstream tracking configured; the 6 ahead commits are local only.
- Old-Mac runner: on `main` @ `366597b` (= `origin/main`), working tree clean.

## This Pass Was Read-Only (audit + planning docs)
No trades, no scheduler/automation re-arm, no `.env`/launchd/deploy/push changes. This pass
only read code, performed a **read-only** old-Mac audit over Tailscale, authored the manual
paper-validation checklist, and updated this handoff. The disarm/cleanup notes below are from
the prior pass (retained for context).

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
Stabilization pass: (1) defined "manual paper validation passed" as a concrete checklist in
`docs/MANUAL_PAPER_VALIDATION.md`; (2) analyzed the `ALPHALAB_REQUIRE_PAPER_APPROVAL` gate and
recommended setting it `true` on the runner before any paper re-arm; (3) audited dev↔old-Mac
drift read-only and produced a deploy-readiness plan (no deploy). Read-only — no config/code/
env/launchd/runtime changes.

### 1. Manual paper validation — DEFINED
- Full checklist: `docs/MANUAL_PAPER_VALIDATION.md`. First test is conservative: ONE
  human-selected EQUITY idea, manual paper path, scheduler `dry_run`, automation flag off,
  human approval required, paper endpoint only.
- Pass = single attributable equity paper order (idea→approval→trade→audit→Performance), with
  the scheduler proven idle/`dry_run` and same-DB proof intact. Any live-endpoint contact,
  scheduler-placed order, missing approval, blank price, or missing audit/DB record = fail →
  stop, stay `dry_run`/disarmed.

### 2. Approval policy (`ALPHALAB_REQUIRE_PAPER_APPROVAL`) — RECOMMENDATION
- **How it works:** `_paper_approval_required()` (`service.py:1752`) reads the env var
  (default `true`; only `false`-ish values disable it). It is consumed by
  `_paper_execution_approval_error()` (`service.py:1716`), which `place_trade()` calls on EVERY
  non-dry-run execution (`service.py:846`).
- **Scope:** `place_trade` is the single choke point for BOTH manual (`test_trending_strategies`)
  and automation (`import_and_test`, `poll_live_catalysts`, etc.) paper paths → the flag
  governs **both**. BUT the gate only applies to ideas that are **analyst-assisted** OR
  **crypto** (`service.py:1722`); plain non-assisted equity ideas skip it entirely. Rejected/
  expired ideas are ALWAYS blocked regardless of the flag.
- **true vs false:** `true` → an analyst-assisted/crypto idea must be `approved` in the
  Approvals page before a paper order places; otherwise `needs_human_approval`, no order.
  `false` → those ideas skip the human gate (only rejected/expired still blocked).
- **Recommendation:** Set `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` on the old Mac **before any
  paper re-arm**. It is the safest value for first manual validation (defense-in-depth for the
  manual path and a hard prerequisite once automation is later considered). Currently `false`
  on the runner. NOT changed this pass — recommendation only. Caveat: it does not cover plain
  non-assisted equity ideas, so the validation idea should be analyst-assisted (or rely on the
  human nature of the manual test) for the gate to bite.

### 3. Dev ↔ Old-Mac drift / deploy-readiness — PLAN (no deploy)
- **Dev:** `tooling/codexpro-devspace` @ `be3757c`, 6 ahead / 0 behind `main`, clean, NOT pushed.
- **Old Mac:** `main` @ `366597b` (= `origin/main`), clean.
- **Delta (dev has, runner lacks):** `bf7f64d`, `2c4c52c`, `6227f46`, `dacdca2`, `e1999c1`,
  `be3757c` (CodexPro tooling/docs, multi-coin crypto + Yahoo fallback, exposure widening,
  runbook/handoff/launcher, this handoff).
- **Old-Mac safety (audited read-only over Tailscale):** `safe_stabilization_mode: true`
  (mode=`dry_run`, automation guard `false`, paper-trigger `false`). Scheduler + dashboard
  LaunchAgents `running`; fresh heartbeat `2026-06-18T16:30 PT`. `require_approval=false`,
  `manual_paper=true`, `.env` perms `600`.
- **DB path correct:** yes — resolver == heartbeat == db_status ==
  `/Users/danielkimoto/AlphaLab/alpha_lab/data/alpha_lab.sqlite3` (no split-brain). ideas=119,
  trades=32, catalyst_events=213.
- **Before deploying this branch:** (a) pass manual paper validation first; (b) reconcile the
  6 unpushed commits into `main` (PR or merge — runner tracks `main`); (c) re-confirm the
  `dacdca2` widening is intended for the runner (it is — keep equity 20 / crypto 25); (d) keep
  gates safe and set `REQUIRE_PAPER_APPROVAL=true` if re-arming; (e) back up `.env`; (f) deploy
  code-only, never overwrite the live `.env`/DB; (g) stop services before any tree move.
- **Immediately after deploy:** run `scripts/verify_old_mac_runtime.sh` (or
  `./ops remote-status/safety-status/health`) — confirm commit matches, `safe_stabilization_mode:
  true`, DB path unchanged + same-DB proof, fresh heartbeat, expected job count, dashboard on
  loopback, paper checks 200.

### Files Changed
- `docs/MANUAL_PAPER_VALIDATION.md` (new) + `.ai/LEX_REVIEW_HANDOFF.md` (this update). **No
  config/code/env/launchd changes; `dacdca2` kept.**

### Commands Run
- Local: `git rev-parse`/`log`/`status` (read-only). Read of scheduler/service/config/scripts.
- Old Mac (read-only over Tailscale `danielkimoto@100.91.41.60`): `git rev-parse`/`status`,
  `.env` gate names only (no secret values), `launchctl print` states, venv `resolve_db_path`,
  `scheduler_safety_status`, `db_status --json`. No writes, no smoke-test, no order endpoints.

### Git State
- Branch `tooling/codexpro-devspace`, 6 commits ahead of `main`, **not pushed**. Working tree:
  `docs/MANUAL_PAPER_VALIDATION.md` (untracked) + `.ai/LEX_REVIEW_HANDOFF.md` (modified).
  Runner unchanged (`main` @ `366597b`).

### Safety Notes
- Read-only + doc authoring only. No deploy, push, trades, scheduler start/re-arm, `.env`,
  launchd, or runtime-code changes. Old Mac left exactly as found: `dry_run`/disarmed.

### What Lex Should Inspect Next
- Review `docs/MANUAL_PAPER_VALIDATION.md`: are the pass/fail criteria and order-size limits
  acceptable for the first paper test?
- Confirm the recommendation to set `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` on the runner before
  any re-arm, given the gate does not cover non-assisted equity ideas.
- Decide branch reconciliation (PR vs merge of the 6 commits into `main`) before any deploy.

### Open Questions
- Should the first validation idea be forced analyst-assisted so the approval gate applies, or
  is the human-placed manual nature sufficient for a non-assisted equity idea?
- Reconciliation path for the 6 unpushed commits: PR review vs direct merge to `main`?

### Recommended Next Step
- Lex reviews the validation checklist + approval recommendation. Keep scheduler
  `dry_run`/disarmed; set `REQUIRE_PAPER_APPROVAL=true` only as part of an intentional re-arm
  decision after a clean manual validation. No deploy/push/re-arm before then.
