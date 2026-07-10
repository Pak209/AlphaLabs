"""
alpha_lab/intel_api.py — the Intelligence Platform REST gateway (M1 → M2).

A SEPARATE FastAPI app from the personal dashboard (plan §0.1): its own port,
its own SQLite (keys/usage/evaluations), and only the payment-agnostic product
layer behind it — the personal surface (positions, trades, approvals,
preferences, writes) does not exist here.

M2a moved the gateway stack (IntelStore, RateLimiter, x402 challenge,
authorize pipeline) into alpha_lab.intel_gateway so REST and MCP share one
auth → x402 seam → rate-limit → metering path. POST /mcp is the streamable-
HTTP MCP transport (alpha_lab.intel_mcp holds the JSON-RPC handler).

Run (tailnet/local only until M4):
    .venv/bin/python -m alpha_lab.intel_api --port 8790
Keys (seed): INTEL_API_KEYS="partnername:rawkey,other:rawkey2"
License posture: INTEL_COMMERCIAL_MODE defaults ON (SEC-only catalysts,
recomposed snapshot, deferred brief) — set false only for internal use.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .intel_gateway import (   # noqa: F401 — IntelStore/RateLimiter re-exported for compat
    DEFAULT_RATE_PER_MIN, INTEL_DB_DEFAULT, Gateway, IntelStore, RateLimiter,
)
from .intel_mcp import handle_message
from .intel_products import (
    CATALOG, PRODUCT_FUNCS, catalog, decision_explanation, signal_evaluation,
)


def create_intel_app(trading_db_path: str | None = None,
                     store: IntelStore | None = None) -> FastAPI:
    app = FastAPI(title="AlphaLabs Intelligence", version="0.2.0",
                  description="Derived market intelligence for AI agents — REST + MCP + x402.")
    gateway = Gateway(store)

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
        return {"rollup_7d": gateway.store.usage_rollup()}

    def _authorize(request: Request, product: str):
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        key, err, status = gateway.authorize(raw, product)
        if err:
            return None, JSONResponse(status_code=status, content=err)
        return key, None

    def _serve(product: str, request: Request, **kwargs: Any) -> Any:
        started = time.monotonic()
        key, denied = _authorize(request, product)
        if denied:
            return denied
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
            gateway.store.record_usage(key["name"], product, status,
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

    @app.post("/v1/signal-evaluation")
    async def signal_evaluation_route(request: Request) -> Any:
        started = time.monotonic()
        key, denied = _authorize(request, "signal-evaluation")
        if denied:
            return denied
        status = 200
        try:
            try:
                body = await request.json()
            except Exception:
                body = None
            if not isinstance(body, dict):
                status = 422
                return JSONResponse(status_code=422, content={
                    "detail": "JSON object body required: {ticker, bias, ...}"})
            try:
                result = signal_evaluation(body)
            except ValueError as exc:
                status = 422
                return JSONResponse(status_code=422, content={"detail": str(exc)})
            evaluation_id = gateway.store.store_evaluation(key["name"], body, result)
            result["data"]["evaluation_id"] = evaluation_id
            return result
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": "signal-evaluation temporarily unavailable"})
        finally:
            gateway.store.record_usage(key["name"], "signal-evaluation", status,
                                       (time.monotonic() - started) * 1000)

    @app.get("/v1/decision-explanation/{evaluation_id}")
    def decision_explanation_route(evaluation_id: str, request: Request) -> Any:
        started = time.monotonic()
        key, denied = _authorize(request, "decision-explanation")
        if denied:
            return denied
        status = 200
        try:
            record = gateway.store.get_evaluation(evaluation_id)
            if not record or record.get("key_name") != key["name"]:
                status = 404
                return JSONResponse(status_code=404, content={
                    "detail": "evaluation_id not found for this key"})
            return decision_explanation(record)
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": "decision-explanation temporarily unavailable"})
        finally:
            gateway.store.record_usage(key["name"], "decision-explanation", status,
                                       (time.monotonic() - started) * 1000)

    @app.post("/mcp")
    async def mcp_route(request: Request) -> Any:
        """Streamable-HTTP MCP transport; paid tools/call runs the same gateway."""
        try:
            msg = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "parse error"}})
        raw = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        rpc_response = handle_message(msg, gateway=gateway,
                                      trading_db_path=trading_db_path, raw_key=raw)
        if rpc_response is None:                 # notification — acknowledged, no body
            return Response(status_code=202)
        return JSONResponse(content=rpc_response)

    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    uvicorn.run(create_intel_app(), host=args.host, port=args.port)
