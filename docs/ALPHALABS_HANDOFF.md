# AlphaLab — Handoff

> Living status document. **Update after every major milestone.**
> Last updated: **2026-06-16** — Milestone: *Old Mac re-hosted on a GitHub-backed checkout (AirDrop copy → clean clone), split-brain DB fixed, remote access via Tailscale Serve.* Prior same-day milestone: *Crypto execution fixes + multi-coin (BTC/LINK/HYPE) idea generation. See [`HANDOFF_2026-06-16.md`](./HANDOFF_2026-06-16.md).*

For the deep explanation of scoring, the hard gate, modifiers, no-data behavior,
and real-vs-stub APIs, see [`scoring-and-signals.md`](./scoring-and-signals.md).

---

## Executive Summary

**Purpose:** AlphaLab is a catalyst-first AI research and paper-trading system.

**Core philosophy:**

```
Catalyst
  → Price/Volume Confirmation
  → Options/Dark Pool Confirmation
  → Risk Engine
  → Paper Trade
```

Options and Dark Pool data are **conviction modifiers only** — they can raise
conviction on a confirmed idea but can never trigger a trade on their own.

Paper / dry-run only. No live brokerage orders.

---

## Current Architecture

| Component | Role |
| --------- | ---- |
| SEC / Polygon / Benzinga / Tiingo / Newsfilter | Catalyst & news ingestion (live-capable) |
| Research / Narrative agents | Theme, sector, and narrative scoring |
| Options Flow agent | Unusual options scoring (stub provider today) |
| Dark Pool / TRF agent | Institutional participation scoring (stub provider today) |
| Scoring engine | Six-component composite + hard gate |
| Risk engine | Gates trades on confidence / RiskConfig |
| Paper Trader | Alpaca paper / simulated broker (decoupled package) |
| Dashboard | FastAPI + vanilla JS, signal-breakdown audit panel |
| MCP connector | Pure-stdlib stdio JSON-RPC server (`alpha_lab/mcp_server.py`) exposing read + dry-run-only write tools to MCP clients (Claude Cowork) |
| Automation scheduler | `alpha_lab/scheduler.py` — market-hours cron (catalyst poll + daily-brief import/test). Dry-run by default; paper via one env flag |

Two decoupled packages: `alpha_lab/` (research/scoring) and `paper_trader/`
(execution — no `alpha_lab` imports).

---

## Deployment (dedicated always-on server)

Runs on a dedicated Mac server (Intel/macOS; set the SSH user/host in
`scripts/server.conf`), project at `~/AlphaLab`. Hardened for unattended uptime:

- **GitHub-backed layout.** The server's `~/AlphaLab` is a real Git checkout of
  `Pak209/AlphaLabs` (origin `main`), bootstrapped/updated by
  `scripts/bootstrap_old_mac_from_github.sh` (idempotent: clones if missing,
  ff-only pull, builds `.venv`, installs `requirements.txt`, ensures runtime
  dirs, chmod 600 `.env`, runs `db_status`). It refuses to pull a dirty source
  tree, so runtime state (`.env`, `alpha_lab/data/`, `logs/`, `reports/`) stays
  local and untouched.
- **`./ops` orchestrator** (dev Mac → server over Tailscale/SSH, config in
  `scripts/server.conf`): `doctor` (SSH + checkout + venv readiness),
  `remote-status`, `health` (full server-side verifier incl. same-DB proof),
  `deploy`, and confirmed state changes `start` / `stop` / `restart` / `reload`.
- **Dashboard API** — `com.alphalab.dashboard` LaunchAgent (KeepAlive + RunAtLoad)
  on `127.0.0.1:8787`, via `scripts/run_dashboard.sh` (sources `.env`).
- **Automation scheduler** — `com.alphalab.scheduler` LaunchAgent (KeepAlive),
  via `scripts/run_scheduler.sh`. Template: `deploy/com.alphalab.scheduler.plist.template`.
- **Scheduled validator** — `com.alphalab.options-validation`, weekdays 06:32 PT.
- Power: no sleep on AC + clamshell (`pmset disablesleep 1`); FileVault off +
  auto-login so it self-recovers after a reboot. (`autorestart` N/A on a laptop —
  battery rides through outages; a multi-hour outage that drains the battery
  needs a manual power-on.)
- Remote health from the dev Mac: `./ops health` (or legacy
  `./scripts/check_old_mac.sh`) over key-based SSH (config in `scripts/server.conf`).

