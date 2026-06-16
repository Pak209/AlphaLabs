# AlphaLab two-Mac setup (dev → always-on runner)

A deliberately simple split: your **new MacBook (M4 Pro)** is where you build and
test and is the single source of truth; your **old MacBook** is a dedicated,
always-on machine that runs the scheduled paper-trading jobs. Updates flow one
way — new → old — over your home network with `rsync`. No Docker, no cloud, no
CI, no GitHub required.

```
NEW MacBook (dev, source of truth)            OLD MacBook (runner, always on)
  ~/AlphaLab  ──deploy_to_old_mac.sh──rsync/ssh──▶  ~/AlphaLab
                                                     ├─ .venv      (its own)
  check_old_mac.sh ──────ssh────────────────────▶   ├─ .env       (its own keys)
                                                     ├─ logs/      (its own)
                                                     ├─ data/*.sqlite3 (its own history)
                                                     └─ launchd schedule → 06:32 weekdays
```

The deploy **never** overwrites the old Mac's `.env`, `.venv`, `logs/`, or
SQLite database — those stay local to the server.

## Folder layout (same on both Macs)

```
~/AlphaLab/
├── alpha_lab/                 # research/scoring package
├── paper_trader/              # trading package (paper-only)
├── scripts/
│   ├── setup_old_mac.sh       # ① run ONCE on the OLD Mac
│   ├── deploy_to_old_mac.sh   # run on the NEW Mac to push code
│   ├── check_old_mac.sh       # run on the NEW Mac to check health
│   ├── run_options_validation.sh  # the job launchd runs each morning
│   ├── server.conf.example    # template for connection settings
│   └── server.conf            # YOUR host/user (git-ignored, not deployed)
├── deploy/
│   └── com.alphalab.options-validation.plist.template  # launchd schedule
├── docs/server-setup.md       # this file
├── logs/                      # run logs (server-local, git-ignored)
├── requirements.txt
├── .env.example
└── .env                       # secrets (git-ignored, never overwritten)
```

---

## One-time setup

### On the OLD MacBook (the runner)

1. **Name it & set timezone.** System Settings → General → About → set a memorable
   name (e.g. `old-macbook`; its network address becomes `old-macbook.local`).
   Then Date & Time → set timezone to **America/Los_Angeles** (the 06:32 schedule
   depends on this).

2. **Enable Remote Login (SSH).** System Settings → General → Sharing → turn on
   **Remote Login**. Note the username shown.

3. **Install standalone Python.** Download the macOS installer from
   <https://www.python.org/downloads/macos/> (3.11 or 3.12), or `brew install python`.
   Do **not** rely on Xcode's Python for a server.

4. **Plug it in** to AC power and connect to your network (Ethernet preferred; Wi-Fi is fine).

### On the NEW MacBook (dev)

5. **Set up SSH key login** so deploys don't prompt for a password each time:
   ```bash
   ssh-keygen -t ed25519        # press Enter through the prompts if you have no key yet
   ssh-copy-id you@old-macbook.local
   ssh you@old-macbook.local 'echo connected'   # should print without a password
   ```

6. **Configure the connection** once:
   ```bash
   cd ~/AlphaLab
   cp scripts/server.conf.example scripts/server.conf
   # edit scripts/server.conf → set SERVER_USER and SERVER_HOST to the old Mac
   ```

7. **First deploy** (pushes code to the old Mac):
   ```bash
   ./scripts/deploy_to_old_mac.sh
   ```

8. **Get the old Mac's `.env` in place.** The deploy intentionally skips secrets.
   Copy your keys over once (or create the file directly on the old Mac):
   ```bash
   scp ~/AlphaLab/.env you@old-macbook.local:AlphaLab/.env
   ```

