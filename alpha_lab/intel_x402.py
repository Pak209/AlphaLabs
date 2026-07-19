"""
alpha_lab/intel_x402.py — the x402 payment lane (M3-sandbox).

x402 in one paragraph: a keyless caller gets HTTP 402 with machine-readable
payment requirements; it signs an EIP-3009 USDC transferWithAuthorization
for the exact amount and retries with the signed payload base64-encoded in
the X-PAYMENT header; the server verifies the signature via a facilitator,
serves the product, settles on-chain through the same facilitator, and
returns X-PAYMENT-RESPONSE with the transaction. No account, no key, no
card — an agent with a funded wallet can buy one API call.

Modes (INTEL_X402_MODE):
  off      — keyless calls get 401 (M1 behavior)
  demo     — keyless calls get a spec-shaped 402 challenge; no settlement
  sandbox  — REAL verify+settle on Base Sepolia testnet USDC via the free
             x402.org facilitator (this milestone). Test money only.
  live     — Base mainnet USDC via the CDP facilitator. GATED: requires the
             dedicated business wallet + CDP KYB (human decisions of record)
             — never a personal wallet.

This module is deliberately stdlib-only (urllib) — no new dependencies on
the runner. The facilitator does the cryptography; we do local sanity
checks (scheme/network/payTo/amount) and replay protection via the
payments table's UNIQUE payment_id (the EIP-3009 nonce).
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .intel_products import CATALOG

X402_VERSION = 1
USDC_DECIMALS = 6

# Chain + facilitator parameters per network. USDC contract addresses are
# Circle's canonical deployments; the EIP-712 domain (extra) is what payers
# use to sign transferWithAuthorization.
NETWORKS: dict[str, dict[str, str]] = {
    "base-sepolia": {
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "facilitator": "https://x402.org/facilitator",
        "eip712_name": "USDC",
        "eip712_version": "2",
    },
    "base": {
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        # CDP facilitator (per-request EdDSA JWT auth via CDP_API_KEY_ID/SECRET).
        "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
        # Verified 2026-07-12 against the on-chain DOMAIN_SEPARATOR (0x02fa7265...):
        # mainnet USDC signs as "USD Coin"/"2" — NOT "USDC" like Base Sepolia.
        # A payer signing with the wrong domain fails verification silently.
        "eip712_name": "USD Coin",
        "eip712_version": "2",
    },
}


def x402_mode() -> str:
    return os.getenv("INTEL_X402_MODE", "off").strip().lower()


def x402_network() -> str:
    """sandbox pays on testnet; demo/live describe mainnet."""
    return "base-sepolia" if x402_mode() == "sandbox" else "base"


def pay_to_address() -> str:
    return os.getenv("INTEL_X402_PAY_TO", "").strip()


def public_base_url() -> str:
    """Canonical public origin for absolute resource URLs (Bazaar catalogs by
    the full URL an agent actually calls — a relative path is uncatalogable)."""
    return os.getenv("INTEL_PUBLIC_BASE_URL", "https://api.pak-labs.com").strip().rstrip("/")


def payment_lane_ready() -> bool:
    """True when a real (sandbox/live) payment lane is configured."""
    return x402_mode() in {"sandbox", "live"} and bool(pay_to_address())


def atomic_amount(price_usd: float) -> str:
    """USDC atomic units (6 decimals) as the spec's string integer."""
    return str(int(round(float(price_usd) * 10 ** USDC_DECIMALS)))


def payment_requirements(product: str) -> dict[str, Any]:
    """Spec-correct PaymentRequirements for one product on the active network."""
    network = x402_network()
    params = NETWORKS[network]
    price = CATALOG.get(product, {}).get("price_usd", 0.01)
    return {
        "scheme": "exact",
        "network": network,
        "maxAmountRequired": atomic_amount(price),
        "resource": f"{public_base_url()}/v1/{product}",
        "description": CATALOG.get(product, {}).get("summary", "")[:500],
        "mimeType": "application/json",
        "outputSchema": {
            "type": "object",
            "description": "AlphaLabs standard envelope: product, version, generated_at, "
                           "data, provenance, confidence, reasoning, disclaimer. "
                           "Full schema at " + public_base_url() + "/openapi.json",
        },
        "payTo": pay_to_address() or "<unset — demo mode>",
        "maxTimeoutSeconds": 60,
        "asset": params["usdc"],
        "extra": {"name": params["eip712_name"], "version": params["eip712_version"]},
    }


def challenge_body(product: str, error: str = "payment required") -> dict[str, Any]:
    body = {
        "x402Version": X402_VERSION,
        "error": error,
        "accepts": [payment_requirements(product)],
    }
    if x402_mode() == "demo":
        body["note"] = ("demo challenge — no settlement in demo mode; use an API key, "
                        "or ask for sandbox access (Base Sepolia testnet USDC)")
    return body


