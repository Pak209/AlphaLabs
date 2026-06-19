# Lex Review Handoff — AlphaLabs

This file has **two parts**, used by all agents (Claude, Codex, Lex, Human):

1. **Current State Summary** (top) — the concise, current snapshot. Read this first.
   It MAY be refreshed/replaced when project state materially changes; keep it current.
2. **Agent Activity Log** (bottom) — **append-only**. Never delete, rewrite, or reorder
   prior entries. New entries are agent-labeled and written via the shared helper
   (`.agents/skills/alphalabs-handoff-update/scripts/append_handoff.py`), which appends
   under the `## Agent Activity Log` heading only.

_Last updated: 2026-06-18_

## Current State Summary

> Concise current snapshot — read first; may be refreshed when state materially changes.

## Current Branch
`tooling/codexpro-devspace` (9 commits ahead of `main`, 0 behind).

## Git Status Summary
- Working tree: clean except this handoff edit. Validation docs + reconciliation handoff are
  committed (`a8cb5a6`, `7a0d9f4`, `7418a73`); **nothing pushed**.
- HEAD: `7418a73` — docs: update Lex handoff for reconciliation plan.
- `main` / `origin/main`: `366597b` — feat: classify SEC offering filings as bearish catalysts.
- **Not pushed.** No upstream tracking configured; the 9 ahead commits are local only.
- Old-Mac runner: last known on `main` @ `366597b` (= `origin/main`), clean.

## First-Validation Readiness — NOT READY (2026-06-18, code GREEN / ops BLOCKED)
Audited whether AlphaLabs can run the first manual paper validation. **Code paths are sound**
(manual endpoint, approval gate, Alpaca paper-only enforcement all verified). **Operationally
NOT READY** on two blockers:
1. **Old Mac UNREACHABLE.** SSH over Tailscale `danielkimoto@100.91.41.60` timed out (port 22,
   twice) this pass — cannot verify the runner is still `dry_run`/disarmed, that the dashboard/
   scheduler are healthy, same-DB proof holds, or that Alpaca paper is reachable. The validation
   runs against the runner, so it cannot start until the old Mac is reachable and re-verified.
   Last confirmed-safe state was `2026-06-18T18:25 PT`.
2. **Approval flag not yet set.** Runner had `ALPHALAB_REQUIRE_PAPER_APPROVAL=false` at last
   audit; the checklist requires `true` so the analyst-assisted approval gate actually engages.
   Changing it is intentionally deferred (out of scope here) — must be set before the test.
Also gating: the test must run during equity market hours. No env/launchd/old-Mac change was
made this pass.

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
- **Dev-Mac scheduler health is ambiguous.** Do not treat the dev Mac as an
  authoritative runtime; do not reload it blindly. The old Mac is the only trusted runner.
- **Branch reconciliation pending.** 8 local commits (incl. `dacdca2`) are unpushed and
  unmerged into `main`; `./ops deploy` only pulls `main` ff-only, so this work cannot reach
  the runner until reconciled. See Reconciliation Plan below.

## Stabilization Priorities (current status)

### 1. Working tree — CLEAN
- All feature/doc work is committed across 8 commits on `tooling/codexpro-devspace`
  (see Reconciliation Plan). Tree clean apart from in-flight handoff edits.

### 2. Dev Mac ↔ Old Mac drift — PRESENT (expected, gated)
- Old-Mac runner is on `main` @ `366597b` (= `origin/main`), clean. Dev is 8 commits ahead
  on the feature branch, unpushed. `./ops deploy` pulls `main` ff-only, so nothing reaches
  the runner until the 8 commits are merged into `origin/main`. No deploy performed.

### 3. Scheduler paper-mode — SAFE (disarmed)
- The runner was found paper-armed on 2026-06-18 and disarmed the same day: gates flipped to
  `ALPHALAB_SCHEDULER_MODE=dry_run` + `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=false`, scheduler
  reloaded. Re-verified read-only this pass: `safe_stabilization_mode: true`,
  `paper_trades_can_be_triggered_by_scheduler: false`, fresh heartbeat `2026-06-18T18:25 PT`.
- Keep dry_run + disarmed until a paper window is intentionally opened.
- `ALPHALAB_REQUIRE_PAPER_APPROVAL=false` still on the runner — flagged for change before any re-arm.

