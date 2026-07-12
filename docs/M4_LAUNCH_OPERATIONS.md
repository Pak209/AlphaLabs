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
   sole-proprietor vs LLC before starting — an LLC needs formation docs +
   EIN and is also what counsel will likely recommend for a data-services
   business (Track 2 asks them; do these in the same week).
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

## Track 2 — Licensing counsel sign-off (gates public launch)

An agent cannot provide sign-off; it CAN make the engagement cheap. The
brief below turns an open-ended review into ~one billable hour.

1. **[HUMAN] Engage counsel** (data-licensing / fintech familiarity).
2. **[AGENT — prepared] The briefing package** is docs/COMMERCIAL_LAUNCH_REVIEW.md
   (risk matrix + terms analysis). The specific questions needing answers:
   - Does Polygon's individual-plan "Derived Works" clause reach products
     built from OUR pipeline's decisions *about* vendor-sourced events
     (calibration, outcome-report, feature-attribution) — telemetry that
     contains no vendor data, only our engine's scores and results?
   - Same question for Alpaca's redistribution terms re: paper-trading
     outcome aggregates.
   - Does the compiled daily brief qualify for a publisher's exemption
     once vendor quotes are removed (or is it dead until licensed)?
   - Is SEC-EDGAR-only catalysts + attribution posture clean as built?
   - Entity/liability: right structure for selling research signals with
     "not investment advice" disclaimers (ties into Track 1's entity
     decision)?
3. **[HUMAN] Outcome recorded** as go/no-go per product in the launch
   review doc; **[AGENT]** then adjusts `INTEL_COMMERCIAL_MODE` filters to
   match counsel's actual lines.

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

Entity decision → counsel session (same week) → KYB while counsel reviews →
agent builds Track 3 items in parallel → beta (keys, tailnet/invite) →
public flip when Tracks 1–2 both clear.