> **Gotcha — never `mv ~/AlphaLab` while the agents are running.** The launchd
> services hold the project directory by inode, so renaming it out from under a
> live process makes the running dashboard/scheduler keep reading/writing the
> *renamed* path's DB while the resolver points at the new `~/AlphaLab` — a
> **split-brain DB** (caught by `./ops health`'s same-DB proof). Correct order
> when relocating: **`./ops stop` → move/sync files → `./ops start`** (a fresh
> launch re-resolves `~/AlphaLab`). If you only renamed, copy the authoritative
> DB from the old path into the clone *before* restarting.

### Remote access (dashboard / PWA)

The dashboard binds **loopback only** (`127.0.0.1:8787`); `alpha_lab/main.py`
refuses any non-loopback bind unless `ALPHALAB_ALLOW_PUBLIC_BIND=true`. Reach it
remotely without changing the bind:

- **Dev Mac — SSH tunnel:** `ssh -N -L 8787:127.0.0.1:8787 <user>@<tailscale-ip>`,
  then open `http://127.0.0.1:8787` (localhost = secure context, PWA installable).
- **Phone + Dev Mac — Tailscale Serve** (run once on the server):
  `tailscale serve --bg 127.0.0.1:8787` → yields a tailnet-only HTTPS URL
  (`https://<magic-dns>.ts.net`). HTTPS = secure context, so the iPhone PWA
  (`alpha_lab/static/sw.js` + `manifest.webmanifest`) installs via Safari →
  Add to Home Screen. Requires the Tailscale app active on the phone. Undo with
  `tailscale serve --https=443 off`.

### Automation modes — Pattern B vs C (one-flag switch)

`ALPHALAB_SCHEDULER_MODE` in `~/AlphaLab/.env` controls the scheduler:

| Value | Pattern | Behavior |
| ----- | ------- | -------- |
| `dry_run` (default) | **B** | Generate + score ideas all day; **place no orders**. |
| `paper` | **C** | Idea-testing jobs place Alpaca **paper** orders. |

Paper orders *also* require `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true`
(enforced in `import_and_test`) — two flags must agree, so flipping the mode
alone cannot place orders unless automation is armed. To switch:
edit `.env`, then `launchctl kickstart -k gui/$(id -u)/com.alphalab.scheduler`.

---

## Scoring Formula

```
35%  Catalyst
20%  Price / Volume Confirmation
15%  Narrative
15%  Options Flow            (conviction modifier)
10%  Institutional / Dark Pool (conviction modifier)
 5%  Macro
```

Components with no provider data are dropped and the remaining weights are
renormalized, so no-data is neutral.

---

## Hard Gate Rules

An idea is **confirmed** only when **both**:

```
Catalyst score        ≥ 40
Price/Volume score    ≥ 55
```

If not confirmed but options/institutional data are present:

```
→ Options component       excluded from the blend
→ Institutional component excluded from the blend
→ Composite capped at 69.9 (tier capped at Watchlist)
→ gate_applied = True, floors_applied += "confirmation_gate"
```

An idea with no options/institutional data at all is **not** gated.

---

## APIs

**Real / live-capable (env-key gated, sample fallback when key absent):**

- SEC EDGAR — `SEC_USER_AGENT`
- Polygon — `POLYGON_API_KEY`
- Benzinga — `BENZINGA_API_KEY`
- Tiingo — `TIINGO_API_KEY`
- Newsfilter — `NEWSFILTER_API_KEY`
- Alpaca (paper broker / account / quotes) — `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`
- Anthropic (LLM analyst) — `ANTHROPIC_API_KEY`

**Stubbed (no real feed wired yet — return no-data → neutral):**

- Options Flow provider — `StubOptionsFlowProvider`
- Dark Pool / TRF provider — `StubDarkPoolProvider`

> No FMP or Unusual Whales integration exists in the code today; a real
> options/TRF vendor still needs to be selected (see Open Decisions).

---

## Current Status

**Completed**
- ✓ Options Flow agent (point system, provider interface + stub)
- ✓ Dark Pool / TRF agent (tiered scoring, provider interface + stub)
- ✓ Price/Volume confirmation component
- ✓ Composite rewrite (35/20/15/15/10/5) with hard gate
- ✓ DB migration + trade logging of all signal metrics
- ✓ Dashboard signal-breakdown audit panel (trades + catalyst cards)
- ✓ MCP connector (pure-stdlib stdio JSON-RPC) + Cowork integration guide
- ✓ Tests: agents, composite, gate, dashboard data contract, MCP handshake/safety (85 green)

**Stubbed**
- ○ Options Flow provider (no real feed)
- ○ Dark Pool provider (no real feed)

**Not started**
- ○ Real options-flow feed integration
- ○ Real TRF / dark-pool feed integration
- ○ Live intraday price/volume feed (price/volume currently conservative)

---

## Open Decisions

- Which **options-flow data vendor** to wire into `OptionsFlowProvider`.
- Which **dark-pool / TRF vendor** to wire into `DarkPoolProvider`.
- Whether to **re-tune the 15% / 10% modifier weights** after live testing.
- **Cowork connector registration path** — the standard `mcpServers` JSON block
  is used, but where Cowork specifically reads it from is not yet documented
  publicly (see [`cowork-integration.md`](./cowork-integration.md)).

---

## Next Priorities

1. Verify Polygon integration end-to-end.
2. Verify Alpaca paper trading end-to-end.
3. Dry-run testing across a basket of confirmed ideas.
4. Paper-trade evaluation and P/L review.
5. Add a real options-flow feed (activate the modifier).
6. Add a real dark-pool / TRF feed (activate the modifier).

---

## Changelog

- **2026-06-16** — Old Mac re-hosted on a GitHub-backed checkout + split-brain DB
  fix + remote-access hardening. **No trading logic / scoring / schema changes.**
  The server's `~/AlphaLab` was an AirDrop copy (no `.git`); converted it to a
  clean clone of `Pak209/AlphaLabs` without losing state: renamed the old tree to
  a timestamped backup, cloned fresh, restored `.env` (600), `logs/`, `reports/`,
  and the live SQLite DB + `audit.jsonl`, then rebuilt the venv via
  `scripts/bootstrap_old_mac_from_github.sh`. **`./ops health` caught a split-brain
  DB:** the 2-day-old dashboard/scheduler LaunchAgents had followed the renamed
  backup directory by inode and were still writing its DB, while the resolver
  pointed at the new clone. Fixed with `./ops stop` → copy the authoritative
  (newer) DB from the backup into the clone → `./ops start`; re-ran `./ops health`,
  all hard checks green (same-DB proof, 18 scheduler jobs, dashboard on
  `127.0.0.1:8787`, fresh heartbeat). **Remote access:** confirmed loopback-only
  bind; enabled Tailscale Serve on the server for a tailnet-only HTTPS URL so the
  PWA installs on the iPhone (SSH tunnel remains the Dev-Mac fallback). See the
  Deployment section's gotcha + remote-access notes. Backup tree retained as a
  rollback safety net. Open item: scheduler still on `ALPHALAB_SCHEDULER_MODE=paper`
  — recommend `dry_run` for the post-migration stabilization window, then flip back.
- **2026-06-16** — Crypto execution + multi-coin milestone (full detail:
  [`HANDOFF_2026-06-16.md`](./HANDOFF_2026-06-16.md)). **Trading behavior:
  CHANGED.** Driven by a hard Alpaca constraint confirmed this session: crypto is
  **long-only** (no shorting) and **SOL/XRP are not supported**.
  (1) **Crypto price routing** — `paper_trader/alpaca_client.py`
  `get_latest_trade_price` now routes slash-pairs (`BTC/USD`) to Alpaca's
  `v1beta3/crypto/us/latest/trades` market-data endpoint (new
  `_latest_crypto_trade_price`); previously it only hit the equities endpoint and
  returned `None` for crypto, breaking any price-dependent crypto path.
  (2) **Honest crypto-short rejection** — `decision_engine.py` now rejects bearish
  crypto up front with "Alpaca does not support shorting crypto (crypto is
  long-only)" instead of the misleading late "latest price required" error.
  (3) **Multi-coin generation** — generalized the BTC-only generator to a small
  Alpaca-tradeable universe **BTC / LINK / HYPE**. `market_data.py` gains a
  `CRYPTO_COINS` registry and `get_crypto_market(ticker)` (BTC kept as a wrapper);
  the BTC-baked text helpers are parameterized by symbol/name. `service.py`
  `_btc_signal_from_market` now derives identity from the market dict;
  `poll_weekend_crypto` loops all 3 coins (per-coin dedupe + graceful skip);
  added `_generate_crypto_idea` + `generate_after_hours_crypto_ideas`.
  `config.example.json` crypto `approved_tickers`: dropped SOL/BNB (untradeable),
  added HYPE. Tests: **189 green** (updated 2 `test_api.py` mocks to patch
  `get_crypto_market`). **Not yet deployed.** Open decisions: CoinGecko free-tier
  rate-limit on 6 uncached GETs/poll; the after-hours UI/API route is still
  BTC-only (`generate_after_hours_crypto_ideas` unwired); ETH/DOGE are approved
  but not in the generation registry.
