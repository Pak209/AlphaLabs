"""
alpha_lab/intel_mcp.py — the Intelligence Platform MCP server (M2a).

Same recipe as alpha_lab/mcp_server.py (hand-rolled JSON-RPC 2.0, no MCP SDK —
the venv is Python 3.9 and the official SDK needs 3.10+), but pointed at the
COMMERCIAL product layer and threaded through the SAME gateway as REST:
`handle_message()` is transport-agnostic and every paid tools/call runs
Gateway.authorize (key → x402 seam → rate limit) and is metered with
interface="mcp" into the platform's own SQLite.

Transports:
  * streamable HTTP — POST /mcp on the intel app (alpha_lab.intel_api); this
    is the lane remote agents use (tailnet-only until M4).
  * stdio — `python -m alpha_lab.intel_mcp` for a local MCP client
    (claude_desktop_config.json). Auth comes from INTEL_MCP_KEY.

Safety model: identical to the REST surface — the product layer already
refuses personal-surface data, so this file exposes nothing REST doesn't.
No execution authority exists on this surface at all.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

from .intel_gateway import Gateway
from .intel_products import (
    calibration_report, catalog, decision_explanation, feature_attribution,
    outcome_report, signal_evaluation,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "alphalabs-intel", "version": "0.2.0"}

# tool name -> catalog product metered/charged (None = free discovery)
TOOL_PRODUCTS: dict[str, Optional[str]] = {
    "alphalabs_get_catalog": None,
    "alphalabs_calibration_report": "calibration",
    "alphalabs_evaluate_signal": "signal-evaluation",
    "alphalabs_explain_decision": "decision-explanation",
    "alphalabs_outcome_report": "outcome-report",
    "alphalabs_feature_attribution": "feature-attribution",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "alphalabs_get_catalog",
        "description": "Free: list AlphaLabs Intelligence products, prices, and auth model.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "alphalabs_calibration_report",
        "description": ("Live paper-trading pipeline calibration telemetry: stage funnel, "
                        "gate failures, near-misses. Derived analytics only — no positions, "
                        "orders, or account data exist on this surface."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "alphalabs_evaluate_signal",
        "description": ("Score YOUR trade idea through the live AlphaLabs deterministic engine: "
                        "composite score, tier, per-component sub-signals, floors. Price/volume "
                        "confirmation is not evaluated (no vendor market data). Returns an "
                        "evaluation_id for alphalabs_explain_decision."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Symbol, e.g. NVDA"},
                "bias": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                               "description": "Your own conviction 0-1 (echoed, not scored)"},
                "catalyst": {"type": "string", "description": "What just happened (headline/event)"},
                "thesis": {"type": "string", "description": "Why it should move the stock"},
                "catalyst_type": {"type": "string",
                                  "description": "Optional label, e.g. 'Government Contract'"},
                "catalyst_score": {"type": "number", "minimum": 0, "maximum": 100,
                                   "description": "Optional 0-100 materiality if you scored it"},
            },
            "required": ["ticker", "bias"],
            "additionalProperties": False,
        },
    },
    {
        "name": "alphalabs_outcome_report",
        "description": ("Recorded outcomes of the live pipeline's own decisions: hit rates, "
                        "score-band tables, accepted-vs-rejected edge, gate near-miss regret. "
                        "Aggregated engine telemetry — percent moves and counts only."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "alphalabs_feature_attribution",
        "description": ("Which engine inputs actually predict outcomes, measured on recorded "
                        "live results: Spearman rankings, median-split deltas, dead inputs."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "alphalabs_explain_decision",
        "description": ("Glass-box breakdown of a prior evaluation by evaluation_id: every "
                        "sub-signal, weight, floor, and the composite reasoning."),
        "inputSchema": {
            "type": "object",
            "properties": {"evaluation_id": {"type": "string"}},
            "required": ["evaluation_id"],
            "additionalProperties": False,
        },
    },
]


def _rpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: Any, code: int, message: str,
               data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _tool_text(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "isError": False}


def _call_tool(name: str, arguments: dict[str, Any], *, gateway: Gateway,
               trading_db_path: Optional[str], raw_key: str,
               interface: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Returns (tool_result, rpc_error_payload). Exactly one is set."""
    if name not in TOOL_PRODUCTS:
        return None, {"code": -32602, "message": f"unknown tool: {name}"}
    product = TOOL_PRODUCTS[name]

    if product is None:                       # free discovery tool
        return _tool_text(catalog()), None

    key, err, status = gateway.authorize(raw_key, product)
    if err:
        return None, {"code": -32001,
                      "message": err.get("detail") or err.get("error") or "unauthorized",
                      "data": {"http_status": status, **err}}

    started = time.monotonic()
    result_status = 200
    try:
        if name == "alphalabs_calibration_report":
            payload = calibration_report(trading_db_path)
        elif name == "alphalabs_outcome_report":
            payload = outcome_report(trading_db_path)
        elif name == "alphalabs_feature_attribution":
            payload = feature_attribution(trading_db_path)
        elif name == "alphalabs_evaluate_signal":
            payload = signal_evaluation(arguments)
            evaluation_id = gateway.store.store_evaluation(key["name"], arguments, payload)
            payload["data"]["evaluation_id"] = evaluation_id
        elif name == "alphalabs_explain_decision":
            record = gateway.store.get_evaluation(str(arguments.get("evaluation_id") or ""))
            if not record or record.get("key_name") != key["name"]:
                result_status = 404
                return None, {"code": -32602, "message": "evaluation_id not found for this key",
                              "data": {"http_status": 404}}
            payload = decision_explanation(record)
        else:                                  # pragma: no cover — map and branches in sync
            result_status = 500
            return None, {"code": -32603, "message": f"tool {name} not wired"}
        return _tool_text(payload), None
    except ValueError as exc:
        result_status = 422
        return None, {"code": -32602, "message": str(exc), "data": {"http_status": 422}}
    except Exception:
        result_status = 503
        return None, {"code": -32603, "message": f"{product} temporarily unavailable",
                      "data": {"http_status": 503}}
    finally:
        gateway.store.record_usage(key["name"], product, result_status,
                                   (time.monotonic() - started) * 1000,
                                   interface=interface)


