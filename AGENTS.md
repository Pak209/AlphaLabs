# AlphaLabs — Codex Project Instructions

## Mandatory handoff log — `.ai/LEX_REVIEW_HANDOFF.md`

`.ai/LEX_REVIEW_HANDOFF.md` is the **authoritative project timeline and operational
memory**, shared by Codex, Codex, Lex, and human operators. A new contributor must be
able to read only that file and understand current project state, deployment state,
runtime state, recent changes, blockers, and next actions — without chat history.

This is the single shared contract; the matching Codex skill lives at
`.agents/skills/alphalabs-handoff-update/`. Codex follows the **same** file contract.

### Two-part model

The file has two parts — treat them differently:

1. **Current State Summary** (top, `## Current State Summary`) — the concise current
   snapshot Lex/Pak read first. It MAY be refreshed/replaced in place when project state
   materially changes (deploy, branch reconciliation, scheduler re-arm, validation
   pass/fail). Keep it current and brief.
2. **Agent Activity Log** (bottom, `## Agent Activity Log`) — **append-only**. Never
   delete, rewrite, or reorder prior entries. Every meaningful task adds a new
   agent-labeled entry here via the shared helper, which appends under this heading only.

When state materially changes: refresh the Current State Summary in place AND append a new
log entry describing the change. Never edit a prior log entry retroactively.

### When to append (do NOT wait to be asked)

After every meaningful task, append a new entry. Meaningful tasks include: code changes,
audits, bug investigations, deployments, scheduler changes, launchd changes, database
changes/migrations, infrastructure changes, MCP changes, CodexPro changes, production
verification, paper-trading configuration changes, and runtime diagnostics.

Always append an entry for these **operational events**, even when no source file changed:
deploys, scheduler restarts, LaunchAgent changes, dashboard restarts, old-Mac server
changes, dedicated-server changes, paper-trading mode changes, environment/config changes,
DB migrations. These are first-class project events.

If no files changed but useful work occurred, append an **audit entry**: what was
inspected, what was verified, findings, and recommendations (`Files Modified: - None
(audit only).`).

### How to append

Append via the shared helper from the repo root (do not hand-edit prior entries):

```bash
python3 .agents/skills/alphalabs-handoff-update/scripts/append_handoff.py \
  --agent Codex \
  --summary "..." \
  --file path/changed --command "cmd run" --result "what was verified" \
  --risk "remaining concern" --next "highest-leverage next action" \
  --commit <hash-or-none>
```

The helper stamps a Pacific-time timestamp, branch, and working-tree state, and rejects
credential-like text. Repeat `--file/--command/--result/--risk` for multiple items. Pass
`--commit <hash>` only when *this task* created that commit, else `none`. After appending,
read the tail and run `git diff --check -- .ai/LEX_REVIEW_HANDOFF.md`.

### Entry contract (produced by the helper)

```markdown
## YYYY-MM-DD HH:MM PT — Codex

Branch: branch-name
Commit: none
Working Tree: clean

### Summary
### Files Modified
### Commands / Tests Run
### Results
### Risks / Blockers
### Next Recommended Task
```

### Append-only & agent-label rules

- Append only. Never delete entries, never rewrite project history, preserve chronology.
- Every entry identifies the actor: exactly one of `Codex`, `Codex`, `Lex`, `Human`.
- If another agent wrote the previous entry, do not modify it — append your own.
- Keep entries concise and factual; prefer evidence over assumptions.

### Security rules

Never record API keys, tokens, passwords, secrets, cookie values, full URLs containing
credentials, or `.env` contents. Do not paste large logs/diffs/transcripts. Record only
that required credentials were verified, e.g. "Verified required environment variables
exist and loaded successfully." See `.ai/blocked-paths.md` for off-limits paths.

## Operating posture

This repo runs an automated paper-trading system on a macOS `launchd` runner (old Mac).
Read `.ai/agent-rules.md`, `.ai/blocked-paths.md`, and `.ai/project-context.md` before
acting. Do not trigger trades, start/re-arm scheduler paper mode, modify `.env`, or change
launchd without explicit human approval. Keep the runner `dry_run`/disarmed during
stabilization until manual paper validation passes.
