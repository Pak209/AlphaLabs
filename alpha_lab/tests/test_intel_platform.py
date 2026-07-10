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


def test_all_products_return_safe_envelopes(tmp_path: Path):
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


def test_catalyst_feed_excludes_yahoo_from_paid_product(tmp_path: Path):
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
    assert accept["network"] == "base" and accept["asset"] == "USDC"
    assert accept["maxAmountRequired"] == str(CATALOG["catalysts"]["price_usd"])
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
