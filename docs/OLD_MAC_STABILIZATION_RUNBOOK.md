# Old Mac Stabilization Runbook

Use this after the AirDrop-to-GitHub re-host, after any reboot, and before the
first market-hours check of the day. It is intentionally operational and safe:
no secrets are printed here, no live trading is enabled, and the live SQLite DB
is never moved.

## Stabilization Checklist

Goal: keep the old Mac observable while avoiding accidental scheduler-triggered
paper orders during the post-migration window.

1. From the dev Mac, confirm the current state:
   ```bash
   git status --short --branch
   git rev-parse HEAD
   ./ops remote-status
   ./ops safety-status
   ./ops health
   ```
2. Read the safety line:
   - `safe stabilization mode: true` means the scheduler is `dry_run` and the
     automation paper-trade guard is disarmed.
   - `paper trades can be triggered by scheduler jobs: true` means both
     `ALPHALAB_SCHEDULER_MODE=paper` and
     `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true` are active.
3. Recommended stabilization posture:
   - `ALPHALAB_SCHEDULER_MODE=dry_run`
   - `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES` unset or not `true`
4. Do not edit `.env` from Codex. If an operator intentionally changes `.env`,
   restart the scheduler afterward:
   ```bash
   ssh <old-mac> 'launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler'
   ```
5. Re-check:
   ```bash
   ./ops safety-status
   ./ops remote-status
   ./ops health
   ```

`./ops deploy`, `./ops start`, `./ops restart`, and `./ops reload` refuse to
reload services when scheduler paper jobs are fully armed. That refusal is a
stabilization guardrail, not a deployment failure.

## Morning Verification Checklist

Run before trusting the dashboard, scheduler, or phone PWA for the day:

```bash
./ops remote-status
./ops safety-status
./ops health
./ops check polygon
./ops check sec
./ops check alpaca
```

Expected healthy signals:

- SSH reachable over Tailscale or LAN.
- Dashboard LaunchAgent running.
- Scheduler LaunchAgent running.
- Scheduler heartbeat is fresh.
- `/api/health`, `/api/db-status`, and `/api/catalysts/intelligence` return
  HTTP 200 inside `./ops health`.
- Dashboard API DB path matches the resolver path.
- Scheduler heartbeat DB path matches the resolver path.
- Scheduler job count is 18 unless the job set was intentionally changed.
- Polygon check returns HTTP 200, 401, or 403; 200 is best, 401/403 still prove
  endpoint reachability but require key review.
- SEC EDGAR check returns HTTP 200.
- Alpaca paper account check returns HTTP 200.

If any same-DB proof fails, stop feature work and resolve that first.

## Old Mac Reboot Recovery

After a reboot or power event:

1. Wait for the old Mac to auto-login and join Tailscale.
2. From the dev Mac:
   ```bash
   ./ops doctor
   ./ops remote-status
   ./ops health
   ```
3. If SSH is unavailable, check the old Mac physically:
   - It is powered on and awake.
   - Tailscale is running and signed in.
   - System Settings -> General -> Sharing -> Remote Login is on.
4. If LaunchAgents are not loaded:
   ```bash
   ./ops status
   ./ops start
   ```
   `./ops start` will refuse if scheduler paper jobs are fully armed. In that
   case, either intentionally disarm stabilization mode first or start services
   manually only after confirming paper automation is intended.
5. Confirm the scheduler stamped a new heartbeat:
   ```bash
   ./ops remote-status
   ```

## Tailscale Serve / PWA Checklist

The dashboard should stay bound to `127.0.0.1:8787`. Do not bind it to
`0.0.0.0` for phone access.

On the old Mac:

```bash
tailscale serve status
```

If Serve is missing and phone/PWA access is needed:

```bash
tailscale serve --bg 127.0.0.1:8787
tailscale serve status
```

Then on the iPhone:

- Confirm the Tailscale app is connected.
- Open the HTTPS MagicDNS URL from `tailscale serve status`.
- In Safari, use Add to Home Screen for the PWA.
- Keep `ALPHALAB_API_TOKEN` configured for write protection when exposing the
  dashboard through tailnet HTTPS.

To disable Serve:

```bash
tailscale serve --https=443 off
```

## Rollback Checklist

Rollback is code-only unless an operator explicitly chooses to restore a DB
backup. Do not overwrite or move the live DB as part of ordinary code rollback.

1. Stop services before moving project trees or restoring a backup tree:
   ```bash
   ./ops stop
   ```
2. On the old Mac, inspect the retained backup tree and current checkout:
   ```bash
   ls -ld ~/AlphaLab*
   cd ~/AlphaLab
   git status --short --branch
   git log --oneline -10
   ```
3. For a code rollback:
   ```bash
   git checkout <known-good-commit>
   .venv/bin/python -m pip install -r requirements.txt
   ```
4. Start services and verify:
   ```bash
   ./ops start
   ./ops health
   ```
5. Return to latest main when ready:
   ```bash
   git checkout main
   git pull --ff-only origin main
   ```

## Hard Warning: Do Not Move A Live Checkout

Never run `mv ~/AlphaLab ...` while `com.alphalab.dashboard` or
`com.alphalab.scheduler` is running.

launchd processes can keep using the old directory inode after a rename. That
creates split-brain behavior: the running services may keep writing the renamed
tree's SQLite DB while new shells and scripts resolve `~/AlphaLab` to a different
DB. `./ops health` catches this with the same-DB proof, but prevention is better.

Safe relocation order:

```bash
./ops stop
# move or restore project trees only while services are stopped
./ops start
./ops health
```

