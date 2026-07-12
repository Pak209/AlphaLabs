# M4 Launch Operations — KYB, Counsel, Public Exposure

Written 2026-07-12, after M3-sandbox settled its first on-chain payment.
Three tracks separate the platform from real revenue. Each item is marked
**[HUMAN]** (only Pak can do it — accounts, identity, signatures, spend) or
**[AGENT]** (Claude/Codex can build or prepare it). Agent-assisted browser
sessions are available for any HUMAN item: the agent navigates and reads,
Pak types credentials and clicks the binding buttons.

## Track 1 — Coinbase business wallet + CDP KYB (gates M3-live)

Decision of record: all x402 revenue lands in a **dedicated business
wallet, never personal**.

1. **[HUMAN] Entity decision first.** KYB verifies a *business*. Decide
   sole-proprietor vs LLC before starting — sole prop works and is the
   fastest path; an LLC (formation docs + EIN, self-serve online services
   exist) adds liability separation and can be done later.
2. **[HUMAN] Gather KYB documents** (typical set — verify the current list
   on the CDP onboarding screen): legal business name + address, EIN (or
   SSN for sole prop), formation documents, beneficial-owner government ID,
   business description + website (the M4 landing page serves this).
3. **[HUMAN] Create the CDP account** at portal.cdp.coinbase.com and the
   business wallet; complete KYB in their flow. *Agent-assisted session
   offered: Claude drives Chrome to the right screens and explains each
   step; Pak enters all credentials/IDs and clicks every accept.*
4. **[AGENT] After approval:** wire `INTEL_X402_MODE=live` config — CDP
   facilitator base URL + auth (`INTEL_X402_FACILITATOR_BEARER`), mainnet
   `INTEL_X402_PAY_TO=<business wallet>`, and verify the mainnet EIP-712
   domain params (`extra`) against CDP docs (noted in intel_x402.py).
   One paid mainnet probe (a few real cents) is the acceptance test.

## Track 2 — Licensing posture: SELF-SERVE (decision of record 2026-07-12)

Counsel skipped deliberately. The posture manages the gray edges by
construction instead of by opinion, and it is ENFORCED IN CODE
(INTEL_COMMERCIAL_MODE + catalog pricing), not by policy memo:

- **Paid products** are engine-native or public-domain-sourced only:
  signal-evaluation, decision-explanation (caller inputs + our engine),
  SEC EDGAR catalysts, recomposed market-snapshot (engine regime only).
- **Pipeline telemetry is FREE during beta** (calibration, outcome-report,
  feature-attribution): a free research product minimizes any commercial
  derived-works reading while the funnel builds. Keys still required —
  metered and rate-limited, never anonymous.
- **Daily brief stays deferred** — the publisher's-exemption question is
  not worth self-navigating.
- **Buy licenses, not opinions**: CoinGecko Analyst (~$35/mo, explicit
  commercial license + attribution) when crypto context should return;
  Polygon commercial tier IF Polygon-derived paid products are ever
  wanted.
- **[HUMAN] The Polygon renewal (~Aug 9) is the real licensing decision**:
  cancel unless the daily PV-comparison evidence says Alpaca can't carry
  confirmation — going forward, no Polygon agreement means no Polygon
  derived-works exposure accruing.
- Revisit counsel only if: revenue becomes material, a vendor objects, or
  an enterprise customer requires representations.

## Track 3 — M4 public exposure (gated on Tracks 1–2 for paid; beta can precede)

Build-now items (no public exposure until DNS flips):

1. **[AGENT] api.pak-labs.com tunnel config** — separate hostname on the
   existing Cloudflare tunnel to :8790, **without** Access (auth is
   key/x402, not identity). Prepared config, not routed until go.
2. **[AGENT] intel LaunchAgent** — `com.alphalab.intel-api` so the intel
   app is a managed service like the dashboard (it currently runs manually).
3. **[AGENT] Landing/pricing page** — the rendered catalog + quickstart at
   the API root; doubles as the "business website" KYB wants.
4. **[AGENT] Status endpoint + uptime page**; key-faucet flow
   (first-100-calls-free) for the beta funnel.
5. **[AGENT] Registry submission drafts** — mcp.so, Smithery, Glama,
   PulseMCP, awesome-mcp-servers entries ready to paste.
6. **[HUMAN] The flips**: DNS route live, registry submissions (publishing),
   any Cloudflare WAF/rate-rule changes. Each is a two-minute click once
   the prepared pieces exist.

## Suggested order

Entity decision (sole prop is fine to start) → CDP KYB → agent builds
Track 3 items in parallel → beta (keys, tailnet/invite) → public flip when
Track 1 clears → Polygon renewal call ~Aug 9 with the PV evidence.