9. **Run the server setup** — SSH in and run it on the old Mac:
   ```bash
   ssh you@old-macbook.local
   cd ~/AlphaLab && ./scripts/setup_old_mac.sh
   ```
   This rebuilds the venv, locks down `.env`, installs + loads the launchd
   schedule, applies power settings (you'll be asked for the admin password once),
   and prints a verification including a live dry-run of the trade chain.

10. **Verify from the dev Mac:**
    ```bash
    ./scripts/check_old_mac.sh
    ```
    Expect: reachable, schedule loaded, won't-sleep, auto-restart ON, venv present.

You're done. The runner fires automatically each weekday at 06:32 local.

---

## Day-to-day

| Goal | On which Mac | Command |
|------|--------------|---------|
| Build / test / iterate | New | normal editing + `.venv/bin/python -m pytest` |
| Preview a deploy (no changes) | New | `./scripts/deploy_to_old_mac.sh --dry-run` |
| Push code to the runner | New | `./scripts/deploy_to_old_mac.sh` |
| Check the runner is healthy | New | `./scripts/check_old_mac.sh` |
| Check health + see last log | New | `./scripts/check_old_mac.sh --logs` |
| Force a test run now | Old (ssh) | `cd ~/AlphaLab && ./scripts/run_options_validation.sh --allow-closed` |
| Reload the schedule after a plist change | Old (ssh) | `./scripts/setup_old_mac.sh` |

Routine code edits (Python/strategy logic) need **no** restart on the server —
the next scheduled run picks them up. Only changes to the schedule itself (the
plist template) require re-running `setup_old_mac.sh`.

---

## Testing / verification cheatsheet

- **Deployment test:** `./scripts/deploy_to_old_mac.sh --dry-run` — shows exactly
  what would change, touches nothing.
- **Manual run test (on the server):** `./scripts/run_options_validation.sh --allow-closed`
  — exercises signal → option-select end-to-end without placing an order when the
  market is closed. Expect `Pre-flight / Signal gen / Option select` all PASS.
- **Health check:** `./scripts/check_old_mac.sh` — green across the board means
  reachable, scheduled, awake-on-AC, auto-restarting, venv ready.

---

## Risks & macOS gotchas (read these once)

1. **TCC / protected folders.** Keep AlphaLab in `~/AlphaLab`, never under
   `~/Desktop`, `~/Documents`, or `~/Downloads`. macOS blocks launchd background
   jobs from reading file *contents* in those folders without Full Disk Access —
   that's the exact bug that broke the schedule before the project was relocated.

2. **FileVault + unattended reboot (the big one).** A LaunchAgent only runs while a
   user is **logged in**. If FileVault is on, a reboot after a power outage stops
   at the disk-unlock screen and nothing runs until someone types the password.
   For an unattended home server, either turn **FileVault off**, or enable
   **automatic login** (System Settings → Users & Groups → Automatically log in as…).
   Auto-login trades some physical security for unattended restart — reasonable for
   a home runner, your call. `autorestart 1` only helps if the Mac can reach the
   desktop on its own.

3. **Clamshell (lid-closed) sleep.** A MacBook normally sleeps when the lid closes.
   `setup_old_mac.sh` runs `sudo pmset -a disablesleep 1`, which keeps it awake lid
   closed. If you'd rather, leave the lid open. Keep it on **AC** — `pmset -c`
   settings only apply on power; on battery it will still sleep.

4. **Standalone Python, not Xcode's.** Rebuild the venv on the server with a
   python.org/Homebrew Python. A venv copied from the dev Mac points at absolute
   paths that won't exist on the other machine — `setup_old_mac.sh` rebuilds it
   from `requirements.txt` instead, which is why `.venv/` is excluded from deploys.

5. **Timezone drift.** The schedule is 06:32 *local* time, chosen to equal ~09:32
   ET. If the old Mac's timezone isn't America/Los_Angeles, the job fires at the
   wrong moment. `check_old_mac.sh` flags this.

6. **rsync `--delete`.** The deploy mirrors your dev tree, so files you delete on
   the dev Mac are removed on the server too — *within synced code only*. `.env`,
   `.venv`, `logs/`, and the database are excluded and therefore protected. Always
   run `--dry-run` first if unsure; the default flow previews and asks before
   applying.

7. **Network address changes.** `.local` Bonjour names usually just work. If the
   old Mac becomes unreachable, give it a reserved IP in your router's DHCP
   settings and use that for `SERVER_HOST`.

8. **Missed runs on wake.** If the Mac is asleep at 06:32, launchd runs the missed
   job once on the next wake (`StartCalendarInterval` behavior). With sleep
   disabled on AC this shouldn't happen, but it's a safe fallback.

9. **Secrets hygiene.** `.env` is git-ignored, excluded from deploys, and chmod-600
   on the server. Don't email/AirDrop it; use `scp` over your LAN as shown.

---

## Future expansion (structure only — not built yet)

The same one-way deploy + launchd pattern extends cleanly to additional jobs:
alpha scanners, catalyst/news agents, market summaries, broader paper trading,
Alpaca execution, and ML data collection. Each becomes another wrapper script
under `scripts/` plus its own plist in `deploy/`, installed by extending
`setup_old_mac.sh`. Deployment, monitoring, and secrets handling stay identical.
Don't build these yet — the minimum reliable runner above is the foundation.
