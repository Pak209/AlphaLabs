# Commercial launch review — licensing, pricing, readiness, architecture, M2 gate

Written 2026-07-09. Review only (no code). Inputs: human decisions of record —
dedicated Coinbase business wallet for all x402 revenue (never personal);
derived-intelligence-only product posture; personal-surface exclusions
continue. Licensing findings below are grounded in vendor terms as published
(sources in the session log) — **this is engineering analysis, not legal
advice; counsel sign-off is a launch gate.**

## Task 1 — Licensing audit & risk matrix

### What each source feeds today

| Source | Consumed | Feeds |
|---|---|---|
| Polygon (paid individual plan) | intraday snapshot (PV), ticker news, options chain refs, futures aggregates | PV confirmation → composite scores; catalyst events; futures pulse; flow preview |
| Alpaca (broker + data) | IEX snapshot/bars, options chain, crypto data, calendar | PV-compare candidate; options selector; trending/liquidity dollar-volume |
| CoinGecko (free/demo tier) | BTC/crypto prices, indicators | BTC bias, crypto signals, liquidity crypto groups |
| SEC EDGAR | filings metadata + forms | filing catalysts (8-K, S-1, 424B5…) |
| Yahoo RSS (unofficial) | headlines, price fallback | internal news context (already excluded from paid) |
| Benzinga/Tiingo/Newsfilter | disabled (no keys) | — |
| FRED (planned) | macro series | future macro inputs |

### The material finding

**Polygon's individual-plan terms prohibit commercial use outright and extend
to "Derived Works" — expressly including analytics and research "based on,
referring to, or derived from the Market Data."** Alpaca's posture is
similar: no redistribution of data **or derived products** for business
purposes without permission. This is stricter than M1's working assumption
("derived analytics are generally fine"). Consequence: **any paid product
whose inputs trace to Polygon/Alpaca data cannot launch on current
plans/agreements.** Personal trading use — the entire existing system — is
squarely within license and unaffected.