def decode_payment_header(header: str) -> Optional[dict[str, Any]]:
    """X-PAYMENT is base64(JSON PaymentPayload); None if malformed."""
    try:
        decoded = json.loads(base64.b64decode(header, validate=True))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def encode_settlement_header(settlement: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(settlement, default=str).encode()).decode()


def _cdp_jwt(method: str, url: str) -> Optional[str]:
    """Per-request CDP Bearer JWT (EdDSA) from CDP_API_KEY_ID/SECRET.

    CDP secret API keys are Ed25519 (base64 seed+public, 64 bytes); the JWT
    binds to one request via the uri claim and expires in 120s — per
    docs.cdp.coinbase.com/api-reference/v2/authentication. Hand-rolled on
    `cryptography` (already a dependency) so no CDP SDK is needed.
    Returns None when the envs aren't set (static-bearer or free
    facilitators need no auth).
    """
    key_id = os.getenv("CDP_API_KEY_ID", "").strip()
    secret = os.getenv("CDP_API_KEY_SECRET", "").strip()
    if not key_id or not secret:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    parsed = urllib.parse.urlparse(url)
    private = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
    now = int(time.time())
    header = {"alg": "EdDSA", "kid": key_id, "typ": "JWT",
              "nonce": secrets.token_hex(8)}
    claims = {"sub": key_id, "iss": "cdp", "aud": ["cdp_service"],
              "nbf": now, "exp": now + 120,
              "uri": f"{method} {parsed.netloc}{parsed.path}"}

    def b64url(obj: dict) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()

    signing_input = f"{b64url(header)}.{b64url(claims)}"
    signature = base64.urlsafe_b64encode(
        private.sign(signing_input.encode())).rstrip(b"=").decode()
    return f"{signing_input}.{signature}"


class FacilitatorClient:
    """verify/settle against an x402 facilitator over HTTPS (stdlib only).

    Sandbox default is the free x402.org facilitator; INTEL_X402_FACILITATOR_URL
    overrides, INTEL_X402_FACILITATOR_BEARER adds an Authorization header
    (the CDP facilitator will need it at M3-live).
    """

    def __init__(self, timeout_s: float = 20.0):
        self.timeout_s = timeout_s

    @property
    def base_url(self) -> str:
        override = os.getenv("INTEL_X402_FACILITATOR_URL", "").strip()
        return (override or NETWORKS[x402_network()]["facilitator"]).rstrip("/")

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        # A descriptive UA is required in practice: the x402.org facilitator's
        # WAF returns 403 to Python-urllib's default (found by the M3 probe).
        headers = {"Content-Type": "application/json",
                   "User-Agent": "AlphaLabs-Intel/0.2 (+x402 seller)"}
        url = f"{self.base_url}/{endpoint}"
        # Auth precedence: explicit static bearer wins; else a per-request CDP
        # JWT when CDP_API_KEY_ID/SECRET are configured; else unauthenticated
        # (the free x402.org facilitator).
        bearer = os.getenv("INTEL_X402_FACILITATOR_BEARER", "").strip() or _cdp_jwt("POST", url)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(
            url, method="POST",
            data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return json.load(response)

    def _rpc(self, endpoint: str, payload: dict[str, Any],
             requirements: dict[str, Any]) -> dict[str, Any]:
        # The RPC envelope's version follows the payload's protocol (a v2
        # payload in a v1 envelope settles, but indexing reads the envelope).
        body = {"x402Version": payload.get("x402Version", X402_VERSION),
                "paymentPayload": payload,
                "paymentRequirements": requirements}
        try:
            return self._post(endpoint, body)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"_facilitator_error": f"{endpoint} unreachable: {exc}"}

    def verify(self, payload: dict[str, Any],
               requirements: dict[str, Any]) -> dict[str, Any]:
        return self._rpc("verify", payload, requirements)

    def settle(self, payload: dict[str, Any],
               requirements: dict[str, Any]) -> dict[str, Any]:
        return self._rpc("settle", payload, requirements)


def local_payment_checks(payload: dict[str, Any],
                         requirements: dict[str, Any]) -> Optional[str]:
    """Cheap sanity checks before spending a facilitator round-trip.

    The facilitator owns signature/balance verification; these only reject
    payloads that can't possibly match what we asked for.
    """
    if payload.get("x402Version") != X402_VERSION:
        return "unsupported x402 version"
    if payload.get("scheme") != requirements["scheme"]:
        return "scheme mismatch (expected exact)"
    if payload.get("network") != requirements["network"]:
        return f"network mismatch (expected {requirements['network']})"
    authorization = (payload.get("payload") or {}).get("authorization") or {}
    if str(authorization.get("to", "")).lower() != requirements["payTo"].lower():
        return "payment recipient mismatch"
    try:
        if int(str(authorization.get("value", "0"))) < int(requirements["maxAmountRequired"]):
            return "payment amount below required"
    except ValueError:
        return "malformed payment amount"
    if not authorization.get("nonce"):
        return "missing authorization nonce"
    return None