- **2026-06-14** — Phone/PWA milestone: weekend crypto jobs, real intraday
  price/volume feed, Analyst Chat, and opt-in API auth. **Trading behavior:
  CHANGED.** Two changes affect what gets traded:
  (1) **Weekend coverage** — `scheduler.py` adds two `sat,sun` jobs
  (`poll_weekend_crypto` every 30 min + a 3×/day weekend market briefing), so
  weekend catalysts (e.g. crypto-moving geopolitics) are no longer missed by the
  prior mon-fri-only cadence. Job count 11→13.
  (2) **The hard gate now bites** — `_price_volume_inputs` was always returning
  empty (every idea scored 50 < the 55 gate, so price/volume never confirmed).
  It now pulls a real Polygon/Massive intraday snapshot via
  `live_sources.fetch_polygon_intraday` (env-gated on `POLYGON_API_KEY`).
  Critically, `relative_volume` only counts when price action *confirms the
  thesis direction* (`trend_confirms is True`) — volume backing a move *against*
  the thesis stays neutral and can't clear the gate (fixed a real flaw caught in
  test: 5× volume on a contrary move was wrongly scoring 68). A 0.25% gap
  deadband ignores noise. Non-equity/option ideas and feed misses fall back to
  the prior empty/neutral behavior, so no regression when the key is unset.
  **New surfaces (no execution authority):** PWA (manifest + network-first
  service worker at `/sw.js` + icons) so the dashboard installs on the phone
  over Tailscale; **Analyst Chat** (`/api/chat` → `analyst.chat_reply`,
  advisory-only, grounded on live catalysts/ideas/brief, cannot place or approve
  trades). **API auth (opt-in):** new `ALPHALAB_API_TOKEN` — when set, a FastAPI
  middleware requires `Authorization: Bearer <token>` on all non-GET requests
  (writes/approvals/execution) via `hmac.compare_digest`; GETs and health stay
  open so the dashboard still renders. Unset = unchanged dev behavior. The dash
  (`app.js`) stores the token in localStorage and prompts+retries once on 401;
  the MCP server attaches it from env. This is the prerequisite for safe
  phone-based trade approvals. New files: `test_price_volume_feed.py`,
  `test_api_auth.py`, `docs/futures-integration-plan.md` (futures = paid Polygon
  product, not Alpaca-paper-tradeable → signal/context input, not a tradeable;
  phased proposal, decision pending). Tests: 110 green.
