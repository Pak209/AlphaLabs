"""AlphaLab MCP connector — pure-stdlib JSON-RPC 2.0 server over stdio.

Exposes AlphaLab's research surface to MCP clients (e.g. Claude Cowork) as a
local connector. It is intentionally *dependency-free* (Python 3.9 stdlib only)
and talks to a **running** AlphaLab FastAPI instance over HTTP, so it shares the
exact same database/state as the live dashboard.

SAFETY MODEL
------------
This connector grants **no execution authority**. It exposes:
  * read tools  — dashboard, ideas, approvals, trades, daily brief, radar
  * write tools — push catalysts / ideas for *dry-run* scoring only

Write tools never expose `execution_mode` and only call dry-run-safe endpoints
(`/api/ideas/import`, `/api/catalysts/import-and-test` with execution_mode hard
-forced to "dry_run"). There is no path through this server that can place a
paper or live order. Approval/decision endpoints are deliberately NOT exposed.

TRANSPORT
---------
stdio: newline-delimited JSON-RPC 2.0. One message per line, no embedded
newlines, no Content-Length framing. Logs go to stderr only.

Run:
    python -m alpha_lab.mcp_server
Configure (e.g. claude_desktop_config.json):
    {"mcpServers": {"alphalab": {
        "command": "/Users/danielpak/AlphaLab/.venv/bin/python",
        "args": ["-m", "alpha_lab.mcp_server"],
        "env": {"ALPHALAB_BASE_URL": "http://127.0.0.1:8787"}}}}
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

PROTOCOL_VERSION = "2025-11-25"
SERVER_NAME = "alphalab"
SERVER_VERSION = "0.1.0"
BASE_URL = os.environ.get("ALPHALAB_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
HTTP_TIMEOUT = float(os.environ.get("ALPHALAB_MCP_TIMEOUT", "30"))


def _log(msg: str) -> None:
    """Diagnostics go to stderr so they never corrupt the stdio JSON stream."""
    sys.stderr.write(f"[alphalab-mcp] {msg}\n")
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# HTTP client against the running AlphaLab API
# --------------------------------------------------------------------------- #
def _http(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {"Accept": "application/json"}
    # If the API is token-gated (ALPHALAB_API_TOKEN set), authenticate writes.
    token = os.environ.get("ALPHALAB_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"AlphaLab API {method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach AlphaLab API at {BASE_URL} ({exc.reason}). "
            f"Is the server running? (python -m alpha_lab.main)"
        ) from exc
    return json.loads(raw) if raw else None


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
def _tool_get_dashboard(_: Dict[str, Any]) -> Any:
    return _http("GET", "/api/dashboard")


def _tool_list_scored_ideas(args: Dict[str, Any]) -> Any:
    limit = int(args.get("limit", 25))
    return _http("GET", f"/api/ideas?limit={limit}")


def _tool_list_pending_approvals(args: Dict[str, Any]) -> Any:
    limit = int(args.get("limit", 100))
    return _http("GET", f"/api/ideas/pending-approval?limit={limit}")


def _tool_list_trades(_: Dict[str, Any]) -> Any:
    return _http("GET", "/api/trades")


def _tool_get_daily_brief(args: Dict[str, Any]) -> Any:
    live = "true" if bool(args.get("live_catalysts", True)) else "false"
    return _http("GET", f"/api/brief/daily?live_catalysts={live}")


def _tool_get_catalyst_radar(args: Dict[str, Any]) -> Any:
    live = "true" if bool(args.get("live", True)) else "false"
    return _http("GET", f"/api/catalysts/radar?live={live}")


def _tool_get_idea_explanation(args: Dict[str, Any]) -> Any:
    idea_id = int(args["idea_id"])
    return _http("GET", f"/api/ideas/{idea_id}/explanation")


def _tool_import_catalyst(args: Dict[str, Any]) -> Any:
    # Strip any caller-supplied execution_mode; hard-pin to dry_run.
    payload = {k: v for k, v in args.items() if k != "execution_mode"}
    payload["execution_mode"] = "dry_run"
    return _http("POST", "/api/catalysts/import-and-test", payload)


def _tool_import_idea(args: Dict[str, Any]) -> Any:
    # /api/ideas/import only scores+stores ideas; it never executes a trade.
    payload = {k: v for k, v in args.items() if k != "execution_mode"}
    return _http("POST", "/api/ideas/import", payload)


TOOLS = [
    {
        "name": "get_dashboard",
        "description": "Get the AlphaLab dashboard snapshot: scored ideas, trades, "
        "stats, and current pipeline state. Read-only.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_handler": _tool_get_dashboard,
    },
    {
        "name": "list_scored_ideas",
        "description": "List recently scored research ideas with composite alpha "
        "scores, tiers, and gate status. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25}
            },
            "additionalProperties": False,
        },
        "_handler": _tool_list_scored_ideas,
    },
    {
        "name": "list_pending_approvals",
        "description": "List ideas awaiting human approval before any paper execution. "
        "Read-only — this tool cannot approve anything.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100}
            },
            "additionalProperties": False,
        },
        "_handler": _tool_list_pending_approvals,
    },
    {
        "name": "list_trades",
        "description": "List logged paper/dry-run trades with their full signal "
        "breakdown (catalyst, price/volume, options, dark-pool, gate). Read-only.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "_handler": _tool_list_trades,
    },
    {
        "name": "get_daily_brief",
        "description": "Get the AlphaLab daily market brief (catalysts + narrative + "
        "candidate ideas). Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"live_catalysts": {"type": "boolean", "default": True}},
            "additionalProperties": False,
        },
        "_handler": _tool_get_daily_brief,
    },
    {
        "name": "get_catalyst_radar",
        "description": "Get the catalyst radar feed of upcoming/recent market "
        "catalysts. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"live": {"type": "boolean", "default": True}},
            "additionalProperties": False,
        },
        "_handler": _tool_get_catalyst_radar,
    },
    {
        "name": "get_idea_explanation",
        "description": "Get the detailed scoring/trade explanation for one idea by id. "
        "Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"idea_id": {"type": "integer"}},
            "required": ["idea_id"],
            "additionalProperties": False,
        },
        "_handler": _tool_get_idea_explanation,
    },
    {
        "name": "import_catalyst",
        "description": "Push catalyst data into AlphaLab and run it through scoring in "
        "DRY-RUN only (never executes a paper/live trade). Use this to test how a "
        "catalyst would score. Provide a 'catalysts' list (or single catalyst fields). "
        "Returns the scored result. NOTE: scraped web data must not be presented as "
        "options-flow or dark-pool provider data — those providers are stubbed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "catalysts": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of catalyst objects (ticker, headline, etc.)",
                },
                "source": {"type": "string"},
                "timestamp": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "_handler": _tool_import_catalyst,
    },
    {
        "name": "import_idea",
        "description": "Import one or more research ideas into AlphaLab for scoring and "
        "storage. This NEVER executes a trade — ideas land in the pipeline and still "
        "require human approval for any paper execution. Each idea needs: ticker, bias "
        "(bullish|bearish), confidence (0-1), timeframe (intraday|swing), and a thesis "
        "(or reason). Pass a single idea object, or {'ideas': [...]}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ideas": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of idea objects.",
                },
                "ticker": {"type": "string"},
                "bias": {"type": "string", "enum": ["bullish", "bearish"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "timeframe": {"type": "string", "enum": ["intraday", "swing"]},
                "thesis": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "_handler": _tool_import_idea,
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def _public_tools() -> list:
    """tools/list payload: strip private handler keys."""
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]


# --------------------------------------------------------------------------- #
# JSON-RPC plumbing
# --------------------------------------------------------------------------- #
def _result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    requested = params.get("protocolVersion", PROTOCOL_VERSION)
    return {
        "protocolVersion": requested if isinstance(requested, str) else PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {
            "content": [{"type": "text", "text": f"Unknown tool: {name!r}"}],
            "isError": True,
        }
    try:
        data = tool["_handler"](args)
        text = json.dumps(data, indent=2, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": False}
    except Exception as exc:  # noqa: BLE001 — surface any failure as tool error
        _log(f"tool {name} failed: {exc}")
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}


def _dispatch(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}
    is_notification = "id" not in message

    if method == "initialize":
        return _result(req_id, _handle_initialize(params))
    if method == "notifications/initialized":
        return None  # notification: no response
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": _public_tools()})
    if method == "tools/call":
        return _result(req_id, _handle_tools_call(params))

    if is_notification:
        return None  # ignore unknown notifications silently
    return _error(req_id, -32601, f"Method not found: {method}")


def _write(message: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    _log(f"starting (base_url={BASE_URL}, protocol={PROTOCOL_VERSION})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _log(f"parse error: {exc}")
            _write(_error(None, -32700, "Parse error"))
            continue
        try:
            response = _dispatch(message)
        except Exception as exc:  # noqa: BLE001
            _log(f"dispatch error: {exc}")
            response = _error(message.get("id"), -32603, f"Internal error: {exc}")
        if response is not None:
            _write(response)
    _log("stdin closed; exiting")


if __name__ == "__main__":
    main()
