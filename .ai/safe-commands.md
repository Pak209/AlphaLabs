# Safe Commands — AlphaLabs

In the **approved mode** (`--bash off`), CodexPro executes **no** shell commands at
all. This file documents (a) the launch commands a human runs to operate the tool,
and (b) the read-only inspection actions that are safe should bash ever be enabled
later under explicit approval.

## Launch (human-run, approved mode)
```bash
# 1) load Node
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

# 2) REQUIRED blocklist (see blocked-paths.md)
export CODEXPRO_BLOCKED_GLOBS='*.sqlite3,*.sqlite,*.db,**/*.sqlite3,**/*.sqlite,**/*.db,logs,logs/**,**/logs/**,reports,reports/**,**/reports/**,data,data/**,**/data/**,credentials,credentials/**,**/credentials/**,secrets,secrets/**,**/secrets/**'

# 3) start local-only, read-only, no tunnel
codexpro start --root /Users/danielpak/AlphaLab \
  --tunnel none --host 127.0.0.1 --write off --bash off
```

## Safe read-only inspection (allowed)
These are non-mutating and safe. In approved mode they are performed via CodexPro's
dedicated read tools, NOT via bash:
- View file tree / list files.
- Read individual non-blocked text files.
- Search code (text/regex).
- `git status`, `git diff`, `git log`, `git show` (read-only history/inspection).

## NEVER run (even if bash is later enabled)
- Anything that places or simulates trades, or touches the broker/order path.
- Anything that starts/loads `launchd` jobs or scheduled runs
  (`launchctl load/start/...`).
- Mutating git ops: `git push`, `git reset`, `git checkout/switch/restore`, `git clean`.
- Destructive shell: `rm`, `mv`, `cp -f`, `chmod`, `chown`, `kill`/`pkill`.
- Network/exfil: `curl`, `wget`, `ssh`, `scp`, `rsync`.
- Package publish or global installs.
- Reading sensitive files via shell (`cat .env`, dumping the sqlite db, etc.).

> Note: CodexPro's built-in `safe` bash mode already blocks most of the above, but the
> approved AlphaLabs mode keeps bash **off** entirely.