- **2026-06-14** — Dedicated always-on server live + automation scheduler with a
  Pattern B/C switch. The old MacBook now runs the dashboard and (new)
  `com.alphalab.scheduler` LaunchAgent. `alpha_lab/scheduler.py` refactored:
  added `automation_mode()` / `build_scheduler()`, and a new env flag
  `ALPHALAB_SCHEDULER_MODE` (`dry_run` default = B, `paper` = C). New files:
  `scripts/run_scheduler.sh`, `deploy/com.alphalab.scheduler.plist.template`,
  `alpha_lab/tests/test_scheduler.py`. Tests: 96 green.
  **Trading behavior: CHANGED — but gated and OFF by default.** The scheduler can
  now place automated Alpaca *paper* orders, but ONLY when BOTH
  `ALPHALAB_SCHEDULER_MODE=paper` AND `ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true`.
  Default (`dry_run`) places nothing. No change to scoring, the hard gate, or any
  signal. New open decision: when to graduate B→C, and whether to set
  `ALPHALAB_REQUIRE_PAPER_APPROVAL=true` before doing so.
- **2026-06-12** — AlphaLab MCP connector shipped (`alpha_lab/mcp_server.py`):
  pure-stdlib JSON-RPC 2.0 over stdio, zero dependencies, talks HTTP to the
  running API. Exposes read tools (dashboard, ideas, approvals, trades, daily
  brief, radar, explanation) and **dry-run-only** write tools (`import_catalyst`,
  `import_idea`) — `execution_mode` is stripped and pinned to `dry_run`; no
  approval/paper/live endpoints are exposed. Added Cowork integration guide
  (`docs/cowork-integration.md`) covering the 3 patterns + guardrails. Tests:
  `test_mcp_server.py` (handshake, tools/list shape, routing, dry-run safety) —
  full suite 85 green. **Trading behavior unchanged** (research/draft only; human
  approval still required for any paper execution). New open decision: Cowork
  connector registration path.
- **2026-06-11** — Options Flow + Dark Pool signal sources shipped as conviction
  modifiers; composite reweighted to 35/20/15/15/10/5 with the confirmation hard
  gate; signal metrics persisted on trades; dashboard signal-breakdown audit panel
  added (gate status, included/excluded modifiers, no-data indicators). Docs added.
