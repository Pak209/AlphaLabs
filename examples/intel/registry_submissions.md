# MCP registry submissions — paste-ready drafts (submit at M4 flip, not before)

All entries assume the public base `https://api.pak-labs.com`. Do not submit
until the hostname is live and the launch checklist clears.

## Common fields

- **Name**: AlphaLabs Intelligence
- **One-liner**: Live trading-pipeline intelligence for AI agents: signal
  evaluation by a real calibrated engine, calibration telemetry, recorded
  outcomes, SEC catalysts. REST + MCP, API keys + x402 pay-per-call.
- **Endpoint (streamable HTTP MCP)**: `POST https://api.pak-labs.com/mcp`
- **Auth**: `Authorization: Bearer <api-key>` (free beta keys; x402 USDC
  pay-per-call rolling out)
- **Tools**: `alphalabs_get_catalog` (free), `alphalabs_calibration_report`,
  `alphalabs_evaluate_signal`, `alphalabs_explain_decision`,
  `alphalabs_outcome_report`, `alphalabs_feature_attribution`
- **Categories**: finance, market-data, research, analytics
- **Docs**: https://api.pak-labs.com (landing) · `/v1/catalog` (machine-readable)
- **Disclaimer**: research signals, not investment advice.

## Client config JSON (works for most registries' "install" block)

```json
{
  "mcpServers": {
    "alphalabs-intel": {
      "type": "http",
      "url": "https://api.pak-labs.com/mcp",
      "headers": { "Authorization": "Bearer YOUR_API_KEY" }
    }
  }
}
```

## Per-registry notes

| Registry | How | Notes |
|---|---|---|
| mcp.so | site submission form | paste common fields; category Finance |
| Smithery | smithery.ai submit (GitHub repo or remote URL) | choose "remote server"; streamable HTTP |
| Glama | glama.ai/mcp submit | supports remote MCP entries |
| PulseMCP | pulsemcp.com submit form | one-liner + endpoint + auth model |
| awesome-mcp-servers | GitHub PR to the list | one line under Finance: `[AlphaLabs Intelligence](https://api.pak-labs.com) - Live trading-pipeline intelligence: signal evaluation, calibration telemetry, recorded outcomes (REST + MCP + x402).` |

## Submission-day checklist

1. Hostname live + `/health` green from off-box.
2. Key faucet or contact path working (an interested agent can get access
   the same day).
3. Status page URL ready (registries ask).
4. Each submission is a PUBLISHING act — human clicks the submit buttons.
