# AlphaLabs Intelligence Platform — architecture & go-to-market plan

Written 2026-07-09. Mission: expose AlphaLabs' differentiated market
intelligence to AI agents as a paid Feed-as-a-Service over REST, MCP, and
x402 micropayments — without touching the personal trading system's safety
posture. Milestone M1 ships with this document.

## 0. Hard constraints designed around (read first)

1. **Separation of surfaces.** The commercial API is a *separate FastAPI app*
   (`create_intel_app`, own port, own SQLite for keys/usage) that reads the
   trading DB read-only through the product layer. The operator's positions,
   P/L, notification preferences, approvals, and any write endpoint are
   architecturally absent from the product surface — not "hidden", absent.
2. **Sell derived intelligence, never redistributed market data.** Vendor
   licenses (Polygon, Alpaca IEX, CoinGecko free tier) prohibit reselling
   quotes/bars. Products expose AlphaLabs' *judgments*: scores, regimes,
   classifications, calibration statistics, explanations — with source
   *attribution* but no raw price/volume redistribution. Yahoo-RSS-derived
   content is excluded from paid products entirely (unofficial feed, ToS
   risk). ⚠️ Before charging real money: a licensing pass by the human,
   listed in Open Human Decisions below.
3. **Trading behavior untouched.** The platform layer is 100% read-only
   against the trading core; every safeguard, gate, and approval flow is
   unaffected. The intel DB is a separate file (backtest-architecture
   pattern).
4. **Not investment advice.** Every response envelope carries a disclaimer;
   products describe research signals and their measured history, never
   recommendations to trade.

## 1. Architecture (the same business logic behind every interface)

```
                    ┌──────────────────────────────────────────────┐
                    │        AlphaLabs Core (existing, pure)       │
                    │ catalysts · scoring · waterfall · outcomes   │
                    │ attribution · replay · market_context · brief│
                    └──────────────────┬───────────────────────────┘
                                       │ read-only
                    ┌──────────────────▼───────────────────────────┐
                    │   Product layer  alpha_lab/intel_products.py │
                    │   payment-agnostic; standard envelope:       │
                    │   product/version/generated_at/data/         │
                    │   provenance/confidence/reasoning/           │
                    │   historical_performance/disclaimer          │
                    └───────┬──────────────┬───────────────────────┘
                            │              │
          ┌─────────────────▼──┐      ┌────▼──────────────────┐
          │ REST  intel_api.py │      │ MCP  intel_mcp (M2)   │
          │ /v1/* (port 8790)  │      │ tools = same products │
          └─────────┬──────────┘      └────┬──────────────────┘
                    └───────┬──────────────┘
          ┌─────────────────▼────────────────────────────────────┐
          │ Gateway middleware (single stack, both interfaces):  │
          │  auth (API key)  →  x402 402-challenge (M3)  →       │
          │  rate limit  →  usage metering  →  latency metrics   │
          │  (intel_platform.sqlite3: keys, usage, payments)     │
          └─────────────────┬────────────────────────────────────┘
                            ▼
              Cloudflare Tunnel  api.pak-labs.com (M4)
              + Cloudflare analytics/WAF; Access NOT applied
              (auth is key/x402, not identity)
```

## 2. Product catalog, differentiation & pricing

What agents cannot easily recreate: **a live, calibrated decision pipeline
with recorded outcomes**. Anyone can wrap a news API; nobody else has this
system's gate telemetry, rejection waterfall, calibration history, and
value-pinned scoring engine.

| Product (endpoint) | What it returns | Differentiation | Price (x402/call) | M |
|---|---|---|---|---|
| `market-snapshot` | regime posture, narrative summary, sector-flow extremes, BTC bias | regime engine + Lex narrative | $0.01 | 1 |
| `catalysts` | scored catalyst events: type, direction, 8-factor score, classification, provenance | FoxRunner-style classifier + dedupe + scoring | $0.02 | 1 |
| `daily-brief` | full AI market brief: tone, themes, macro risks, watchlist, top catalysts | the compiled daily research product | $0.05 | 1 |
| `calibration` | rejection waterfall aggregates: stage funnel, gate failures, near-misses | **unique** — live pipeline calibration telemetry | $0.05 | 1 |
| `signal-evaluation` (POST) | score a caller-supplied idea through the real engine (composite, tier, components, gate verdicts) | the actual production scorer, value-pinned | $0.10 | 2 |
| `decision-explanation` | full alpha breakdown + gate trace for a scored idea | glass-box reasoning | $0.10 | 2 |
| `feature-attribution` | which inputs predict outcomes (Spearman, splits, dead inputs) | measured on live outcomes | $0.10 | 2 |
| `outcome-report` | accepted-vs-rejected performance, score-band tables | recorded pipeline outcomes | $0.05 | 2 |
| `strategy-replay` (POST) | run a caller scenario (weights/thresholds) over history | replay engine as a service | $0.25 | 3 |
| `historical-similarity` | nearest historical catalysts + their forward outcomes | event archive + labels | $0.15 | 3+ |
| `confidence-calibration` | score-band → hit-rate curves | calibration data | $0.05 | 3+ |
| `backtest` (POST) | full scenario backtest (post backtest-M-series) | deterministic engine | $0.50+ | 4+ |

