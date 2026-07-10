#!/usr/bin/env bash
# AlphaLabs Intelligence — curl quickstart.
#   INTEL_URL=http://127.0.0.1:8790 INTEL_KEY=sk-... ./quickstart.sh
set -euo pipefail

INTEL_URL="${INTEL_URL:-http://127.0.0.1:8790}"
INTEL_KEY="${INTEL_KEY:?set INTEL_KEY to your API key}"
AUTH="Authorization: Bearer ${INTEL_KEY}"

echo "── catalog (free)"
curl -sf "${INTEL_URL}/v1/catalog" | python3 -m json.tool

echo "── market snapshot"
curl -sf -H "$AUTH" "${INTEL_URL}/v1/market-snapshot" | python3 -m json.tool

echo "── catalysts (SEC-EDGAR-only in commercial mode)"
curl -sf -H "$AUTH" "${INTEL_URL}/v1/catalysts?limit=5" | python3 -m json.tool

echo "── calibration telemetry"
curl -sf -H "$AUTH" "${INTEL_URL}/v1/calibration" | python3 -m json.tool

echo "── evaluate a signal, then explain the decision"
EVAL=$(curl -sf -H "$AUTH" -H 'Content-Type: application/json' \
  -X POST "${INTEL_URL}/v1/signal-evaluation" -d '{
    "ticker": "NVDA",
    "bias": "bullish",
    "confidence": 0.7,
    "catalyst": "NVDA wins major government AI contract",
    "thesis": "Contract expands datacenter demand beyond consensus",
    "catalyst_type": "Government Contract",
    "catalyst_score": 82
  }')
echo "$EVAL" | python3 -m json.tool
EVAL_ID=$(echo "$EVAL" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["evaluation_id"])')

curl -sf -H "$AUTH" "${INTEL_URL}/v1/decision-explanation/${EVAL_ID}" | python3 -m json.tool

echo "── MCP over streamable HTTP (same gateway)"
curl -sf -H "$AUTH" -H 'Content-Type: application/json' -X POST "${INTEL_URL}/mcp" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -m json.tool