**CoinGecko is the opposite story:** their paid plans (from ~$35/mo Analyst)
include a **commercial license** that explicitly permits charging for
products incorporating their data, with required attribution ("Data provided
by CoinGecko" + link). The free tier we use today is non-commercial.

### Risk matrix (as products are built today)

| Item | Risk | Why | Action before public launch |
|---|---|---|---|
| `catalysts` product (Polygon News rows + headlines) | **HIGH** | commercial redistribution of vendor-licensed news + derived scores | **Rewrite: SEC-EDGAR-only catalyst feed at launch** (public-domain source + our scoring = clean); Polygon-sourced events stay internal |
| `market-snapshot` sector flows (Alpaca/CoinGecko-derived) | **HIGH** | commercial use of derived analytics on non-commercial licenses | Rewrite: regime/tone + SEC-catalyst context; add crypto only after CoinGecko upgrade (w/ attribution) |
| `daily-brief` product | **HIGH** | aggregates all of the above | Defer or recompose from licensed-only inputs |
| CoinGecko free tier feeding anything commercial | **HIGH → LOW** | non-commercial tier | **Upgrade to Analyst (~$35/mo)** + attribution line in envelopes — cheapest clean fix in the stack |
| `calibration` product (gate telemetry funnel) | **MEDIUM** | our own software's decision telemetry, far downstream of any quote; paranoid reading of "derived works" could still reach it | Counsel question #1; defensible, keep in beta behind invited keys until confirmed |
| `replay`/`backtest` over stored history | **MEDIUM** | archive embeds vendor-derived scores | Counsel; or restrict commercial replay to caller-supplied event sets initially |
| `signal-evaluation` / `decision-explanation` (M2, caller-supplied ideas) | **LOW** | our engine + caller inputs; run PV-neutral in commercial mode so no vendor data enters the response | Build with commercial-mode flag (below) |
| SEC EDGAR | **LOW** | US-government public domain; fair-access rules already respected | attribution as good practice |
| Yahoo RSS | **LOW (as-is)** | already excluded from paid products; internal only | keep excluded |
| FRED (future) | **LOW** | public with attribution norms | fine when added |
| Personal trading system's use of all vendors | **LOW** | licensed individual use | no change |

### Changes required before public launch (from the matrix)

1. **License-posture enforced in code**: product layer gains a commercial
   mode where paid outputs can only be composed from licensed-clean inputs
   (SEC, our engine, post-upgrade CoinGecko) — tested, not policy.
2. Catalysts product → SEC-only; snapshot → recomposed; brief → deferred.
3. CoinGecko Analyst upgrade + attribution in envelopes.
4. Optional later: approach Polygon/Alpaca for business/redistribution
   agreements if product demand justifies re-adding their derived signals.

## Task 2 — Pricing review (with reasoning)

Anchors: CoinMarketCap's x402 precedent ($0.01/call) sets the commodity
floor; sub-$0.10 is the "no-deliberation" zone for agent budgets; our
marginal cost is ~0 (SQLite + Python, ms latency), so pricing is value-based;
uniqueness (live calibrated engine) justifies multiples over commodity data.

| Product | Price | Reasoning |
|---|---|---|
| Market Snapshot | **$0.01** | entry product, commodity-adjacent after the licensing rewrite; volume play and the top of the funnel |
| Catalysts (SEC-only at launch) | **$0.02** | fresher than EDGAR polling yourself + our classification/scoring layered on; still volume-priced |
| Daily Brief | **$0.05** (when re-enabled) | compiled artifact, 1–3 calls/agent/day cadence; priced as a small report |
| Calibration | **$0.05** | unique telemetry nobody can replicate; kept cheap deliberately to build the habit of polling it |
| Signal Evaluation (POST) | **$0.10** | the real engine scoring *your* idea — highest per-call utility; launch at $0.10, revisit toward $0.25 with demand data |
| Decision Intelligence (explanation) | **$0.10** | glass-box gate trace + component breakdown; pairs 1:1 with evaluation |
| Replay (POST scenario) | **$0.25** | heavier compute + research-grade output; priced as analysis not lookup |
| Backtesting (POST) | **$0.50–$2.00 tiered** | window/complexity tiers; genuine compute + the deterministic-engine guarantee |

Bundles unchanged from the plan (Brief Pass $1/day; Research $29/mo; Quant
$99/mo; Enterprise custom) — subscriptions ride keys, x402 stays the
zero-friction lane. Add: **first 100 calls free per new key** (faucet) as the
conversion mechanism.

## Task 3 — Launch readiness checklist

**Required before beta** (invited keys, private/tailnet, NO payments):
- [x] M1 gateway (auth, metering, rate limit, 402 demo seam)
- [ ] M2: MCP server + signal-evaluation/explanation products
- [ ] Commercial-mode input enforcement (license posture in code) + tests
- [ ] SEC-only catalysts + snapshot recompose
- [ ] Usage dashboard (ops rollup exists; add daily review habit)
- [ ] Draft ToS/AUP/disclaimer page (even for beta users)
- [ ] Examples repo (private) with quickstarts

**Required before public launch + real x402:**
- [ ] **Counsel sign-off**: derived-works posture per vendor; calibration/
      replay questions; Investment Advisers Act publisher's-exemption check
      (impersonal research publication, no personalized advice)
- [ ] **Coinbase business wallet + CDP onboarding** (KYB), payTo address in
      config; payments table wired with idempotency + refund policy
- [ ] Business entity + tax treatment for USDC revenue (human/accountant)
- [ ] CoinGecko Analyst upgrade (if crypto context ships) + attribution
- [ ] Published ToS, privacy policy, acceptable-use
- [ ] Final pricing sign-off (table above)
- [ ] `api.pak-labs.com` tunnel + WAF/edge rate rules (no Access — key/x402 auth)
- [ ] Status/uptime page + latency SLOs + alerting to NotificationCenter
- [ ] Load test at 10× expected volume; runbook for incidents
- [ ] **Hosting decision**: strong recommendation to serve paid traffic from
      the VPS (tunnel exists) — paid SLA should not depend on the trading mini

**Recommended later:** enterprise webhooks/SLA; Python+TS SDK packages;
public OpenAPI clients; SOC2-lite security posture doc; data-quality SLOs;
Polygon/Alpaca commercial agreements to re-add their derived signals.

## Task 4 — Architecture validation

The layering is validated with one semantic correction and two recommendations:

- **Correction (already true in code, should be true in diagrams):** REST and
  MCP are *siblings* behind one shared gateway middleware stack; x402 is a
  lane *inside* auth (a 402 challenge is an auth outcome), not a layer after
  MCP; analytics/monitoring are cross-cutting consumers of the usage store,
  not a pipeline stage. The M1 implementation already matches this.
- **Recommendation 1 — extract `intel_gateway.py` at M2**: when MCP lands,
  auth/402/rate/metering must be one importable stack used by both
  interfaces, not duplicated. (Planned; making it explicit.)
- **Recommendation 2 — commercial-mode in the product layer**: the licensing
  outcome becomes an architectural feature: `INTEL_COMMERCIAL_MODE` gates
  which inputs products may compose (licensed-clean only), enforced by the
  same forbidden-fragment test pattern that protects personal data. License
  compliance becomes testable code, not documentation.
- Everything else stands: separate app/DB, envelope contract, /v1 freeze,
  monorepo until the PakOS integration point (M6), single-revert rollback.

## Task 5 — M2 gate: **GO**, with a revised order

M2 is code-only, private, payment-free, and its flagship products
(signal-evaluation, decision-explanation) are the *lowest-risk* items in the
licensing matrix. Nothing in M2 waits on counsel, wallet, or hosting.

Revised implementation order (maximizes progress, adds zero legal/ops risk):

1. **M2a** — `intel_gateway.py` extraction + MCP server exposing the two
   unambiguous products first (calibration, signal-evaluation) — tailnet only.
2. **M2b** — signal-evaluation + decision-explanation products
   (commercial-mode: PV-neutral, engine-native, zero vendor data in responses).
3. **M2c** — license-posture rework: SEC-only catalysts, snapshot recompose,
   commercial-mode enforcement tests. (Unblocks snapshot/catalysts for beta.)
4. **M2d** — examples repo (private) + quickstarts; MCP configs for Claude/
   agent frameworks.
5. **M3-sandbox** — x402 settlement against **Base Sepolia testnet** via CDP:
   full payment flow proven with fake USDC while the wallet/KYB/entity work
   completes in parallel. Real network flip is then config, not code.
6. **M4** — public exposure, gated on the "before public launch" checklist.

## Answers to the standing question (MCP/x402 functional status)

Merged M1 gives: REST products live-capable, key auth, metering, rate limit,
and a *demo* 402 challenge. Still needed for "fully functional":
**MCP** — the server itself (M2a; nothing exists yet beyond tool definitions
in the plan). **x402** — real settlement: CDP facilitator verification,
payments-table wiring with idempotency, the business wallet's payTo address,
and network config (testnet first, then Base) — that's M3, gated on the
wallet you're creating. Public reachability (api.pak-labs.com) is M4.