**Bundles/subscriptions:** Brief Pass $1/day (brief+snapshot unlimited);
Research tier $29/mo (all GET products, 10k calls); Quant tier $99/mo (adds
POST scoring/replay, 50k calls); Enterprise: custom (dedicated replay
capacity, webhook push of catalysts, SLA). x402 pay-per-call remains the
zero-friction agent path; subscriptions ride API keys.

## 3. Database changes

**None to the trading DB.** New `alpha_lab/data/intel_platform.sqlite3`:

```sql
CREATE TABLE api_keys (id, key_hash TEXT UNIQUE, name TEXT, tier TEXT,
  rate_per_min INTEGER, created_at, revoked_at);
CREATE TABLE usage (id, key_name TEXT, product TEXT, status INTEGER,
  latency_ms REAL, x402_payment_id TEXT, created_at);
CREATE TABLE payments (id, payment_id TEXT UNIQUE, product TEXT,
  amount_usdc REAL, payer TEXT, network TEXT, settled_at);  -- M3
```

## 4. API specification (v1, M1 scope)

- Base: `https://api.pak-labs.com/v1` (M4; until then tailnet/local :8790)
- Auth: `Authorization: Bearer <key>` (M1) → or x402 payment header (M3)
- `GET /v1/catalog` — free; lists products, prices, schemas
- `GET /v1/market-snapshot` · `GET /v1/catalysts?limit=25` ·
  `GET /v1/daily-brief` · `GET /v1/calibration`
- `GET /health` — free
- Envelope (every product):

```json
{"product": "catalysts", "version": "v1", "generated_at": "...",
 "data": {...}, "provenance": [{"source": "...", "as_of": "..."}],
 "confidence": {"level": "...", "basis": "..."},
 "reasoning": "...", "historical_performance": {...} | null,
 "disclaimer": "Research signals, not investment advice...",
 "usage": {"product_price_usd": 0.02}}
```

- Errors: 401 (no/bad key), 402 (x402 challenge when enabled), 429 (rate),
  503 (upstream data unavailable — never a silent empty 200).

## 5. MCP tool definitions (M2)

One remote MCP server (`intel_mcp.py`, streamable HTTP on the same gateway
stack) exposing tools mapped 1:1 to products:
`alphalabs_market_snapshot`, `alphalabs_catalysts(limit)`,
`alphalabs_daily_brief`, `alphalabs_calibration`,
`alphalabs_evaluate_signal(ticker, bias, confidence, thesis, catalyst_type)`,
`alphalabs_explain_decision(evaluation_id)`. Tool descriptions carry the
price so agent frameworks can budget; x402 flows through the same middleware
(402-aware MCP clients already exist in the ecosystem).

## 6. x402 integration (M3)

- Facilitator: **Coinbase CDP** (verifies signature, settles USDC on Base,
  ~$0.001 gas, ~300ms overhead — production-proven at CoinMarketCap-scale
  per current ecosystem reports).
- Server: FastAPI middleware on the gateway — no key → respond `402` with
  the x402 payment-requirements body (amount from the catalog, pay-to
  address, network `base`); on retry with `X-PAYMENT` header → facilitator
  verify → serve + record in `payments`.
- M1 ships the **adapter seam**: `INTEL_X402_MODE=off|demo` — `demo` returns
  a spec-shaped 402 challenge (no settlement) so integrators can build
  against it today. Real settlement needs the human decisions below.
- SDK path: Python x402 packages with FastAPI support exist (openlib x402 et
  al.); evaluate official Coinbase SDK first at M3.

## 7. Authentication strategy

M1: API keys (hash-at-rest, per-key tier + rate limit; env-seeded
`INTEL_API_KEYS=name:key,...` for first partners, table-backed thereafter).
M3: x402 as keyless pay-per-call lane. Enterprise: keys + signed webhooks.
The personal dashboard's Access/tailnet auth is unrelated and untouched.

## 8. Monitoring, metrics, KPIs

- Per-request usage rows (product, status, latency) → `GET /v1/ops/usage`
  (admin key) + daily rollup into the ops journal routine.
