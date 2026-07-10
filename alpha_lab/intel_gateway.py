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


def x402_challenge_body(product: str) -> dict[str, Any]:
    """Spec-shaped 402 payment-requirements body (demo seam until M3)."""
    price = CATALOG.get(product, {}).get("price_usd", 0.01)
    return {
        "x402Version": 1,
        "error": "payment required",
        "accepts": [{
            "scheme": "exact",
            "network": "base",
            "asset": "USDC",
            "maxAmountRequired": str(price),
            "resource": f"/v1/{product}",
            "description": CATALOG.get(product, {}).get("summary", ""),
            "payTo": os.getenv("INTEL_X402_PAY_TO", "<unset — demo mode>"),
            "maxTimeoutSeconds": 60,
        }],
        "note": "demo challenge — settlement facilitator lands in M3; use an API key today",
    }


class Gateway:
    """One authorize/meter pipeline shared by REST and MCP."""

    def __init__(self, store: IntelStore | None = None):
        self.store = store or IntelStore()
        self.limiter = RateLimiter()

    def authorize(self, raw_key: str, product: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, int]:
        """Returns (key, error_body, error_status). Exactly one of key/error set."""
        key = self.store.resolve_key(raw_key) if raw_key else None
        if not key:
            if os.getenv("INTEL_X402_MODE", "off").strip().lower() == "demo":
                return None, x402_challenge_body(product), 402
            return None, {"detail": "API key required (Authorization: Bearer <key>). "
                                    "See /v1/catalog; x402 pay-per-call arrives in M3."}, 401
        if not self.limiter.allow(key["name"], int(key.get("rate_per_min") or DEFAULT_RATE_PER_MIN)):
            return None, {"detail": "rate limit exceeded"}, 429
        return key, None, 0
