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
import urllib.error
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
        # CDP facilitator (auth required; wired at M3-live after KYB).
        "facilitator": "https://api.cdp.coinbase.com/platform/v2/x402",
        "eip712_name": "USDC",          # verify against CDP docs at M3-live
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
        "resource": f"/v1/{product}",
        "description": CATALOG.get(product, {}).get("summary", ""),
        "mimeType": "application/json",
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
        bearer = os.getenv("INTEL_X402_FACILITATOR_BEARER", "").strip()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint}", method="POST",
            data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return json.load(response)

    def _rpc(self, endpoint: str, payload: dict[str, Any],
             requirements: dict[str, Any]) -> dict[str, Any]:
        body = {"x402Version": X402_VERSION, "paymentPayload": payload,
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