- KPIs: distinct paying agents/week · calls/day by product · x402 revenue/wk
  · repeat-caller rate (7d) · retention cohort (keys active 4 weeks later) ·
  conversion (catalog hits → first paid call) · p50/p95 latency per product ·
  uptime (tunnel connector + health probe) · top-product share.
- Alerting reuses the existing NotificationCenter (WATCH-level ops alerts).

## 9. Deployment & rollback

- M1–M2: separate LaunchAgent `com.alphalab.intel-api` on :8790, tailnet
  only (integration testing).
- M4 public: new Cloudflare tunnel ingress `api.pak-labs.com → :8790`
  (NO Access — auth is key/x402; WAF + rate rules at edge). Same fail-closed
  rollout pattern as alpha.pak-labs.com.
- Longer term: migrate the intel app to the hermes-vps (tunnel already
  exists) so paid traffic never depends on the trading mini.
- Rollback at every layer: bootout LaunchAgent / remove DNS / revert PR —
  product layer is stateless; usage DB is append-only and separate.

## 10. Testing & docs

- Tests per milestone: envelope contracts (shape + no-personal-data
  assertions + no-secret-leak), auth 401/402/429 paths, metering rows,
  product determinism against seeded DBs; route-manifest-style pin for the
  intel app.
- Docs: `/v1/catalog` is machine-readable truth; OpenAPI auto-served at
  `/docs`; quickstarts (curl, Python httpx, x402-fetch, MCP client) in
  `examples/` (M2); CHANGELOG.md + semver from first public tag.

## 11. Go-to-market (agents and their developers are the customer)

**Discovery (legitimate channels only):**
- MCP: publish to the four that matter — mcp.so, Smithery, Glama, PulseMCP —
  plus a PR to awesome-mcp-servers; claim listings, keep descriptions
  benchmark-honest.
- x402: list in the x402 ecosystem/awesome-x402 index and Coinbase CDP
  discovery surfaces; being *callable for $0.02 with no signup* is itself
  the growth loop for agent traffic.
- GitHub: public `alphalabs-examples` repo (quickstarts, MCP config,
  x402-fetch demo, LangChain/agent snippets); clear README with a 60-second
  first-call; topics/tags for mcp + x402 + market-intelligence.
- Content: one benchmark page — "what the calibration feed catches that raw
  news APIs don't" with reproducible numbers; changelog as RSS.
- Communities: MCP/x402 developer Discords and forums via genuinely useful
  posts; no spam, no fake traffic, no astroturf.

**Launch checklist:** catalog stable → pricing page (= rendered catalog) →
examples repo green in CI → registries submitted → status/uptime page →
first-100-calls-free key faucet → announce.

## 12. Roadmap

| M | Scope | Exit criteria |
|---|---|---|
| **M1 — SHIPPED** | product layer + REST app + key auth + metering + rate limit + 402-demo seam + tests | 4 products live on :8790 tailnet; suite green |
| **M2 — SHIPPED** | intel_gateway extraction + MCP server (HTTP `/mcp` + stdio) + signal-evaluation/explanation products + INTEL_COMMERCIAL_MODE license enforcement + examples/intel quickstarts | agent can call via MCP end-to-end (verified in-process against live DB) |
| M2.x | SEC EDGAR ingestion source — commercial catalysts feed is honestly EMPTY until license-clean events exist | commercial /v1/catalysts returns real SEC events |
| **M3-sandbox — SHIPPED** | real x402 verify/settle lane (intel_x402.py + gateway charge path): Base Sepolia testnet USDC via x402.org facilitator, X-PAYMENT/X-PAYMENT-RESPONSE, nonce replay protection, payments table, spec-correct challenges (atomic units + asset contract) | mocked-facilitator suite green; on-chain testnet probe = examples/intel/x402_sandbox.md |
| M3-live | switch to CDP facilitator + Base mainnet USDC paid to the business wallet | first settled $0.01 — GATED on wallet/KYB/counsel |
| M4 | public tunnel api.pak-labs.com + registries + landing/pricing page | first external agent call |
| M5 | replay/attribution/outcome products + subscriptions | first repeat customer |
| M6 | VPS migration + SLA + enterprise webhooks | mini-independent |

## 13. Open human decisions (blocking real revenue, not blocking M1–M2)

1. **Licensing review** of derived-analytics posture vs Polygon/Alpaca/
   CoinGecko terms; drop or license anything marginal. (Yahoo already
   excluded from paid products.)
2. **Wallet & entity**: USDC receiving address custody, tax treatment,
   business entity for selling data services.
3. **Pricing sign-off** on the table above.
4. **Hosting**: bless VPS migration timing (M6) — paid uptime SLA should not
   depend on the trading mini.
