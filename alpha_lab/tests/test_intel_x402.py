"""Intelligence Platform M3-sandbox: the x402 payment lane.

Contracts that matter before real (test) money flows:
  * keyless calls in sandbox mode get a SPEC-CORRECT 402 challenge
    (atomic USDC units, asset contract address, Base Sepolia network)
  * verify runs BEFORE the product, settle AFTER it succeeds — a failed
    settlement withholds output, a failed product never charges
  * replay of a used authorization nonce is refused
  * settled payments land in the payments table and usage rows carry the
    payment id

The facilitator is faked at FacilitatorClient._post — no network, no chain.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

from alpha_lab import intel_x402
from alpha_lab.tests.test_intel_platform import EVAL_REQUEST, client_with_key

PAY_TO = "0xReceiver00000000000000000000000000000001"
PAYER = "0xPayer0000000000000000000000000000000002"
SEPOLIA_USDC = intel_x402.NETWORKS["base-sepolia"]["usdc"]


def payment_header(nonce: str = "0xnonce-1", to: str = PAY_TO, value: str = "20000",
                   network: str = "base-sepolia", version: int = 1) -> str:
    payload = {
        "x402Version": version, "scheme": "exact", "network": network,
        "payload": {"signature": "0xsig",
                    "authorization": {"from": PAYER, "to": to, "value": value,
                                      "validAfter": "0", "validBefore": "99999999999",
                                      "nonce": nonce}},
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def fake_facilitator(monkeypatch, *, verify_ok: bool = True, settle_ok: bool = True):
    calls: list[str] = []

    def _post(self, endpoint, body):
        calls.append(endpoint)
        if endpoint == "verify":
            return {"isValid": True, "payer": PAYER} if verify_ok else \
                   {"isValid": False, "invalidReason": "insufficient_funds"}
        return {"success": True, "transaction": "0xtxhash", "network": "base-sepolia",
                "payer": PAYER} if settle_ok else \
               {"success": False, "errorReason": "broadcast_failed"}

    monkeypatch.setattr(intel_x402.FacilitatorClient, "_post", _post)
    return calls


def sandbox_client(tmp_path: Path, monkeypatch):
    client, store = client_with_key(tmp_path, monkeypatch)
    monkeypatch.setenv("INTEL_X402_MODE", "sandbox")
    monkeypatch.setenv("INTEL_X402_PAY_TO", PAY_TO)
    return client, store


def payments_rows(store) -> list[dict]:
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute("SELECT * FROM payments").fetchall()]


def test_sandbox_challenge_is_spec_correct(tmp_path: Path, monkeypatch):
    client, _ = sandbox_client(tmp_path, monkeypatch)
    res = client.get("/v1/catalysts")                       # keyless, no payment
    assert res.status_code == 402
    body = res.json()
    assert body["x402Version"] == 1
    accept = body["accepts"][0]
    assert accept["network"] == "base-sepolia"
    assert accept["maxAmountRequired"] == "20000"           # $0.02 in atomic USDC
    assert accept["asset"] == SEPOLIA_USDC                  # contract, not a ticker
    assert accept["payTo"] == PAY_TO
    assert accept["extra"] == {"name": "USDC", "version": "2"}
    assert "note" not in body                               # demo note is demo-only


def test_x402_happy_path_settles_and_meters(tmp_path: Path, monkeypatch):
    client, store = sandbox_client(tmp_path, monkeypatch)
    calls = fake_facilitator(monkeypatch)

    res = client.get("/v1/catalysts", headers={"X-PAYMENT": payment_header()})
    assert res.status_code == 200
    assert res.json()["product"] == "catalysts"
    settlement = json.loads(base64.b64decode(res.headers["X-PAYMENT-RESPONSE"]))
    assert settlement["success"] and settlement["transaction"] == "0xtxhash"
    assert calls == ["verify", "settle"]                    # verify before settle

    rows = payments_rows(store)
    assert len(rows) == 1
    assert rows[0]["payment_id"] == "0xnonce-1" and rows[0]["tx_hash"] == "0xtxhash"
    assert rows[0]["payer"] == PAYER and rows[0]["amount_usdc"] == 0.02

    conn = sqlite3.connect(store.db_path)
    usage = conn.execute("SELECT key_name, status, x402_payment_id FROM usage").fetchone()
    assert usage == (f"x402:{PAYER}", 200, "0xnonce-1")


def test_x402_replay_rejected(tmp_path: Path, monkeypatch):
    client, store = sandbox_client(tmp_path, monkeypatch)
    fake_facilitator(monkeypatch)
    header = payment_header(nonce="0xonce-only")

    assert client.get("/v1/catalysts", headers={"X-PAYMENT": header}).status_code == 200
    replay = client.get("/v1/catalysts", headers={"X-PAYMENT": header})
    assert replay.status_code == 402
    assert "replay" in replay.json()["error"]
    assert len(payments_rows(store)) == 1                   # charged exactly once


def test_x402_verify_failure_never_settles_or_serves(tmp_path: Path, monkeypatch):
    client, store = sandbox_client(tmp_path, monkeypatch)
    calls = fake_facilitator(monkeypatch, verify_ok=False)

    res = client.get("/v1/catalysts", headers={"X-PAYMENT": payment_header()})
    assert res.status_code == 402
    assert "insufficient_funds" in res.json()["error"]
    assert calls == ["verify"]                              # settle never attempted
    assert payments_rows(store) == []


def test_x402_settle_failure_withholds_product(tmp_path: Path, monkeypatch):
    client, store = sandbox_client(tmp_path, monkeypatch)
    fake_facilitator(monkeypatch, settle_ok=False)

    res = client.get("/v1/catalysts", headers={"X-PAYMENT": payment_header()})
    assert res.status_code == 402
    body = res.json()
    assert "settlement failed" in body["error"]
    assert "data" not in body and "product" not in body     # no product output leaked
    assert payments_rows(store) == []


def test_x402_local_checks_reject_before_facilitator(tmp_path: Path, monkeypatch):
    client, _ = sandbox_client(tmp_path, monkeypatch)
    calls = fake_facilitator(monkeypatch)

    cases = {
        payment_header(to="0xSomeoneElse"): "recipient mismatch",
        payment_header(value="19999"): "amount below required",
        payment_header(network="base"): "network mismatch",
        "not-base64!!": "malformed",
    }
    for header, expected in cases.items():
        res = client.get("/v1/catalysts", headers={"X-PAYMENT": header})
        assert res.status_code == 402
        assert expected in res.json()["error"]
    assert calls == []                                      # all rejected locally


def test_x402_pays_for_evaluation_and_explanation(tmp_path: Path, monkeypatch):
    client, store = sandbox_client(tmp_path, monkeypatch)
    fake_facilitator(monkeypatch)

    res = client.post("/v1/signal-evaluation", json=EVAL_REQUEST,
                      headers={"X-PAYMENT": payment_header(nonce="0xeval", value="100000")})
    assert res.status_code == 200
    evaluation_id = res.json()["data"]["evaluation_id"]

    # same payer, fresh authorization — evaluation scoping follows the wallet
    explained = client.get(f"/v1/decision-explanation/{evaluation_id}",
                           headers={"X-PAYMENT": payment_header(nonce="0xexplain",
                                                                value="100000")})
    assert explained.status_code == 200
    assert explained.json()["data"]["verdict"]["composite_score"] == \
           res.json()["data"]["composite_score"]

    # a miss never charges: unknown id -> 404 and no third settlement
    missing = client.get("/v1/decision-explanation/nope",
                         headers={"X-PAYMENT": payment_header(nonce="0xmiss",
                                                              value="100000")})
    assert missing.status_code == 404
    assert {r["payment_id"] for r in payments_rows(store)} == {"0xeval", "0xexplain"}


def test_api_keys_still_work_in_sandbox_mode(tmp_path: Path, monkeypatch):
    client, _ = sandbox_client(tmp_path, monkeypatch)
    res = client.get("/v1/catalysts", headers={"Authorization": "Bearer sk-test-123"})
    assert res.status_code == 200
    assert "X-PAYMENT-RESPONSE" not in res.headers


def test_facilitator_requests_carry_descriptive_user_agent(monkeypatch):
    """The x402.org WAF 403s python-urllib's default UA (live probe finding)."""
    captured = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"isValid": true}'

    def fake_urlopen(request, timeout=None):
        captured["ua"] = request.get_header("User-agent")
        return FakeResponse()

    monkeypatch.setattr(intel_x402.urllib.request, "urlopen", fake_urlopen)
    intel_x402.FacilitatorClient().verify({"x402Version": 1}, {"network": "base"})
    assert captured["ua"] and "urllib" not in captured["ua"].lower()
    assert "AlphaLabs" in captured["ua"]


