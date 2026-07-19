"""
alpha_lab/intel_gateway.py — the shared gateway stack (M2a).

Extracted from intel_api so REST and MCP run the SAME auth → x402 seam →
rate limit → metering pipeline (plan §4 architecture validation: REST and
MCP are siblings behind one gateway; x402 is a lane inside auth). Keys,
usage, payments, and stored evaluations live in the platform's OWN SQLite —
never the trading DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from . import intel_x402
from .intel_products import CATALOG

INTEL_DB_DEFAULT = "alpha_lab/data/intel_platform.sqlite3"
DEFAULT_RATE_PER_MIN = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key_hash TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'research',
  rate_per_min INTEGER NOT NULL DEFAULT 60,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key_name TEXT NOT NULL,
  product TEXT NOT NULL,
  status INTEGER NOT NULL,
  latency_ms REAL,
  x402_payment_id TEXT,
  interface TEXT NOT NULL DEFAULT 'rest',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id TEXT NOT NULL UNIQUE,
  product TEXT NOT NULL,
  amount_usdc REAL NOT NULL,
  payer TEXT,
  network TEXT,
  tx_hash TEXT,
  settled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  evaluation_id TEXT NOT NULL UNIQUE,
  key_name TEXT NOT NULL,
  request_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class IntelStore:
    """Keys, usage, payments, and stored evaluations — platform DB only."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("INTEL_DB_PATH", INTEL_DB_DEFAULT)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            # additive migration for pre-M2 stores
            cols = [r[1] for r in conn.execute("PRAGMA table_info(usage)").fetchall()]
            if "interface" not in cols:
                conn.execute("ALTER TABLE usage ADD COLUMN interface TEXT NOT NULL DEFAULT 'rest'")
            pay_cols = [r[1] for r in conn.execute("PRAGMA table_info(payments)").fetchall()]
            if "tx_hash" not in pay_cols:
                conn.execute("ALTER TABLE payments ADD COLUMN tx_hash TEXT")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def resolve_key(self, raw: str) -> dict[str, Any] | None:
        for pair in os.getenv("INTEL_API_KEYS", "").split(","):
            if ":" in pair:
                name, key = pair.split(":", 1)
                if hmac.compare_digest(key.strip(), raw):
                    return {"name": name.strip(), "tier": "seed",
                            "rate_per_min": int(os.getenv("INTEL_RATE_PER_MIN", DEFAULT_RATE_PER_MIN))}
        with self._conn() as conn:
            row = conn.execute(
                "SELECT name, tier, rate_per_min FROM api_keys "
                "WHERE key_hash = ? AND revoked_at IS NULL",
                (_hash_key(raw),),
            ).fetchone()
        return dict(row) if row else None

    def record_usage(self, key_name: str, product: str, status: int,
                     latency_ms: float, payment_id: str | None = None,
                     interface: str = "rest") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO usage (key_name, product, status, latency_ms, x402_payment_id, interface) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key_name, product, status, round(latency_ms, 2), payment_id, interface),
            )
            conn.commit()

    def usage_rollup(self, limit_days: int = 7) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                """
                SELECT date(created_at) AS day, product, key_name, interface,
                       COUNT(*) AS calls, AVG(latency_ms) AS avg_latency_ms,
                       SUM(status = 200) AS ok
                FROM usage
                WHERE datetime(created_at) >= datetime('now', ?)
                GROUP BY day, product, key_name, interface ORDER BY day DESC, calls DESC
                """,
                (f"-{int(limit_days)} days",),
            ).fetchall()]

    def issue_key(self, name: str, tier: str = "beta-faucet",
                  rate_per_min: int = 30) -> str:
        """Create a key, store only its hash, return the raw key ONCE."""
        import secrets
        raw = f"sk-intel-{secrets.token_urlsafe(24)}"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, name, tier, rate_per_min) VALUES (?, ?, ?, ?)",
                (_hash_key(raw), name, tier, rate_per_min))
            conn.commit()
        return raw

    def key_name_exists(self, name: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM api_keys WHERE name = ? AND revoked_at IS NULL",
                                (name,)).fetchone() is not None

    def count_keys(self, tier: str) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM api_keys WHERE tier = ?",
                                (tier,)).fetchone()[0]

    def count_ok_calls(self, key_name: str) -> int:
        """Lifetime successful calls — the beta allowance meter (errors are free)."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM usage WHERE key_name = ? AND status = 200",
                (key_name,)).fetchone()[0]

    def store_evaluation(self, key_name: str, request: dict[str, Any],
                         result: dict[str, Any]) -> str:
        evaluation_id = uuid.uuid4().hex[:16]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO evaluations (evaluation_id, key_name, request_json, result_json) "
                "VALUES (?, ?, ?, ?)",
                (evaluation_id, key_name, json.dumps(request, default=str),
                 json.dumps(result, default=str)),
            )
            conn.commit()
        return evaluation_id

    def has_payment(self, payment_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM payments WHERE payment_id = ?",
                                (payment_id,)).fetchone() is not None

    def record_payment(self, payment_id: str, product: str, amount_usdc: float,
                       payer: str, network: str, tx_hash: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO payments (payment_id, product, amount_usdc, payer, network, tx_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (payment_id, product, amount_usdc, payer, network, tx_hash),
            )
            conn.commit()

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT evaluation_id, key_name, request_json, result_json, created_at "
                "FROM evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        if not row:
            return None
        return {"evaluation_id": row["evaluation_id"], "key_name": row["key_name"],
                "request": json.loads(row["request_json"]),
                "result": json.loads(row["result_json"]),
                "created_at": row["created_at"]}


class RateLimiter:
    """Per-key sliding-minute window (in-process; edge rules layer on at M4)."""

    def __init__(self):
        self.hits: dict[str, list[float]] = {}

    def allow(self, key_name: str, per_min: int) -> bool:
        now = time.monotonic()
        window = [t for t in self.hits.get(key_name, []) if now - t < 60]
        if len(window) >= per_min:
            self.hits[key_name] = window
            return False
        window.append(now)
        self.hits[key_name] = window
        return True


def x402_challenge_body(product: str, error: str = "payment required") -> dict[str, Any]:
    """Spec-correct 402 payment-requirements body (see intel_x402)."""
    return intel_x402.challenge_body(product, error=error)


class Gateway:
    """One authorize/meter pipeline shared by REST and MCP."""

    def __init__(self, store: IntelStore | None = None):
        self.store = store or IntelStore()
        self.limiter = RateLimiter()
        self.facilitator = intel_x402.FacilitatorClient()

    def authorize(self, raw_key: str, product: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
        """Returns (key, error_body, error_status). Exactly one of key/error set."""
        key = self.store.resolve_key(raw_key) if raw_key else None
        if not key:
            # Free-in-beta products are never payable — keyless callers get the
            # key hint, not a 402 for zero dollars.
            paid = CATALOG.get(product, {}).get("price_usd", 0) > 0
            if paid and intel_x402.x402_mode() in {"demo", "sandbox", "live"}:
                return None, x402_challenge_body(product), 402
            return None, {"detail": "API key required (Authorization: Bearer <key>). "
                                    "See /v1/catalog for products and the x402 payment lane."}, 401
        if not self.limiter.allow(key["name"], int(key.get("rate_per_min") or DEFAULT_RATE_PER_MIN)):
            return None, {"detail": "rate limit exceeded"}, 429
        if key.get("tier") == "beta-faucet":
            allowance = int(os.getenv("INTEL_BETA_CALL_ALLOWANCE", "100"))
            if self.store.count_ok_calls(key["name"]) >= allowance:
                return None, {"detail": f"beta allowance exhausted ({allowance} calls). "
                                        "Pay per call keyless via x402 (drop the key, retry, "
                                        "follow the 402), or contact us for a partner key."}, 402
        return key, None, 0

    # ── x402 payment lane (M3-sandbox) ────────────────────────────────────
    # verify BEFORE the product runs; settle AFTER it succeeds — the caller
    # is never charged for a 5xx, and we never serve on an unsettleable
    # authorization for longer than one request.

    def authorize_or_charge(self, raw_key: str, payment_header: str, product: str,
                            payment_signature: str = ""
                            ) -> tuple[dict[str, Any] | None, dict[str, Any] | None,
                                       dict[str, Any] | None, int]:
        """Key lane first, then the payment lane (v1 X-PAYMENT or v2
        PAYMENT-SIGNATURE — dual-stack). Returns (key, payment_ctx, error, status)."""
        if raw_key:
            key, err, status = self.authorize(raw_key, product)
            return key, None, err, status
        paid = CATALOG.get(product, {}).get("price_usd", 0) > 0
        if ((payment_header or payment_signature)
                and intel_x402.payment_lane_ready() and paid):
            if payment_signature:
                payment, reason = self.verify_payment_v2(payment_signature, product)
            else:
                payment, reason = self.verify_payment(payment_header, product)
            if reason:
                return None, None, x402_challenge_body(product, error=reason), 402
            payer_name = f"x402:{payment['payer']}"
            if not self.limiter.allow(payer_name, DEFAULT_RATE_PER_MIN):
                return None, None, {"detail": "rate limit exceeded"}, 429
            return {"name": payer_name, "tier": "x402",
                    "rate_per_min": DEFAULT_RATE_PER_MIN}, payment, None, 0
        key, err, status = self.authorize(raw_key, product)
        return key, None, err, status

    def verify_payment(self, payment_header: str, product: str
                       ) -> tuple[dict[str, Any] | None, str | None]:
        """Decode + local checks + facilitator verify. Returns (payment_ctx, reason)."""
        payload = intel_x402.decode_payment_header(payment_header)
        if payload is None:
            return None, "malformed X-PAYMENT header (expected base64 JSON payload)"
        requirements = intel_x402.payment_requirements(product)
        reason = intel_x402.local_payment_checks(payload, requirements)
        if reason:
            return None, reason
        nonce = str(((payload.get("payload") or {}).get("authorization") or {}).get("nonce"))
        if self.store.has_payment(nonce):
            return None, "payment authorization already used (replay)"
        verdict = self.facilitator.verify(payload, requirements)
        if verdict.get("_facilitator_error"):
            return None, verdict["_facilitator_error"]
        if not verdict.get("isValid"):
            return None, str(verdict.get("invalidReason") or "payment verification failed")
        payer = str(verdict.get("payer")
                    or ((payload.get("payload") or {}).get("authorization") or {}).get("from")
                    or "unknown")
        return {"payload": payload, "requirements": requirements, "nonce": nonce,
                "payer": payer, "product": product,
                "amount_usd": CATALOG.get(product, {}).get("price_usd", 0.0)}, None

    def verify_payment_v2(self, signature_header: str, product: str
                          ) -> tuple[dict[str, Any] | None, str | None]:
        """v2 lane: decode PAYMENT-SIGNATURE, local checks, facilitator verify."""
        payload = intel_x402.decode_payment_header(signature_header)
        if payload is None:
            return None, "malformed PAYMENT-SIGNATURE header (expected base64 JSON)"
        reason = intel_x402.local_payment_checks_v2(payload, product)
        if reason:
            return None, reason
        authorization = (payload.get("payload") or {}).get("authorization") or {}
        nonce = str(authorization.get("nonce"))
        if self.store.has_payment(nonce):
            return None, "payment authorization already used (replay)"
        accepted = payload.get("accepted") or {}
        verdict = self.facilitator.verify(payload, accepted)
        if verdict.get("_facilitator_error"):
            return None, verdict["_facilitator_error"]
        if not verdict.get("isValid"):
            return None, str(verdict.get("invalidReason") or "payment verification failed")
        payer = str(verdict.get("payer") or authorization.get("from") or "unknown")
        return {"payload": payload, "requirements": accepted, "nonce": nonce,
                "payer": payer, "product": product, "protocol": 2,
                "amount_usd": CATALOG.get(product, {}).get("price_usd", 0.0)}, None

    def settle_payment(self, payment: dict[str, Any]
                       ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Settle a verified payment. Returns (payment_id, response_header_b64, error_body)."""
        settlement = self.facilitator.settle(payment["payload"], payment["requirements"])
        if settlement.get("_facilitator_error") or not settlement.get("success"):
            reason = str(settlement.get("_facilitator_error")
                         or settlement.get("errorReason") or "settlement failed")
            return None, None, x402_challenge_body(payment["product"],
                                                   error=f"settlement failed: {reason}")
        try:
            self.store.record_payment(
                payment["nonce"], payment["product"], payment["amount_usd"],
                payment["payer"],
                str(payment["requirements"].get("network", "")),
                settlement.get("transaction"))
        except sqlite3.IntegrityError:      # raced replay — refuse the duplicate
            return None, None, x402_challenge_body(
                payment["product"], error="payment authorization already used (replay)")
        return payment["nonce"], intel_x402.encode_settlement_header(settlement), None
