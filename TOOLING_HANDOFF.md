# Tooling Handoff — CodexPro / DevSpace

Reusable AI development-environment setup. This file documents how CodexPro (and,
later, DevSpace) connect to this repository, the approved operating mode, and the
exact commands to operate the tools. Copy this file + the `.ai/` directory into
future repositories (Nomi, Holobots, …) as the standard tooling baseline.

> Scope: these tools are **MCP servers** that expose a local repo to ChatGPT's web
> "Developer Mode." They run on your machine; the remote party is ChatGPT reaching
> back in. Treat repo exposure as a security decision.

---

## 1. What is installed

| Tool | Status | Install |
|---|---|---|
| Node.js | v20.20.0 (nvm); v24 LTS also available | `nvm install --lts` |
| CodexPro | **Installed, approved for local-only use** | `npm install -g codexpro` (v0.28.0) |
| DevSpace (`@waishnav/devspace`) | **NOT installed, NOT approved** (deferred) | — |

Install locations:
- CodexPro global package: `~/.nvm/versions/node/v20.20.0/lib/node_modules/codexpro`
- CodexPro CLI: `~/.nvm/versions/node/v20.20.0/bin/codexpro`
- Per-workspace profiles (only if you run `codexpro setup`): `~/.codexpro/`
  *(not created yet — validation ran the server directly)*

---

## 2. Approved AlphaLabs CodexPro mode

The **only** approved mode for this repo until explicitly changed:

- **Local-only** — server bound to `127.0.0.1`.
- **No tunnel** — no Cloudflare / ngrok / named tunnel / token URL / password URL.
- **Read-only first** — `--write off` and `--bash off`.
- **No write/edit** — file mutation tools disabled.
- **No bash** — shell execution disabled.
- **Extended blocked globs REQUIRED** — see `.ai/blocked-paths.md`.

Because the server is loopback-only, ChatGPT's web Developer Mode **cannot reach it**
without a public tunnel. End-to-end ChatGPT pairing is therefore **deferred** and
requires explicit, separate approval before any tunnel is enabled.

---

## 3. Operating commands

Always load nvm first in a fresh shell:
```bash
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
```

Always export the required blocklist before starting (see `.ai/blocked-paths.md`):
```bash
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'
```

### Start CodexPro (approved local-only, read-only)
```bash
codexpro start --root /Users/danielpak/AlphaLab \
  --tunnel none --host 127.0.0.1 --write off --bash off
```
Equivalent non-interactive server (used for validation; never tunnels):
```bash
codexpro-mcp-http --root /Users/danielpak/AlphaLab \
  --host 127.0.0.1 --port 8787 --write off --bash off
```

### Stop CodexPro
- Interactive launcher: press `q` or `Ctrl+C` in its terminal.
- Direct server: `Ctrl+C`, or `kill <pid>` of the `codexpro-mcp-http` process.

### Update CodexPro
```bash
npm install -g codexpro@latest
```

### Uninstall CodexPro
```bash
npm uninstall -g codexpro
rm -rf ~/.codexpro   # optional: removes saved profiles
```

### DevSpace
Deferred — see section 5. Do not run any DevSpace command.

---

## 4. Security posture (validated 2026-06-17)

- Server binds `127.0.0.1` only (verified via `lsof`); never `0.0.0.0`.
- `writeMode=off`, `bashMode=off`, `inheritEnv=false` confirmed via `server_config`.
- `.env` blocked by CodexPro's built-in rules.
- **Gap found & closed:** CodexPro's default blocklist does NOT cover `*.sqlite3`,
  `logs/`, `reports/`, `data/`, `credentials/`, `secrets/`. A small log/report/sqlite
  file is readable by default. The extended `CODEXPRO_BLOCKED_GLOBS` in
  `.ai/blocked-paths.md` blocks all of them by rule (verified).
- CodexPro redacts secret-looking strings from command output and does not inherit
  your shell env into subprocesses by default. No telemetry in source. Its only
  outbound network call is downloading `cloudflared`, which happens **only** in
  cloudflare-tunnel mode (not used here).

---

## 5. DevSpace — deferred status

- **Not installed. Not approved.**
- Only reconsider with **worktree / checkout-only isolation** (operate on a fresh
  git worktree so gitignored secrets are absent), and only after a source review of
  the mitigations.
- **Never point DevSpace at the live AlphaLabs working directory** unless explicitly
  approved. Rationale: it ships as a minified bundle, has no path blocklist (would
  not protect `.env`), inherits full env into subprocesses, has no read-only mode,
  persists loaded file contents to a local sqlite db, and depends on an unvetted
  agent engine.

---

## 6. Reusing this for other repos

1. Copy `TOOLING_HANDOFF.md` and the `.ai/` directory into the new repo.
2. Edit `.ai/project-context.md` for that project.
3. Keep `.ai/blocked-paths.md` (the extended globs) as the baseline; add
   project-specific sensitive paths.
4. Launch CodexPro with `--root <that repo>` — each repo is isolated by its own
   `--root`; never use `--allow-home` or a parent directory as the root.
