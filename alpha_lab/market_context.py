"""
alpha_lab/market_context.py — self-free market-context helpers.

Extracted verbatim from AlphaLabService (Phase 2 PR6, docs/PHASE2_PLAN.md):
the I/O tier of the market-context cluster that reads no service state. The
repo-coupled tier (market regime, briefing context) joins in PR7, completing
this module as the cluster's home.

The service keeps _validation_price as a delegate (a test monkeypatches it on
the instance); _equity_market_open stays in the service (broker coupling) and
only its no-broker fallback calls regular_equity_session_open here.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from paper_trader.alpaca_client import AlpacaClient, load_credentials_from_env

from .live_sources import fetch_polygon_intraday, fetch_yahoo_price
from .repository import AlphaLabRepository


def validation_price(ticker: str) -> float | None:
    """Best-effort live quote for signal validation; never uses simulated prices.

    Tries Polygon (needs a key), then Yahoo Finance (keyless, works on
    networks that block the broker API), then Alpaca. The Yahoo fallback
    means trade levels still populate when Polygon is unconfigured and Alpaca
    is unreachable (e.g. restrictive school/campus Wi-Fi).
    """
    snap = fetch_polygon_intraday(ticker)
    if snap.get("status") == "ok":
        price = snap.get("last_price")
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
    yahoo = fetch_yahoo_price(ticker)
    if yahoo.get("status") == "ok":
        price = yahoo.get("last_price")
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
    try:
        credentials = load_credentials_from_env()
        price = AlpacaClient(credentials).get_latest_trade_price(ticker)
        return float(price) if price else None
    except Exception:
        return None


def regular_equity_session_open(now: datetime | None = None) -> bool:
    """True during the regular NYSE cash session (Mon–Fri 9:30–16:00 ET).

    ``now`` is injectable for tests only; the no-arg call (every production
    call site) reads the real clock exactly as before.
    """
    now = now or datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() < time(16, 0)


def safe_market_payload(fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def current_market_regime(repo: "AlphaLabRepository") -> str:
    """Regime posture in force right now, stamped on each new signal.

    Reads the most recent saved market briefing (the scheduler regenerates
    these) and uses its ``broad_market_tone`` — the same defensive / risk-on
    watch / mixed posture computed by the daily brief. Falls back to
    ``unknown`` when no briefing has been generated yet.
    """
    try:
        briefings = repo.list_market_briefings(1)
    except Exception:
        return "unknown"
    if not briefings:
        return "unknown"
    tone = str(briefings[0].get("payload", {}).get("broad_market_tone") or "").strip().lower()
    return tone or "unknown"


def latest_briefing_context(conn) -> dict[str, Any]:
    briefings = AlphaLabRepository(conn).list_market_briefings(1)
    if not briefings:
        return {}
    payload = briefings[0].get("payload", {})
    return {
        "headline": payload.get("broad_market_tone", ""),
        "market_context": payload.get("broad_market_tone", ""),
        "source": "stored_market_briefing",
        "generated_at": payload.get("generated_at", ""),
    }
