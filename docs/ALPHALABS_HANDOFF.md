# AlphaLab — Handoff

> Living status document. **Update after every major milestone.**
> Last updated: **2026-06-14** — Milestone: *Phone/PWA + Analyst Chat + opt-in API auth; weekend crypto jobs and a real intraday price/volume feed that makes the hard gate bite.*

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

- **Dashboard API** — `com.alphalab.dashboard` LaunchAgent (KeepAlive + RunAtLoad)
  on `127.0.0.1:8787`, via `scripts/run_dashboard.sh` (sources `.env`).
- **Automation scheduler** — `com.alphalab.scheduler` LaunchAgent (KeepAlive),
  via `scripts/run_scheduler.sh`. Template: `deploy/com.alphalab.scheduler.plist.template`.
- **Scheduled validator** — `com.alphalab.options-validation`, weekdays 06:32 PT.
- Power: no sleep on AC + clamshell (`pmset disablesleep 1`); FileVault off +
  auto-login so it self-recovers after a reboot. (`autorestart` N/A on a laptop —
  battery rides through outages; a multi-hour outage that drains the battery
  needs a manual power-on.)
- Remote health from the dev Mac: `./scripts/check_old_mac.sh` over key-based SSH
  (config in `scripts/server.conf`).

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
