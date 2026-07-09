"""
alpha_lab/intel_api.py — the Intelligence Platform REST gateway (M1).

A SEPARATE FastAPI app from the personal dashboard (plan §0.1): its own port,
its own SQLite (keys/usage), and only the payment-agnostic product layer
behind it — the personal surface (positions, trades, approvals, preferences,
writes) does not exist here.

Gateway stack (plan §1): API-key auth → x402 seam → per-key rate limit →
usage metering → product. `INTEL_X402_MODE=demo` returns a spec-shaped 402
challenge for keyless calls so integrators can build against the payment
flow before settlement exists (real facilitator lands in M3).

Run (tailnet/local only until M4):
    .venv/bin/python -m alpha_lab.intel_api --port 8790
Keys (M1 seed): INTEL_API_KEYS="partnername:rawkey,other:rawkey2"
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .intel_products import CATALOG, PRODUCT_FUNCS, catalog

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
"""


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class IntelStore:
    """Keys + usage in the platform's OWN SQLite — never the trading DB."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("INTEL_DB_PATH", INTEL_DB_DEFAULT)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def resolve_key(self, raw: str) -> dict[str, Any] | None:
        """env-seeded keys first (M1 bootstrap), then table-backed keys."""
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
                     latency_ms: float, payment_id: str | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO usage (key_name, product, status, latency_ms, x402_payment_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (key_name, product, status, round(latency_ms, 2), payment_id),
            )
            conn.commit()

    def usage_rollup(self, limit_days: int = 7) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                """
                SELECT date(created_at) AS day, product, key_name,
                       COUNT(*) AS calls, AVG(latency_ms) AS avg_latency_ms,
                       SUM(status = 200) AS ok
                FROM usage
                WHERE datetime(created_at) >= datetime('now', ?)
                GROUP BY day, product, key_name ORDER BY day DESC, calls DESC
                """,
                (f"-{int(limit_days)} days",),
            ).fetchall()]


class RateLimiter:
    """Per-key sliding-minute window (in-process; edge rules layer on in M4)."""

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


def _x402_challenge(product: str) -> JSONResponse:
    """Spec-shaped 402 challenge (demo seam; facilitator settlement = M3)."""
    price = CATALOG.get(product, {}).get("price_usd", 0.01)
    return JSONResponse(status_code=402, content={
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
    })


def create_intel_app(trading_db_path: str | None = None,
                     store: IntelStore | None = None) -> FastAPI:
    app = FastAPI(title="AlphaLabs Intelligence", version="0.1.0",
                  description="Derived market intelligence for AI agents — REST + MCP + x402.")
    intel_store = store or IntelStore()
    limiter = RateLimiter()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "platform": "alphalabs-intel", "products": len(CATALOG)}

    @app.get("/v1/catalog")
    def get_catalog() -> dict[str, Any]:
        return catalog()

    @app.get("/v1/ops/usage")
    def ops_usage(request: Request) -> Any:
        admin = os.getenv("INTEL_ADMIN_KEY", "")
        provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not admin or not hmac.compare_digest(provided, admin):
            return JSONResponse(status_code=401, content={"detail": "admin key required"})
        return {"rollup_7d": intel_store.usage_rollup()}

    def _serve(product: str, request: Request, **kwargs: Any) -> Any:
        started = time.monotonic()
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        key = intel_store.resolve_key(raw) if raw else None
        if not key:
            if os.getenv("INTEL_X402_MODE", "off").strip().lower() == "demo":
                return _x402_challenge(product)
            return JSONResponse(status_code=401, content={
                "detail": "API key required (Authorization: Bearer <key>). "
                          "See /v1/catalog; x402 pay-per-call arrives in M3."})
        if not limiter.allow(key["name"], int(key.get("rate_per_min") or DEFAULT_RATE_PER_MIN)):
            intel_store.record_usage(key["name"], product, 429, (time.monotonic() - started) * 1000)
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        try:
            result = PRODUCT_FUNCS[product](trading_db_path, **kwargs) if kwargs else \
                     PRODUCT_FUNCS[product](trading_db_path)
            status = 200
            return result
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": f"{product} temporarily unavailable"})
        finally:
            intel_store.record_usage(key["name"], product, status,
                                     (time.monotonic() - started) * 1000)

    @app.get("/v1/market-snapshot")
    def market_snapshot_route(request: Request) -> Any:
        return _serve("market-snapshot", request)

    @app.get("/v1/catalysts")
    def catalysts_route(request: Request, limit: int = 25) -> Any:
        return _serve("catalysts", request, limit=limit)

    @app.get("/v1/daily-brief")
    def daily_brief_route(request: Request) -> Any:
        return _serve("daily-brief", request)

    @app.get("/v1/calibration")
    def calibration_route(request: Request) -> Any:
        return _serve("calibration", request)

    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    uvicorn.run(create_intel_app(), host=args.host, port=args.port)