def test_free_beta_products_never_enter_payment_lane(tmp_path, monkeypatch):
    """Self-serve posture: telemetry is free in beta — keyless callers get a
    key hint (401), never a zero-dollar 402, even with the lane active."""
    client, store = sandbox_client(tmp_path, monkeypatch)
    fake_facilitator(monkeypatch)

    res = client.get("/v1/calibration")                         # keyless, free product
    assert res.status_code == 401
    assert "key" in res.json()["detail"].lower()

    # even a valid payment header is ignored for a free product
    res = client.get("/v1/outcome-report", headers={"X-PAYMENT": payment_header()})
    assert res.status_code == 401
    assert payments_rows(store) == []

    # keys still work and nothing is charged
    ok = client.get("/v1/feature-attribution",
                    headers={"Authorization": "Bearer sk-test-123"})
    assert ok.status_code == 200
    assert ok.json()["usage"]["product_price_usd"] == 0.0


# ─── M3-live prep: CDP facilitator JWT auth ──────────────────────────────────

def _fake_cdp_env(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    private = Ed25519PrivateKey.generate()
    seed = private.private_bytes(serialization.Encoding.Raw,
                                 serialization.PrivateFormat.Raw,
                                 serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
    monkeypatch.setenv("CDP_API_KEY_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("CDP_API_KEY_SECRET",
                       base64.b64encode(seed + public).decode())
    return private.public_key()


def test_cdp_jwt_structure_and_signature(monkeypatch):
    public_key = _fake_cdp_env(monkeypatch)
    token = intel_x402._cdp_jwt("POST", "https://api.cdp.coinbase.com/platform/v2/x402/settle")
    head_b64, claims_b64, sig_b64 = token.split(".")

    def unb64(part):
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))

    header, claims = unb64(head_b64), unb64(claims_b64)
    assert header["alg"] == "EdDSA" and header["typ"] == "JWT"
    assert header["kid"] == claims["sub"] == "11111111-2222-3333-4444-555555555555"
    assert len(header["nonce"]) == 16
    assert claims["iss"] == "cdp" and claims["aud"] == ["cdp_service"]
    assert claims["uri"] == "POST api.cdp.coinbase.com/platform/v2/x402/settle"
    assert claims["exp"] - claims["nbf"] == 120
    # the signature must verify against the derived public key
    signature = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    public_key.verify(signature, f"{head_b64}.{claims_b64}".encode())


def test_facilitator_uses_cdp_jwt_when_configured(monkeypatch):
    _fake_cdp_env(monkeypatch)
    monkeypatch.delenv("INTEL_X402_FACILITATOR_BEARER", raising=False)
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"isValid": true}'
        return R()

    monkeypatch.setattr(intel_x402.urllib.request, "urlopen", fake_urlopen)
    intel_x402.FacilitatorClient().verify({"x402Version": 1}, {"network": "base"})
    assert captured["auth"].startswith("Bearer ")
    assert captured["auth"].count(".") == 2          # three JWT segments


def test_static_bearer_wins_over_cdp_jwt(monkeypatch):
    _fake_cdp_env(monkeypatch)
    monkeypatch.setenv("INTEL_X402_FACILITATOR_BEARER", "static-token")
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{}'
        return R()

    monkeypatch.setattr(intel_x402.urllib.request, "urlopen", fake_urlopen)
    intel_x402.FacilitatorClient().verify({}, {"network": "base"})
    assert captured["auth"] == "Bearer static-token"
