---
name: alphalabs-handoff-update
description: Maintain AlphaLabs' append-only `.ai/LEX_REVIEW_HANDOFF.md` as the cross-agent source of truth. Use at the end of every meaningful task, audit, investigation, implementation, bug fix, deployment, or review in this repository, including useful read-only work, so Codex records who acted, what changed or was inspected, validation performed, results, risks, git state, and the highest-leverage next step without exposing secrets.
---

# AlphaLabs Handoff Update

`.ai/LEX_REVIEW_HANDOFF.md` is **two-part** and shared by all agents (Codex, Claude, Lex, Human):

1. **Current State Summary** (top, under `## Current State Summary`) — the concise current
   snapshot Lex/Pak read first. It MAY be refreshed/replaced when project state materially
   changes; keep it current and brief.
2. **Agent Activity Log** (bottom, under `## Agent Activity Log`) — **append-only**. Never
   delete, rewrite, or reorder prior entries.

This skill appends one concise, factual entry to the **Agent Activity Log only**, after
completing meaningful work. The helper requires the `## Agent Activity Log` heading and
appends within that section; it never touches the Current State Summary. Refreshing the
Current State Summary is a separate, deliberate hand-edit — do not delete log history.

## Workflow

1. Finish the task and its verification before writing the entry.
2. Determine the performing agent. Use exactly one of: `Codex`, `Claude`, `Lex`, or `Human`.
3. Gather the facts from the current task:
   - summary of completed work or investigation;
   - files modified, or `None (audit only)` when no files changed;
   - commands and tests actually run;
   - verified successes and failures;
   - outstanding risks or blockers;
   - one highest-leverage next task;
   - current branch and working-tree state;
   - the task's commit hash, or `none` if this task created no commit.
4. Exclude all credentials and secret values. Never read secret-bearing files for the handoff. Refer to secret checks only generically, such as `Verified required environment variables exist.`
5. Append the entry with `scripts/append_handoff.py`. Do not hand-edit prior entries.
6. Read the appended tail and run `git diff --check -- .ai/LEX_REVIEW_HANDOFF.md` to verify formatting.

## Append Command

Run from the repository root:

```bash
python3 .agents/skills/alphalabs-handoff-update/scripts/append_handoff.py \
  --agent Codex \
  --summary "Implemented and verified the requested change." \
  --file path/to/file.py \
  --command "pytest tests/test_file.py" \
  --result "Targeted tests passed." \
  --risk "None identified." \
  --next "Run the broader regression suite." \
  --commit none
```

Repeat `--file`, `--command`, `--result`, and `--risk` for multiple items. The helper supplies a Pacific-time timestamp, branch, and working-tree state. Pass `--commit <hash>` only when the current task created that commit.

## Entry Contract

Every appended entry must contain, in order:

```markdown
## YYYY-MM-DD HH:MM PT — AgentName

Branch: branch-name
Commit: none
Working Tree: clean

### Summary
...

### Files Modified
- ...

### Commands / Tests Run
- ...

### Results
- ...

### Risks / Blockers
- ...

### Next Recommended Task
...
```

The helper inserts this block under `## Agent Activity Log` (the section runs to end of file), preserving every prior entry. It errors if that heading is missing rather than appending blindly.

For audits and read-only investigations, summarize what was inspected and verified, put `- None (audit only).` under files, and record the findings and recommended action. Facts belong in the handoff; speculation does not.

## Refreshing the Current State Summary

When project state materially changes (deploy, branch reconciliation, scheduler re-arm, validation pass/fail), update the `## Current State Summary` section in place to stay current and concise. This is the one part that may be rewritten. The `## Agent Activity Log` below it is never edited retroactively — record the change as a new appended log entry too.

## Security Guardrails

Never record API keys, tokens, secrets, passwords, cookie values, `.env` contents, private credentials, or command output containing them. Do not paste large logs, diffs, or chat transcripts. The helper rejects common credential-assignment and bearer-token patterns, but the agent remains responsible for reviewing every value before appending it.