---

## Reconciliation Plan (prepared — NOT executed)

`./ops deploy` pulls `origin/main` ff-only on the old Mac, so the 8 feature-branch commits must
land in `main` before any deploy. No merge/rebase/push was performed; this is the plan only.

**The 8 commits ahead of `main` (oldest → newest), classified:**
| Commit | Type | Summary |
|---|---|---|
| `bf7f64d` | tooling/docs | CodexPro tooling templates (`.ai/*`, `TOOLING_HANDOFF.md`) |
| `2c4c52c` | tooling | CodexPro stable tunnel helper scripts + `.gitignore` token rules |
| `6227f46` | runtime | multi-coin after-hours crypto + Yahoo keyless price fallback + tests |
| `dacdca2` | config/risk | widen position limits (equity 20 / crypto 25), swap SOL/BNB→HYPE |
| `e1999c1` | docs | remote-ops runbook, dated handoff, Cloudflare stable launcher |
| `be3757c` | docs | Lex review handoff |
| `a8cb5a6` | docs | define manual paper validation gate |
| `7a0d9f4` | docs | require analyst-assisted idea for paper validation |

- **Commits that should NOT go to `main`:** none identified — all 8 are intended. The only
  runtime-behavior changers are `6227f46` (tested) and `dacdca2` (config). Tooling/docs commits
  are inert at runtime.
- **`dacdca2` widening:** re-confirmed INTENTIONAL for paper-test capacity (keep equity=20,
  crypto=25). Do NOT revert. Safety rests on the scheduler/automation/approval gates, not the
  position cap.
- **Secret scan (commit range `main..HEAD`):** clean. High-entropy literal patterns
  (AKIA…/sk-…/xox…/PRIVATE KEY) = 0 hits. All matches are env-var NAMES, `.gitignore` token
  globs, docs about the secret blocklist, or runtime code reading a token file / setting HTTP
  header names — no literal credentials.
- **Tests:** `6227f46` shipped with green tests (`test_api`, `test_price_volume_feed`,
  `test_decision_engine`) per its commit; re-run before deploy as a gate.

**Recommendation: regular merge `tooling/codexpro-devspace` into LOCAL `main` (no squash).**
Rationale: the 8 commits are already logically separated by concern (tooling/docs/runtime/
config), so preserving them keeps `dacdca2`'s isolated 1-file config change individually
revertible and keeps the runtime feature (`6227f46`) auditable apart from docs. Squash would
bury the deliberate `dacdca2` isolation. Cherry-pick is unnecessary since none are excluded.
Do this only AFTER manual paper validation passes; then push `main` and `./ops deploy`.

---

## Latest Task

### Task Summary
Reconciliation-prep pass: cleaned stale commit counts/sections in this handoff (now
consistently 8 commits @ HEAD `7a0d9f4`), ran a read-only validation of the `main..HEAD` range
(status/log/diff/secret scan), and produced a branch Reconciliation Plan (above). No merge,
rebase, push, deploy, re-arm, or old-Mac change. The manual-validation and approval-policy
findings from prior passes are retained below for Lex.

### Carried forward — Manual paper validation (DEFINED)
- Full checklist: `docs/MANUAL_PAPER_VALIDATION.md`. First test: ONE human-selected
  **analyst-assisted** equity idea, manual paper path, scheduler `dry_run`, automation flag off,
  human approval required, paper endpoint only. Pass = single attributable equity paper order
  (idea→approval→trade→audit→Performance) with the scheduler proven idle/`dry_run` and same-DB
  proof intact; any live-endpoint contact, scheduler order, missing approval, blank price, or
  missing record = fail → stop, stay `dry_run`/disarmed.

### Carried forward — Approval policy (`ALPHALAB_REQUIRE_PAPER_APPROVAL`) RECOMMENDATION
- `_paper_approval_required()` (`service.py:1752`) → `_paper_execution_approval_error()`
  (`service.py:1716`), called by `place_trade()` on EVERY non-dry-run execution
  (`service.py:846`). `place_trade` is the single choke point for BOTH manual and automation
  paper paths → the flag governs **both**, but the gate only bites on **analyst-assisted OR
  crypto** ideas (`service.py:1722`); plain non-assisted equity ideas skip it. Rejected/expired
  ideas always blocked.