# ─── x402 v2 (dual-stack): headers-based transport + Bazaar discovery ────────
# v2 rides ALONGSIDE v1 on the same responses: the 402 keeps the v1 JSON body
# (proven, earning) and adds the v2 PAYMENT-REQUIRED header; payments are
# accepted from either X-PAYMENT (v1) or PAYMENT-SIGNATURE (v2). The Bazaar
# indexes from the v2 envelope's top-level extensions — the earlier v1-shaped
# attempt could never index (docs/X402_BAZAAR_FINDINGS.md).

CAIP2 = {"base": "eip155:8453", "base-sepolia": "eip155:84532"}
CAIP2_REVERSE = {v: k for k, v in CAIP2.items()}


def resource_object(product: str) -> dict[str, Any]:
    return {
        "url": f"{public_base_url()}/v1/{product}",
        "description": CATALOG.get(product, {}).get("summary", "")[:500],
        "mimeType": "application/json",
    }


def payment_requirements_v2(product: str) -> dict[str, Any]:
    network = x402_network()
    params = NETWORKS[network]
    price = CATALOG.get(product, {}).get("price_usd", 0.01)
    return {
        "scheme": "exact",
        "network": CAIP2[network],
        "amount": atomic_amount(price),
        "asset": params["usdc"],
        "payTo": pay_to_address() or "<unset>",
        "maxTimeoutSeconds": 60,
        "extra": {"name": params["eip712_name"], "version": params["eip712_version"]},
    }


def bazaar_extension(product: str) -> dict[str, Any]:
    """Discovery declaration per specs/extensions/bazaar.md (info + schema)."""
    method = CATALOG.get(product, {}).get("method", "GET")
    envelope_example = {"product": product, "version": "v1", "data": {},
                        "disclaimer": "not investment advice"}
    if method == "POST":
        info_input: dict[str, Any] = {
            "type": "http", "method": "POST", "bodyType": "json",
            "body": {"ticker": "NVDA", "bias": "bullish",
                     "catalyst": "example catalyst headline"},
        }
        input_schema = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["POST", "PUT", "PATCH"]},
                "bodyType": {"type": "string", "enum": ["json", "form-data", "text"]},
                "body": {"type": "object"},
            },
            "required": ["type", "method", "bodyType", "body"],
            "additionalProperties": False,
        }
    else:
        info_input = {"type": "http", "method": "GET"}
        input_schema = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["GET", "HEAD", "DELETE"]},
                "queryParams": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["type", "method"],
            "additionalProperties": False,
        }
    return {
        "info": {"input": info_input,
                 "output": {"type": "json", "example": envelope_example}},
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "input": input_schema,
                "output": {
                    "type": "object",
                    "properties": {"type": {"type": "string", "const": "json"},
                                   "example": {"type": "object"}},
                    "required": ["type", "example"],
                    "additionalProperties": False,
                },
            },
            "required": ["input", "output"],
            "additionalProperties": False,
        },
    }


def challenge_v2(product: str, error: str = "payment required") -> dict[str, Any]:
    return {
        "x402Version": 2,
        "error": error,
        "resource": resource_object(product),
        "accepts": [payment_requirements_v2(product)],
        "extensions": {"bazaar": bazaar_extension(product)},
    }


def _b64_json(obj: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj, default=str).encode()).decode()


def challenge_v2_header(product: str, error: str = "payment required") -> str:
    return _b64_json(challenge_v2(product, error))


def local_payment_checks_v2(payload: dict[str, Any], product: str) -> Optional[str]:
    """Sanity checks on a decoded PAYMENT-SIGNATURE payload before the
    facilitator round-trip — mirrors the v1 checks."""
    if payload.get("x402Version") != 2:
        return "unsupported x402 version in PAYMENT-SIGNATURE"
    accepted = payload.get("accepted") or {}
    ours = payment_requirements_v2(product)
    if accepted.get("scheme") != ours["scheme"]:
        return "scheme mismatch (expected exact)"
    if accepted.get("network") != ours["network"]:
        return f"network mismatch (expected {ours['network']})"
    authorization = (payload.get("payload") or {}).get("authorization") or {}
    if str(authorization.get("to", "")).lower() != ours["payTo"].lower():
        return "payment recipient mismatch"
    try:
        if int(str(authorization.get("value", "0"))) < int(ours["amount"]):
            return "payment amount below required"
    except ValueError:
        return "malformed payment amount"
    if not authorization.get("nonce"):
        return "missing authorization nonce"
    return None


def inject_bazaar_extension(payload: dict[str, Any], product: str) -> dict[str, Any]:
    """Ensure the PaymentPayload forwarded to the facilitator carries OUR
    bazaar declaration. Per specs/extensions/bazaar.md ('when a facilitator
    receives a PaymentPayload containing the bazaar extension...'), indexing
    reads the PAYLOAD — clients are supposed to echo the challenge's
    extensions, but the server is the source of truth for its own catalog
    entry, so we inject rather than depend on client behavior."""
    extensions = dict(payload.get("extensions") or {})
    extensions["bazaar"] = bazaar_extension(product)
    return {**payload, "extensions": extensions}
