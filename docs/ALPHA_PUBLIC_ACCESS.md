# alpha.pak-labs.com — public access design & runbook

Created 2026-07-08. Status: **tunnel staged, NOT exposed** — DNS deliberately
not routed until Cloudflare Access is in place (see "Why this order").

## Discovery (measured)

| Item | Value |
|---|---|
| Dashboard/API | `127.0.0.1:8787` (localhost-bound; tunnel is the only external path) |
| Existing tunnels | `codexpro-mini` → mcp-mini.pak-labs.com:8788 (untouched); `pakos` → :4180 (untouched) |
| New tunnel | `alphalabs`, id `bd34f2c8-d5f8-42e6-973f-b37e9c134dba` — **separate tunnel** so AlphaLabs exposure shares no blast radius with MCP |
| Connector | user LaunchAgent `com.alphalab.tunnel-alpha` (no sudo), KeepAlive, logs → `~/Library/Logs/alphalabs-tunnel.log`; registered to lax07/lax08 |
| Config | `~/.cloudflared/alphalabs.yml` → ingress `alpha.pak-labs.com` → `http://127.0.0.1:8787`, 404 fallback |

## Security review (why Access is mandatory, not optional)

- **Write endpoints** (approve/reject, paper-trade, imports, chat, config) are
  bearer-token-gated (`ALPHALAB_API_TOKEN`, hmac-compared) — but public DNS
  adds an internet-wide brute-force surface.
- **GET endpoints are open by design** (the dashboard renders without auth on
  the tailnet) and expose operator-sensitive data: positions and P/L, trades,
  execution audit, notification preferences, alerts, DB identity.
- Conclusion per the deployment constraints: **exposing the hostname without
  edge auth would leak data → stopped before DNS.** The safer option, now
  staged: Cloudflare Access in front of everything, plus connector-side JWT
  validation so the origin rejects non-Access traffic even if the edge app is
  later deleted or misconfigured (fail-closed at two layers). The app bearer
  token remains as the third layer for writes.

## Why this order (no unauthenticated window, ever)

1. ✅ Tunnel + connector staged with **no DNS record** — hostname does not
   resolve (verified: curl → no resolution).
2. ⬜ **Human:** create the Access application (steps below). Access apps can
   exist before DNS; the policy is live the instant the record appears.
3. ⬜ **Agent:** arm connector JWT validation with the app's AUD tag, restart
   connector, THEN route DNS. Verify. Public traffic therefore meets Access
   on its very first request.

## Human step — Cloudflare Zero Trust dashboard (~5 min)

one.dash.cloudflare.com → your team → Access → Applications → **Add an
application** → *Self-hosted*:

- Application name: `AlphaLabs`
- Session duration: `30 days` (PWA-friendly; approvals still re-auth monthly)
- Public hostname: `alpha.pak-labs.com` (exact host, path blank)
- Policy: name `owner-only`, action **Allow**, include → **Emails** →
  `dankimoto8@gmail.com` (add more later if needed)
- Identity: One-time PIN is zero-setup (email OTP); add Google/Apple login
  later if preferred.
- Save, then open the application's **Overview** tab and copy the
  **Application Audience (AUD) tag** and note your **team domain**
  (`<team>.cloudflareaccess.com`).

Give the agent the AUD tag + team domain.

## Agent step — arm and expose (after AUD received)

```bash
# 1. Arm connector-side JWT validation (fail-closed)
#    Uncomment the originRequest.access block in ~/.cloudflared/alphalabs.yml
#    filling teamName (the <team> part) and audTag, then:
launchctl kickstart -k gui/$(id -u)/com.alphalab.tunnel-alpha

# 2. Route DNS (THE exposure step)
~/.local/bin/cloudflared tunnel route dns alphalabs alpha.pak-labs.com
```

## Verification

```bash
# Unauthenticated request must meet Cloudflare Access, never the app:
curl -s -o /dev/null -w "%{http_code}\n" https://alpha.pak-labs.com/api/health   # expect 302 (Access login)
curl -sI https://alpha.pak-labs.com/ | grep -i "location\|cf-access"             # Access redirect headers
# In a browser: alpha.pak-labs.com -> email OTP -> dashboard renders.
# Writes still require the app bearer token even when Access-authenticated.
# Tailnet path unaffected: https://dans-mac-mini.tailc4ac76.ts.net/ still serves.
```

## Rollback (any single step reverses cleanly)

```bash
# Remove public exposure (DNS): delete the alpha CNAME in the Cloudflare DNS
# dashboard (or via API); Access app can stay (inert without DNS).
# Stop the connector:
launchctl bootout gui/$(id -u)/com.alphalab.tunnel-alpha
# Delete the tunnel entirely:
~/.local/bin/cloudflared tunnel delete alphalabs
```

## What this change does NOT touch

Trading behavior, scheduler, broker config, scoring, gates, telemetry, DB
schema, the MCP tunnel, the pakos tunnel, Tailscale serve, or the app's
localhost binding. The dashboard process itself is completely unaware of the
tunnel.
