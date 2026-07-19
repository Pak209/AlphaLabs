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

M3-sandbox: keyless callers can PAY per call — INTEL_X402_MODE=sandbox
verifies+settles real testnet USDC on Base Sepolia via the x402.org
facilitator (X-PAYMENT in, X-PAYMENT-RESPONSE out; alpha_lab.intel_x402).
Verify runs before the product, settle after it succeeds, so a 5xx never
charges anyone. live mode stays gated on the business wallet + CDP KYB.

Run (tailnet/local only until M4):
    .venv/bin/python -m alpha_lab.intel_api --port 8790
Keys (seed): INTEL_API_KEYS="partnername:rawkey,other:rawkey2"
License posture: INTEL_COMMERCIAL_MODE defaults ON (SEC-only catalysts,
recomposed snapshot, deferred brief) — set false only for internal use.
"""
from __future__ import annotations

import hmac
import os
import re
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import intel_x402
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

    @app.get("/", response_class=HTMLResponse)
    def landing() -> str:
        """Free landing/pricing page rendered from the catalog — the public
        face of the API (and the 'business website' KYB asks for)."""
        rows = []
        for name, meta in CATALOG.items():
            price = "Free (beta)" if not meta.get("price_usd") else f"${meta['price_usd']:.2f}/call"
            method = meta.get("method", "GET")
            rows.append(f"<tr><td><code>{method} /v1/{name}</code></td>"
                        f"<td>{price}</td><td>{meta['summary']}</td></tr>")
        table = "".join(rows)
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaLabs Intelligence — derived market analytics for AI agents</title>
<style>
 body {{ font: 16px/1.55 -apple-system, system-ui, sans-serif; margin: 0 auto; max-width: 860px;
        padding: 40px 20px; background: #0b0e14; color: #e6e9ef; }}
 h1 {{ font-size: 30px; margin-bottom: 4px; }} .muted {{ color: #97a0b0; }}
 table {{ border-collapse: collapse; width: 100%; margin: 22px 0; }}
 td, th {{ border-bottom: 1px solid #232936; padding: 9px 8px; text-align: left; font-size: 14px; }}
 code, pre {{ background: #141926; border-radius: 5px; padding: 2px 6px; font-size: 13px; }}
 pre {{ padding: 12px; overflow-x: auto; }} a {{ color: #7fb4ff; }}
 .foot {{ font-size: 12px; color: #97a0b0; margin-top: 34px; border-top: 1px solid #232936; padding-top: 14px; }}
</style></head><body>
<h1>AlphaLabs Intelligence</h1>
<p class="muted">Derived market intelligence from a live, calibrated paper-trading pipeline —
scores, regimes, calibration telemetry, and recorded outcomes. Built for AI agents:
REST + MCP, API keys today, x402 pay-per-call (USDC on Base) in rollout.</p>
<table><tr><th>Product</th><th>Price</th><th>What you get</th></tr>{table}</table>
<h3>Auth</h3>
<p><code>Authorization: Bearer &lt;api-key&gt;</code> — grab a free beta key below
(first 100 calls free), or pay keyless per call via
<a href="https://www.x402.org">x402</a> (USDC on Base).</p>
<form id="faucet" onsubmit="return getKey(event)" style="display:flex;gap:8px;flex-wrap:wrap;margin:14px 0">
  <input id="faucet-email" type="email" required placeholder="you@example.com"
         style="flex:1;min-width:220px;padding:10px;border-radius:6px;border:1px solid #232936;background:#141926;color:#e6e9ef">
  <button type="submit" style="padding:10px 18px;border-radius:6px;border:none;background:#7fb4ff;color:#0b0e14;font-weight:700;cursor:pointer">Get a free beta key</button>
</form>
<pre id="faucet-out" style="display:none"></pre>
<script>
async function getKey(e) {{
  e.preventDefault();
  const out = document.getElementById("faucet-out");
  out.style.display = "block"; out.textContent = "requesting…";
  try {{
    const res = await fetch("/v1/keys/beta", {{ method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ email: document.getElementById("faucet-email").value }}) }});
    const data = await res.json();
    out.textContent = res.ok
      ? "YOUR KEY (shown once — save it now):\n" + data.key + "\n\n" + data.note
      : (data.detail || "request failed");
  }} catch (_) {{ out.textContent = "network error — try again"; }}
  return false;
}}
</script>
<h3>Quickstart</h3>
<pre>curl -H "Authorization: Bearer $KEY" https://api.pak-labs.com/v1/catalog</pre>
<p>MCP: point your client at <code>POST https://api.pak-labs.com/mcp</code> with the same bearer key
(tools: catalog, calibration, evaluate_signal, explain_decision, outcome_report,
feature_attribution).</p>
<p class="foot">Research signals and calibration telemetry. Informational derived analytics —
not investment advice, not an offer or solicitation, and not a redistribution of any
vendor's market data. Machine-readable catalog: <a href="/v1/catalog">/v1/catalog</a>.</p>
</body></html>"""

    @app.get("/llms.txt", response_class=Response)
    def llms_txt() -> Response:
        """Machine-readable service description (llms.txt convention) — the
        agent-facing storefront. Crawled by LLM toolchains and readable by any
        agent that lands on the root domain."""
        products = "\n".join(
            f"- {meta.get('method', 'GET')} /v1/{name} — "
            f"{'FREE during beta (API key required)' if not meta.get('price_usd') else '$' + format(meta['price_usd'], '.2f') + ' per call'}: "
            f"{meta['summary']}"
            for name, meta in CATALOG.items())
        text = f"""# AlphaLabs Intelligence

> Live trading-pipeline intelligence for AI agents: signal evaluation by a real
> calibrated engine (glass-box sub-signal explanations), pipeline calibration
> telemetry, recorded outcome reports, and SEC-filing catalysts. Derived
> analytics only — never redistributed vendor market data. Not investment advice.

Base URL: https://api.pak-labs.com

## Products
{products}

## Auth (two lanes)
- API key: `Authorization: Bearer <key>` — self-provision a free beta key
  (first 100 calls free, 30 req/min): POST /v1/keys/beta with
  {{"email": "you@example.com"}} — the key is returned once in the response.
- x402 pay-per-call: keyless requests to paid products return an HTTP 402 with
  machine-readable payment requirements (USDC on Base mainnet, EIP-3009,
  settled via the Coinbase facilitator). No account needed — an agent with a
  funded wallet can buy a single call.

## Interfaces
- REST: endpoints above; machine-readable catalog at /v1/catalog; full schema at /openapi.json
- MCP (streamable HTTP): POST /mcp — tools: alphalabs_get_catalog,
  alphalabs_evaluate_signal, alphalabs_explain_decision,
  alphalabs_calibration_report, alphalabs_outcome_report,
  alphalabs_feature_attribution

## Why this data is different
The scores and telemetry come from a live, gated paper-trading pipeline with
recorded outcomes — accepted-vs-rejected edge, score-band hit rates, and
feature attribution measured on real decisions, not backtests or wrapped
public feeds.
"""
        return Response(content=text, media_type="text/plain; charset=utf-8")

    @app.get("/.well-known/mcp/server-card.json")
    def mcp_server_card() -> dict[str, Any]:
        """MCP discovery card — clients probe this path (6 hits before it existed)."""
        return {
            "name": "alphalabs-intel",
            "description": "Live trading-pipeline intelligence: signal evaluation, "
                           "calibration telemetry, recorded outcomes, SEC catalysts. "
                           "Not investment advice.",
            "endpoint": "https://api.pak-labs.com/mcp",
            "transport": "streamable-http",
            "authentication": {"type": "bearer",
                               "hint": "Authorization: Bearer <api-key>; keys via the landing page. "
                                       "Paid REST products also accept x402 payments (USDC on Base)."},
            "docs": "https://api.pak-labs.com/llms.txt",
        }

    @app.get("/robots.txt", response_class=Response)
    def robots() -> Response:
        return Response("User-agent: *\nAllow: /\nSitemap: https://api.pak-labs.com/sitemap.xml\n",
                        media_type="text/plain")

    @app.get("/sitemap.xml", response_class=Response)
    def sitemap() -> Response:
        urls = "".join(f"<url><loc>https://api.pak-labs.com{p}</loc></url>"
                       for p in ("/", "/llms.txt", "/v1/catalog"))
        return Response(f'<?xml version="1.0" encoding="UTF-8"?>'
                        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")

    @app.get("/pricing")
    def pricing_redirect() -> Any:
        # Humans keep guessing this URL (5 hits) — the landing page IS the pricing page.
        return Response(status_code=307, headers={"Location": "/"})

    _EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,24}$")

    @app.post("/v1/keys/beta")
    async def beta_key_faucet(request: Request) -> Any:
        """Self-serve beta keys — the first-100-calls-free funnel.

        Abuse posture for a public, unauthenticated endpoint: per-IP throttle
        (3/min), one key per normalized email, global cap on faucet keys
        (INTEL_BETA_KEY_CAP, default 500, fail-closed), and the keys
        themselves are bounded (30/min rate + lifetime call allowance
        enforced in the gateway) — worst-case cost of abuse is small.
        """
        client_ip = (request.headers.get("cf-connecting-ip")
                     or (request.client.host if request.client else "unknown"))
        if not gateway.limiter.allow(f"faucet:{client_ip}", 5):
            return JSONResponse(status_code=429, content={"detail": "slow down — try again in a minute"})
        try:
            body = await request.json()
        except Exception:
            body = None
        email = str((body or {}).get("email") or "").strip().lower()
        if not _EMAIL_RE.match(email):
            return JSONResponse(status_code=422, content={"detail": "valid email required: {\"email\": \"you@example.com\"}"})
        name = f"beta:{email}"
        if gateway.store.key_name_exists(name):
            return JSONResponse(status_code=409, content={
                "detail": "a beta key was already issued to this email — contact us if it was lost"})
        cap = int(os.getenv("INTEL_BETA_KEY_CAP", "500"))
        if gateway.store.count_keys("beta-faucet") >= cap:
            return JSONResponse(status_code=503, content={
                "detail": "beta is full — contact us for a partner key"})
        raw = gateway.store.issue_key(name)
        allowance = int(os.getenv("INTEL_BETA_CALL_ALLOWANCE", "100"))
        return {
            "key": raw,
            "note": "shown once — store it now. Send as 'Authorization: Bearer <key>'.",
            "tier": "beta-faucet",
            "rate_per_min": 30,
            "call_allowance": allowance,
            "after_allowance": "pay per call keyless via x402 (USDC on Base) or ask for a partner key",
            "catalog": "/v1/catalog",
        }

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
        payment_header = request.headers.get("X-PAYMENT", "").strip()
        payment_signature = request.headers.get("PAYMENT-SIGNATURE", "").strip()
        key, payment, err, status = gateway.authorize_or_charge(
            raw, payment_header, product, payment_signature=payment_signature)
        if err:
            headers = {}
            if status == 402 and CATALOG.get(product, {}).get("price_usd", 0) > 0:
                # dual-stack 402: v1 JSON body (unchanged, proven) + the v2
                # PAYMENT-REQUIRED header carrying the Bazaar discovery
                # extension — this envelope is what the facilitator indexes.
                headers["PAYMENT-REQUIRED"] = intel_x402.challenge_v2_header(
                    product, error=str(err.get("error") or "payment required"))
            return None, None, JSONResponse(status_code=status, content=err, headers=headers)
        return key, payment, None

    def _finalize(result: Any, payment: dict[str, Any] | None):
        """Settle the x402 payment (if any) AFTER the product succeeded.

        Returns (response, payment_id, status). A failed settlement withholds
        the product output — the caller retries with a fresh authorization.
        """
        if not payment:
            return result, None, 200
        payment_id, settlement_header, err = gateway.settle_payment(payment)
        if err:
            return JSONResponse(status_code=402, content=err), None, 402
        header_name = ("PAYMENT-RESPONSE" if payment.get("protocol") == 2
                       else "X-PAYMENT-RESPONSE")
        return JSONResponse(content=result,
                            headers={header_name: settlement_header}), payment_id, 200

    def _serve(product: str, request: Request, **kwargs: Any) -> Any:
        started = time.monotonic()
        key, payment, denied = _authorize(request, product)
        if denied:
            return denied
        payment_id = None
        try:
            result = PRODUCT_FUNCS[product](trading_db_path, **kwargs) if kwargs else \
                     PRODUCT_FUNCS[product](trading_db_path)
            response, payment_id, status = _finalize(result, payment)
            return response
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": f"{product} temporarily unavailable"})
        finally:
            gateway.store.record_usage(key["name"], product, status,
                                       (time.monotonic() - started) * 1000,
                                       payment_id=payment_id)

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

    @app.get("/v1/outcome-report")
    def outcome_report_route(request: Request) -> Any:
        return _serve("outcome-report", request)

    @app.get("/v1/feature-attribution")
    def feature_attribution_route(request: Request) -> Any:
        return _serve("feature-attribution", request)

    @app.post("/v1/signal-evaluation")
    async def signal_evaluation_route(request: Request) -> Any:
        started = time.monotonic()
        key, payment, denied = _authorize(request, "signal-evaluation")
        if denied:
            return denied
        status = 200
        payment_id = None
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
            response, payment_id, status = _finalize(result, payment)
            return response
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": "signal-evaluation temporarily unavailable"})
        finally:
            gateway.store.record_usage(key["name"], "signal-evaluation", status,
                                       (time.monotonic() - started) * 1000,
                                       payment_id=payment_id)

    @app.get("/v1/decision-explanation/{evaluation_id}")
    def decision_explanation_route(evaluation_id: str, request: Request) -> Any:
        started = time.monotonic()
        key, payment, denied = _authorize(request, "decision-explanation")
        if denied:
            return denied
        status = 200
        payment_id = None
        try:
            record = gateway.store.get_evaluation(evaluation_id)
            if not record or record.get("key_name") != key["name"]:
                status = 404
                return JSONResponse(status_code=404, content={
                    "detail": "evaluation_id not found for this key"})
            response, payment_id, status = _finalize(decision_explanation(record), payment)
            return response
        except Exception:
            status = 503
            return JSONResponse(status_code=503, content={
                "detail": "decision-explanation temporarily unavailable"})
        finally:
            gateway.store.record_usage(key["name"], "decision-explanation", status,
                                       (time.monotonic() - started) * 1000,
                                       payment_id=payment_id)

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
        if not raw:
            # Smithery's gateway (and several MCP clients) forward configured
            # keys as query parameters, not headers — found live: 194 failed
            # auth attempts as POST /mcp?api_key=... before this existed.
            raw = (request.query_params.get("api_key")
                   or request.query_params.get("apiKey") or "").strip()
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
