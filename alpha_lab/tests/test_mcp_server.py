"""Tests for the pure-stdlib AlphaLab MCP connector.

These exercise the JSON-RPC dispatch layer directly and stub the HTTP client so
no running AlphaLab server is required. The key safety property under test:
no tool exposed by this server can ever request a paper/live trade.
"""
from __future__ import annotations

import json

import pytest

from alpha_lab import mcp_server


@pytest.fixture
def captured_http(monkeypatch):
    """Replace the HTTP client with a recorder so we can assert on calls."""
    calls = []

    def fake_http(method, path, body=None):
        calls.append({"method": method, "path": path, "body": body})
        return {"ok": True, "echo": {"method": method, "path": path, "body": body}}

    monkeypatch.setattr(mcp_server, "_http", fake_http)
    return calls


def _call(method, params=None, req_id=1):
    return mcp_server._dispatch(
        {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    )


# --------------------------------------------------------------------------- #
# Protocol handshake
# --------------------------------------------------------------------------- #
def test_initialize_returns_protocol_and_capabilities():
    resp = _call("initialize", {"protocolVersion": "2025-11-25"})
    result = resp["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["capabilities"]["tools"] == {}
    assert result["serverInfo"]["name"] == "alphalab"


def test_initialize_defaults_protocol_when_absent():
    resp = _call("initialize", {})
    assert resp["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_initialized_notification_has_no_response():
    # Notifications carry no "id" -> server must stay silent.
    assert mcp_server._dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping_returns_empty_result():
    assert _call("ping")["result"] == {}


def test_unknown_method_returns_method_not_found():
    resp = _call("does/not/exist")
    assert resp["error"]["code"] == -32601


# --------------------------------------------------------------------------- #
# tools/list shape
# --------------------------------------------------------------------------- #
def test_tools_list_shape_and_no_private_keys():
    tools = _call("tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {
        "get_dashboard",
        "list_scored_ideas",
        "list_pending_approvals",
        "list_trades",
        "get_daily_brief",
        "get_catalyst_radar",
        "get_idea_explanation",
        "import_catalyst",
        "import_idea",
    } <= names
    for t in tools:
        assert "name" in t and "description" in t and "inputSchema" in t
        assert all(not k.startswith("_") for k in t), "handler leaked into tools/list"


# --------------------------------------------------------------------------- #
# tools/call routing
# --------------------------------------------------------------------------- #
def test_read_tool_routes_to_get(captured_http):
    resp = _call("tools/call", {"name": "get_dashboard", "arguments": {}})
    result = resp["result"]
    assert result["isError"] is False
    assert captured_http[-1] == {"method": "GET", "path": "/api/dashboard", "body": None}
    # content is text-wrapped JSON
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True


def test_list_scored_ideas_passes_limit(captured_http):
    _call("tools/call", {"name": "list_scored_ideas", "arguments": {"limit": 7}})
    assert captured_http[-1]["path"] == "/api/ideas?limit=7"


def test_unknown_tool_is_error():
    resp = _call("tools/call", {"name": "nope", "arguments": {}})
    assert resp["result"]["isError"] is True


def test_http_failure_surfaces_as_tool_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("server down")

    monkeypatch.setattr(mcp_server, "_http", boom)
    resp = _call("tools/call", {"name": "get_dashboard", "arguments": {}})
    assert resp["result"]["isError"] is True
    assert "server down" in resp["result"]["content"][0]["text"]


# --------------------------------------------------------------------------- #
# SAFETY: write tools can never request paper/live execution
# --------------------------------------------------------------------------- #
def test_import_catalyst_forces_dry_run(captured_http):
    _call(
        "tools/call",
        {
            "name": "import_catalyst",
            "arguments": {
                "catalysts": [{"ticker": "NVDA", "headline": "x"}],
                # Hostile/confused caller tries to escalate:
                "execution_mode": "paper",
            },
        },
    )
    body = captured_http[-1]["body"]
    assert captured_http[-1]["path"] == "/api/catalysts/import-and-test"
    assert body["execution_mode"] == "dry_run"  # escalation stripped + pinned


def test_import_idea_uses_non_executing_endpoint(captured_http):
    _call(
        "tools/call",
        {
            "name": "import_idea",
            "arguments": {
                "ticker": "NVDA",
                "bias": "bullish",
                "confidence": 0.8,
                "timeframe": "intraday",
                "thesis": "test",
                "execution_mode": "paper",  # must be ignored
            },
        },
    )
    call = captured_http[-1]
    assert call["path"] == "/api/ideas/import"  # import-only, never executes
    assert "execution_mode" not in call["body"]


def test_no_tool_exposes_an_execution_action():
    """Static guard: no tool name implies it can approve/reject/place trades.

    Listing pending approvals (read-only) is fine; *acting* on them is not.
    """
    forbidden = ("approve", "reject", "paper_trade", "paper-trade", "execute", "place_trade")
    for tool in mcp_server.TOOLS:
        assert not any(verb in tool["name"] for verb in forbidden), tool["name"]