- **Recommendation:** set `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` on the runner **before any
  paper re-arm** (currently `false`). Safest value for first validation; the validation idea
  must be analyst-assisted for the gate to apply (now required by the checklist). NOT changed.

### Carried forward — Deploy-readiness (no deploy)
- **Dev:** `tooling/codexpro-devspace` @ `7a0d9f4`, 8 ahead / 0 behind `main`, clean, NOT pushed.
- **Old Mac:** `main` @ `366597b` (= `origin/main`), clean, origin = `Pak209/AlphaLabs.git`.
- **Delta (dev has, runner lacks), 8 commits:** `bf7f64d`, `2c4c52c`, `6227f46`, `dacdca2`,
  `e1999c1`, `be3757c`, `a8cb5a6`, `7a0d9f4` (CodexPro tooling/docs, multi-coin crypto + Yahoo
  fallback, exposure widening, runbook/launcher, Lex handoff, manual-validation docs).
- **Old-Mac safety (audited read-only over Tailscale):** `safe_stabilization_mode: true`
  (mode=`dry_run`, automation guard `false`, paper-trigger `false`). Scheduler + dashboard
  LaunchAgents `running`; fresh heartbeat `2026-06-18T18:25 PT`. `require_approval=false`,
  `manual_paper=true`, `.env` perms `600`.
- **DB path correct:** yes — resolver == heartbeat == db_status ==
  `/Users/danielkimoto/AlphaLab/alpha_lab/data/alpha_lab.sqlite3` (no split-brain). ideas=119,
  trades=32, catalyst_events=213.
- **KEY DEPLOY MECHANISM / BLOCKER:** `./ops deploy` does `git fetch + pull --ff-only` on the
  server, which is on **`main`**. The 8 dev commits are on a feature branch that is **unpushed
  and not in `main`**, so an `--ff-only` pull would bring **nothing**. Deploying this work
  REQUIRES first reconciling the 8 commits into `origin/main` (merge/PR + push). No way around
  this short of changing the server's tracked branch. `./ops deploy` also kickstarts dashboard +
  scheduler after pulling, but preserves `.env`/DB/logs/reports/launchd, and
  `require_safe_service_reload` refuses if paper jobs are armed (they are not — safe).
- **Before deploying this branch:** (a) pass manual paper validation first; (b) **merge the 8
  commits into `origin/main` and push** (runner only pulls `main` ff-only); (c) re-confirm the
  `dacdca2` widening is intended for the runner (it is — keep equity 20 / crypto 25); (d) keep
  gates safe and set `REQUIRE_PAPER_APPROVAL=true` if re-arming; (e) back up `.env`; (f) deploy
  code-only via `./ops deploy` (never overwrite the live `.env`/DB); (g) stop services before
  any tree move. Read-only `./ops deploy-preflight` checks the commit gap/dirty/safety first.
- **Immediately after deploy:** run `scripts/verify_old_mac_runtime.sh` (or
  `./ops remote-status/safety-status/health`) — confirm commit matches, `safe_stabilization_mode:
  true`, DB path unchanged + same-DB proof, fresh heartbeat, expected job count, dashboard on
  loopback, paper checks 200.

### Files Changed
- `.ai/LEX_REVIEW_HANDOFF.md` only (this cleanup + Reconciliation Plan). **No config/code/env/
  launchd changes; `dacdca2` kept.**

### Commands Run
- Local read-only: `git status --short`, `git log --oneline main..HEAD`,
  `git diff --stat main..HEAD`, `git diff --name-only main..HEAD`, per-commit `git show --stat`,
  and a pattern-based secret scan of `git diff main..HEAD` (no dedicated scanner installed).
- No old-Mac commands this pass (state carried from the prior read-only audit). No writes.

### Git State
- Branch `tooling/codexpro-devspace`, HEAD `7a0d9f4`, **8 commits ahead of `main`, not pushed**.
  Working tree: only `.ai/LEX_REVIEW_HANDOFF.md` modified. `docs/MANUAL_PAPER_VALIDATION.md` is
  COMMITTED (in `a8cb5a6`/`7a0d9f4`), not untracked. Runner unchanged (`main` @ `366597b`).