def handle_message(msg: Any, *, gateway: Gateway, trading_db_path: Optional[str],
                   raw_key: str, interface: str = "mcp") -> Optional[dict[str, Any]]:
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "invalid request: expected JSON-RPC 2.0 object")
    method = msg.get("method")
    msg_id = msg.get("id")

    if isinstance(method, str) and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _rpc_result(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": ("AlphaLabs Intelligence: derived market analytics for AI agents. "
                             "Paid tools need Authorization: Bearer <api-key> "
                             "(x402 pay-per-call arrives in M3). Start with "
                             "alphalabs_get_catalog. Not investment advice."),
        })
    if method == "ping":
        return _rpc_result(msg_id, {})
    if method == "tools/list":
        return _rpc_result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _rpc_error(msg_id, -32602, "arguments must be an object")
        result, error = _call_tool(name, arguments, gateway=gateway,
                                   trading_db_path=trading_db_path,
                                   raw_key=raw_key, interface=interface)
        if error:
            return _rpc_error(msg_id, error["code"], error["message"], error.get("data"))
        return _rpc_result(msg_id, result)
    return _rpc_error(msg_id, -32601, f"method not found: {method}")


def main() -> None:
    """stdio transport: newline-delimited JSON-RPC 2.0, one message per line."""
    gateway = Gateway()
    trading_db_path = os.getenv("ALPHALAB_DB_PATH")
    raw_key = os.getenv("INTEL_MCP_KEY", "").strip()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            response: Optional[dict[str, Any]] = _rpc_error(None, -32700, "parse error")
        else:
            response = handle_message(msg, gateway=gateway,
                                      trading_db_path=trading_db_path,
                                      raw_key=raw_key, interface="mcp-stdio")
        if response is not None:
            sys.stdout.write(json.dumps(response, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
