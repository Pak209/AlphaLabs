"""Intelligence Platform M1: product envelopes + gateway contracts.

The contracts that matter commercially AND safely:
  * every product returns the standard envelope with provenance/disclaimer
  * NO personal-surface data can appear in any product payload
  * gateway: 401 without key, 402 spec-shaped challenge in demo mode,
    429 past the rate limit, usage metered per call into the platform's
    OWN sqlite (never the trading DB)
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from alpha_lab.database import connect, init_db
from alpha_lab.intel_api import IntelStore, create_intel_app
from alpha_lab.intel_products import (
    CATALOG, calibration_report, catalyst_feed, daily_brief, market_snapshot,
    signal_evaluation,
)
from alpha_lab.repository import AlphaLabRepository


def seeded_trading_db(tmp_path: Path) -> str:
    db = str(tmp_path / "trading.sqlite3")
    init_db(db)
    with connect(db) as conn:
        repo = AlphaLabRepository(conn)
        repo.save_market_briefing({
            "brief_type": "daily_market_brief",
            "broad_market_tone": "Risk-On Watch",
            "themes": ["ai"],
            "macro_risks": ["Watch yields"],
            "candidate_tickers_to_monitor": ["NVDA"],
            "crypto_context": {"btc_bias": "bullish"},
            "strongest_catalysts_found": [
                {"ticker": "NVDA", "headline": "NVDA wins contract",
                 "catalyst_type": "Government Contract", "direction": "bullish",
                 "catalyst_score": 82}],
            "generated_at": "2026-07-09T13:00:00Z",
        })
        conn.execute(
            "INSERT INTO catalyst_events (ticker, catalyst_type, strategy_label, direction,"
            " headline, source, published_at, discovered_at, catalyst_score)"
            " VALUES ('NVDA', 'Government Contract', 'Government Contract', 'bullish',"
            " 'NVDA wins contract', 'Polygon News / Newswire',"
            " '2026-07-09T12:00:00Z', '2026-07-09T12:03:00Z', 82)")
        conn.execute(
            "INSERT INTO catalyst_events (ticker, catalyst_type, strategy_label, direction,"
            " headline, source, published_at, discovered_at, catalyst_score)"
            " VALUES ('', 'News Catalyst', 'News Catalyst', 'neutral', 'Macro headline',"
            " 'Yahoo Finance News', '2026-07-09T12:00:00Z', '2026-07-09T12:04:00Z', 30)")
        conn.execute(
            "INSERT INTO catalyst_events (ticker, catalyst_type, strategy_label, direction,"
            " headline, source, published_at, discovered_at, catalyst_score)"
            " VALUES ('ACME', 'SEC Filing', 'SEC Filing', 'bullish', 'ACME files 8-K',"
            " 'SEC EDGAR (8-K)', '2026-07-09T12:01:00Z', '2026-07-09T12:05:00Z', 75)")
        conn.commit()
    return db


FORBIDDEN_FRAGMENTS = (
    "avg_entry_price", "unrealized_pl", "market_value", "notional",
    "sms_phone_number", "push_subscription", "approval_queue", "alpaca_order_id",
)


def assert_envelope(body: dict, product: str):
    assert body["product"] == product and body["version"] == "v1"
    assert body["generated_at"] and body["provenance"]
    assert "not investment advice" in body["disclaimer"]
    dump = json.dumps(body).lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in dump, fragment


def test_all_products_return_safe_envelopes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTEL_COMMERCIAL_MODE", "false")   # internal/tailnet posture
    db = seeded_trading_db(tmp_path)
    assert_envelope(market_snapshot(db), "market-snapshot")
    assert_envelope(catalyst_feed(db), "catalysts")
    assert_envelope(daily_brief(db), "daily-brief")
    assert_envelope(calibration_report(db), "calibration")

    snap = market_snapshot(db)
    assert snap["data"]["market_regime"] == "risk-on watch"
    assert snap["data"]["btc_bias"] == "bullish"

    brief = daily_brief(db)
    assert brief["data"]["top_catalysts"][0]["headline"] == "NVDA wins contract"


def test_catalyst_feed_excludes_yahoo_from_paid_product(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTEL_COMMERCIAL_MODE", "false")   # yahoo is excluded in BOTH modes
    db = seeded_trading_db(tmp_path)
    events = catalyst_feed(db)["data"]["events"]
    sources = {e["provenance"]["source"] for e in events}
    assert "Polygon News / Newswire" in sources
    assert not any("yahoo" in s.lower() for s in sources)   # license posture


def client_with_key(tmp_path: Path, monkeypatch, x402_mode: str | None = None):
    db = seeded_trading_db(tmp_path)
    monkeypatch.setenv("INTEL_API_KEYS", "testagent:sk-test-123")
    monkeypatch.setenv("INTEL_DB_PATH", str(tmp_path / "intel.sqlite3"))
    if x402_mode:
        monkeypatch.setenv("INTEL_X402_MODE", x402_mode)
    else:
        monkeypatch.delenv("INTEL_X402_MODE", raising=False)
    store = IntelStore(str(tmp_path / "intel.sqlite3"))
    return TestClient(create_intel_app(db, store=store)), store


def test_gateway_auth_metering_and_catalog(tmp_path: Path, monkeypatch):
    client, store = client_with_key(tmp_path, monkeypatch)

    assert client.get("/health").json()["status"] == "ok"
    cat = client.get("/v1/catalog").json()                     # free, no key
    assert {p["product"] for p in cat["products"]} == set(CATALOG)

    assert client.get("/v1/market-snapshot").status_code == 401   # no key

    ok = client.get("/v1/market-snapshot",
                    headers={"Authorization": "Bearer sk-test-123"})
    assert ok.status_code == 200
    assert ok.json()["product"] == "market-snapshot"

    rollup = store.usage_rollup()
    assert rollup and rollup[0]["key_name"] == "testagent" and rollup[0]["calls"] == 1


def test_gateway_402_demo_challenge(tmp_path: Path, monkeypatch):
    client, _ = client_with_key(tmp_path, monkeypatch, x402_mode="demo")
    res = client.get("/v1/catalysts")                          # keyless -> 402
    assert res.status_code == 402
    body = res.json()
    assert body["x402Version"] == 1
    accept = body["accepts"][0]
    # spec-correct requirements (M3): asset is the USDC contract address and
    # the amount is atomic units (6 decimals), not a dollar string
    from alpha_lab.intel_x402 import NETWORKS
    assert accept["network"] == "base" and accept["asset"] == NETWORKS["base"]["usdc"]
    assert accept["maxAmountRequired"] == str(int(CATALOG["catalysts"]["price_usd"] * 1_000_000))
    assert "note" in body                                      # demo is labeled demo
    # keyed calls still work in demo mode
    assert client.get("/v1/catalysts",
                      headers={"Authorization": "Bearer sk-test-123"}).status_code == 200


def test_gateway_rate_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INTEL_RATE_PER_MIN", "3")
    client, store = client_with_key(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer sk-test-123"}
    codes = [client.get("/v1/market-snapshot", headers=headers).status_code
             for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
    assert any(r["calls"] for r in store.usage_rollup())


def test_ops_usage_requires_admin_key(tmp_path: Path, monkeypatch):
    client, _ = client_with_key(tmp_path, monkeypatch)
    monkeypatch.setenv("INTEL_ADMIN_KEY", "admin-abc")
    assert client.get("/v1/ops/usage").status_code == 401
    ok = client.get("/v1/ops/usage", headers={"Authorization": "Bearer admin-abc"})
    assert ok.status_code == 200 and "rollup_7d" in ok.json()


# ─── M2c: commercial mode is the DEFAULT and the license filter ──────────────

def test_commercial_mode_defaults_on_and_filters_products(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("INTEL_COMMERCIAL_MODE", raising=False)   # default = commercial
    db = seeded_trading_db(tmp_path)

    events = catalyst_feed(db)["data"]["events"]                 # SEC-EDGAR-only
    assert events, "license-clean SEC events must survive the commercial filter"
    assert all("sec edgar" in e["provenance"]["source"].lower() for e in events)

    snap = market_snapshot(db)                                   # recomposed snapshot
    assert_envelope(snap, "market-snapshot")
    assert snap["data"]["market_regime"]
    for withheld in ("narrative", "themes", "btc_bias"):
        assert withheld not in snap["data"]

    brief = daily_brief(db)                                      # deferred entirely
    assert brief["data"]["available"] is False
    assert "licens" in brief["data"]["reason"]


# ─── M2b: engine-native evaluation + glass-box explanation ───────────────────

EVAL_REQUEST = {
    "ticker": "NVDA", "bias": "bullish", "confidence": 0.7,
    "catalyst": "NVDA wins major government AI contract",
    "thesis": "Contract expands datacenter demand beyond consensus",
    "catalyst_type": "Government Contract", "catalyst_score": 82,
}


def test_signal_evaluation_deterministic_and_pv_neutral(tmp_path: Path):
    first = signal_evaluation(dict(EVAL_REQUEST))
    second = signal_evaluation(dict(EVAL_REQUEST))
    assert_envelope(first, "signal-evaluation")
    assert first["data"]["composite_score"] == second["data"]["composite_score"]
    assert first["data"]["tier"] == second["data"]["tier"]
    # PV-neutral commercial contract: unconfirmed by construction
    assert first["data"]["confirmed"] is False
    assert first["data"]["price_volume"]["evaluated"] is False
    assert set(first["data"]["components"]) == {"catalyst", "narrative", "macro"}
    assert all(c["signals"] for c in first["data"]["components"].values())

    import pytest
    with pytest.raises(ValueError):
        signal_evaluation({"ticker": "NVDA", "bias": "to-the-moon"})
    with pytest.raises(ValueError):
        signal_evaluation({"ticker": "", "bias": "bullish"})


def test_rest_evaluation_roundtrip_with_explanation(tmp_path: Path, monkeypatch):
    client, store = client_with_key(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer sk-test-123"}

    assert client.post("/v1/signal-evaluation", json=EVAL_REQUEST).status_code == 401
    bad = client.post("/v1/signal-evaluation", headers=headers,
                      json={"ticker": "NVDA", "bias": "sideways"})
    assert bad.status_code == 422

    res = client.post("/v1/signal-evaluation", headers=headers, json=EVAL_REQUEST)
    assert res.status_code == 200
    body = res.json()
    assert_envelope(body, "signal-evaluation")
    evaluation_id = body["data"]["evaluation_id"]
    assert evaluation_id and store.get_evaluation(evaluation_id)

    explained = client.get(f"/v1/decision-explanation/{evaluation_id}", headers=headers)
    assert explained.status_code == 200
    ex = explained.json()
    assert_envelope(ex, "decision-explanation")
    assert ex["data"]["verdict"]["composite_score"] == body["data"]["composite_score"]
    assert ex["data"]["component_reasoning"]["catalyst"]["sub_signals"]

    assert client.get("/v1/decision-explanation/nope", headers=headers).status_code == 404
    # evaluations are scoped to the key that created them
    monkeypatch.setenv("INTEL_API_KEYS", "testagent:sk-test-123,other:sk-other-9")
    assert client.get(f"/v1/decision-explanation/{evaluation_id}",
                      headers={"Authorization": "Bearer sk-other-9"}).status_code == 404


# ─── M2a: MCP transport runs the SAME gateway ────────────────────────────────

def rpc(client, method, params=None, msg_id=1, key=None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return client.post("/mcp", json=msg, headers=headers)


def test_mcp_initialize_and_tool_discovery(tmp_path: Path, monkeypatch):
    client, _ = client_with_key(tmp_path, monkeypatch)

    init = rpc(client, "initialize").json()["result"]
    assert init["protocolVersion"] and init["serverInfo"]["name"] == "alphalabs-intel"

    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "alphalabs_get_catalog", "alphalabs_calibration_report",
        "alphalabs_evaluate_signal", "alphalabs_explain_decision"}

    # notifications are acknowledged without a body
    note = client.post("/mcp", json={"jsonrpc": "2.0",
                                     "method": "notifications/initialized"})
    assert note.status_code == 202

    # catalog tool is free (no key)
    free = rpc(client, "tools/call", {"name": "alphalabs_get_catalog", "arguments": {}})
    catalog_payload = json.loads(free.json()["result"]["content"][0]["text"])
    assert {p["product"] for p in catalog_payload["products"]} == set(CATALOG)


def test_mcp_paid_tools_gated_and_metered(tmp_path: Path, monkeypatch):
    client, store = client_with_key(tmp_path, monkeypatch)

    denied = rpc(client, "tools/call",
                 {"name": "alphalabs_evaluate_signal", "arguments": EVAL_REQUEST})
    assert denied.json()["error"]["data"]["http_status"] == 401

    res = rpc(client, "tools/call",
              {"name": "alphalabs_evaluate_signal", "arguments": EVAL_REQUEST},
              key="sk-test-123")
    payload = json.loads(res.json()["result"]["content"][0]["text"])
    assert_envelope(payload, "signal-evaluation")
    evaluation_id = payload["data"]["evaluation_id"]

    explained = rpc(client, "tools/call",
                    {"name": "alphalabs_explain_decision",
                     "arguments": {"evaluation_id": evaluation_id}},
                    key="sk-test-123")
    ex = json.loads(explained.json()["result"]["content"][0]["text"])
    assert_envelope(ex, "decision-explanation")

    rollup = store.usage_rollup()
    assert any(r["interface"] == "mcp" for r in rollup)          # metered as MCP lane

    bad_args = rpc(client, "tools/call",
                   {"name": "alphalabs_evaluate_signal",
                    "arguments": {"ticker": "NVDA", "bias": "sideways"}},
                   key="sk-test-123")
    assert bad_args.json()["error"]["data"]["http_status"] == 422


def test_commercial_catalysts_survive_vendor_noise(tmp_path: Path, monkeypatch):
    """M2.x regression: the license filter must be in the SQL, not applied
    after a recency LIMIT — 60 fresher vendor rows must not starve the feed
    of the older license-clean SEC event."""
    monkeypatch.delenv("INTEL_COMMERCIAL_MODE", raising=False)
    db = seeded_trading_db(tmp_path)
    with connect(db) as conn:
        for i in range(60):
            conn.execute(
                "INSERT INTO catalyst_events (ticker, catalyst_type, strategy_label,"
                " direction, headline, source, published_at, discovered_at, catalyst_score)"
                f" VALUES ('T{i}', 'News Catalyst', 'News Catalyst', 'neutral',"
                f" 'Vendor headline {i}', 'Polygon News / Newswire',"
                " '2026-07-09T15:00:00Z', '2026-07-09T15:00:00Z', 40)")
        conn.commit()
    events = catalyst_feed(db, limit=10)["data"]["events"]
    assert events, "SEC event must surface despite 60 fresher vendor rows"
    assert all("sec edgar" in e["provenance"]["source"].lower() for e in events)