### Safety Notes
- Read-only + handoff edit only. No merge, rebase, push, deploy, trades, scheduler re-arm,
  `.env`, launchd, or runtime-code changes. Old Mac left exactly as found: `dry_run`/disarmed.

### What Lex Should Inspect Next
- Approve the Reconciliation Plan: regular merge of the 8 commits into `main` (no squash), only
  after manual paper validation passes.
- Review `docs/MANUAL_PAPER_VALIDATION.md` pass/fail criteria and the
  `ALPHALAB_REQUIRE_PAPER_APPROVAL=true`-before-re-arm recommendation.

### Open Questions
- Confirm regular-merge (vs squash) is the desired reconciliation style into `main`.
- Confirm whether `main` should be reconciled now or held until manual validation passes
  (current recommendation: hold until validation passes).

### Recommended Next Step
- **First validation = NOT READY.** Before it can run: (a) restore old-Mac reachability over
  Tailscale and re-verify `./ops safety-status` + `./ops health` + `./ops check alpaca`
  (scheduler `dry_run`/disarmed, same-DB proof, paper 200); (b) set
  `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` on the runner; (c) run during equity market hours.
- Then follow `docs/MANUAL_PAPER_VALIDATION.md` exactly (one analyst-assisted equity idea →
  approve → `POST /api/ideas/{id}/paper-trade`).
- Branch reconciliation and re-arm remain gated behind a clean validation PASS. No merge/push/
  deploy/re-arm now.

---

## Agent Activity Log

> Append-only. Never delete, rewrite, or reorder entries below. New entries are added by the
> shared helper under this heading and must be agent-labeled (`Claude`/`Codex`/`Lex`/`Human`).

## 2026-06-18 22:34 PT — Codex

Branch: tooling/codexpro-devspace
Commit: none
Working Tree: modified

### Summary
Created the repo-scoped AlphaLabs Handoff Update skill and aligned the handoff header with its append-only policy.

### Files Modified
- .agents/skills/alphalabs-handoff-update/SKILL.md
- .agents/skills/alphalabs-handoff-update/agents/openai.yaml
- .agents/skills/alphalabs-handoff-update/scripts/append_handoff.py
- .ai/LEX_REVIEW_HANDOFF.md

### Commands / Tests Run
- python3 skill-creator/scripts/quick_validate.py .agents/skills/alphalabs-handoff-update
- python3 .agents/skills/alphalabs-handoff-update/scripts/append_handoff.py --help
- Secret-pattern rejection fixture
- git diff --check

### Results
- Skill structure passed validation.
- The helper parsed successfully and rejected credential-like input without changing the handoff.
- A Codex-labeled append-only entry was written with branch, commit, and working-tree state.

### Risks / Blockers
- The skill records handoffs when Codex invokes it; other agents must adopt the same file contract independently.

### Next Recommended Task
Have Claude and Lex adopt the append-only entry contract for their completed tasks.


## 2026-06-18 22:36 PT — Claude

Branch: tooling/codexpro-devspace
Commit: none
Working Tree: modified

### Summary
Made .ai/LEX_REVIEW_HANDOFF.md the mandatory append-only project handoff log for Claude by adding a project CLAUDE.md that binds Claude to the same cross-agent contract already implemented by the Codex skill (.agents/skills/alphalabs-handoff-update). Reused the existing append_handoff.py helper instead of duplicating it.

### Files Modified
- CLAUDE.md (new)

### Commands / Tests Run
- git status / read existing .ai/* and .agents/skills/alphalabs-handoff-update skill
- python3 .agents/skills/alphalabs-handoff-update/scripts/append_handoff.py --agent Claude (this entry)

### Results
- CLAUDE.md now mandates appending an entry after every meaningful task and operational event (deploys, scheduler/launchd/dashboard/old-Mac/env/DB changes), defines audit entries, append-only + agent-label + security rules, and points to the shared helper. Verified the helper appends a Claude-labeled entry and rejects credential-like text.

### Risks / Blockers
- Lex and human operators must also adopt the same append contract; only Claude (CLAUDE.md) and Codex (skill) are codified so far.

### Next Recommended Task
Have Lex adopt the same append-only contract; consider a short note in .ai/project-context.md so the mandate is discoverable by all readers.
