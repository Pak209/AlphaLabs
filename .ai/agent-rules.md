# Agent Rules — AlphaLabs

Binding rules for any AI assistant connected to this repository through CodexPro (or
any future MCP tool). These rules apply on top of the tool's own enforcement.

## Hard prohibitions (never, without explicit human approval)
1. **No public exposure.** Never enable a tunnel (Cloudflare, ngrok, named tunnel) or
   any token/password URL. Local-only (`127.0.0.1`) only.
2. **No paper trades. No live trades.** Never invoke any trading or order path.
3. **No scheduler jobs.** Never start, trigger, or load `launchd` jobs or scheduled runs.
4. **No runtime changes.** Do not modify:
   - runtime code (`alpha_lab/`, `paper_trader/` runtime logic)
   - trading logic / decision engine
   - broker / API integration behavior
   - deploy scripts (`deploy/`) or operational scripts that act on prod
   - `launchd` files / scheduler configuration
   - database schema or the database file
5. **No reading of sensitive paths** — see `blocked-paths.md` (`.env`, `*.sqlite3`,
   `logs/`, `reports/`, `data/`, `credentials/`, `secrets/`, keys).

## Approved operating mode (current)
- **Read-only first:** `--write off --bash off`. No file writes/edits, no shell.
- **Local-only, no tunnel.**
- **Extended blocked globs required** (see `blocked-paths.md`) — must be set before launch.
- Allowed activity: read code, search, view file tree, `git status`, `git diff`,
  explain/plan. Planning output via handoff files only if write mode is later enabled
  and scoped to `.ai-bridge/`.

## Escalation
- Enabling write mode, bash mode, or any tunnel is a **separate, explicit** human
  decision. Until then, treat those capabilities as disabled.
- If a task seems to require a prohibited action, stop and ask a human instead.

## Isolation (multi-project)
- One repo per CodexPro `--root`. Never use `--allow-home` or a parent directory.
- No project should be able to read another project's files.
