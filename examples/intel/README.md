# AlphaLabs Intelligence — integration quickstarts (M2d)

Derived market intelligence for AI agents: REST + MCP behind one gateway,
x402 pay-per-call arriving in M3. **Private while the platform is
tailnet-only (pre-M4) — do not publish this directory yet.**

## What you can call today

| Product | Endpoint | Price | Notes |
|---|---|---|---|
| Catalog | `GET /v1/catalog` | free | machine-readable pricing page |
| Market snapshot | `GET /v1/market-snapshot` | $0.01 | engine-derived regime (commercial mode) |
| Catalysts | `GET /v1/catalysts` | $0.02 | SEC-EDGAR-only in commercial mode |
| Calibration | `GET /v1/calibration` | $0.05 | live gate telemetry — the moat product |
| Signal evaluation | `POST /v1/signal-evaluation` | $0.10 | your idea, scored by the live engine |
| Decision explanation | `GET /v1/decision-explanation/{id}` | $0.10 | glass-box breakdown of an evaluation |

Every response uses one envelope: `product / version / generated_at / data /
provenance / confidence / reasoning / disclaimer`. Nothing personal exists on
this surface — no positions, P/L, orders, broker state, or account data.

## Auth — two lanes

**API key** (accounts, subscriptions):

```
Authorization: Bearer <your-api-key>
```

**x402 pay-per-call** (keyless, agent-native): a keyless call returns `402`
with machine-readable payment requirements; sign an EIP-3009 USDC
authorization for the exact amount, retry with it base64-encoded in the
`X-PAYMENT` header, and the settlement receipt comes back in
`X-PAYMENT-RESPONSE`. Modes: `demo` (challenge only), `sandbox` (**real
settlement on Base Sepolia testnet USDC** — see
[`x402_sandbox.md`](x402_sandbox.md)), `live` (Base mainnet, gated on
business-wallet/KYB completion). Verify runs before the product and settle
after it succeeds, so a failed call never charges and a miss (404) is free.

## Quickstarts

- [`quickstart.sh`](quickstart.sh) — curl walkthrough of every endpoint
- [`evaluate_signal.py`](evaluate_signal.py) — stdlib-only Python client:
  evaluate an idea, then fetch its glass-box explanation
- [`mcp_config.json`](mcp_config.json) — wire the MCP server into an MCP
  client (Claude Desktop / Claude Code), both transports

## MCP

Same gateway, second transport. Streamable HTTP lives at `POST /mcp`;
stdio via `python -m alpha_lab.intel_mcp` (auth from `INTEL_MCP_KEY`).
Tools: `alphalabs_get_catalog` (free), `alphalabs_calibration_report`,
`alphalabs_evaluate_signal`, `alphalabs_explain_decision`.

## Disclaimer

Informational derived analytics — not investment advice, not an offer or
solicitation, and not a redistribution of any vendor's market data.
