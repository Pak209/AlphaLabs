"""
alpha_lab/intel_products.py — the Intelligence Platform product layer.

Payment-agnostic business logic (docs/INTELLIGENCE_PLATFORM_PLAN.md §1):
every product is a pure read-only function over the trading core that
returns the standard envelope — product/version/generated_at/data/
provenance/confidence/reasoning/historical_performance/disclaimer. The REST
app, the MCP server, and the x402 gateway all call these same functions.

Hard rules enforced here (not at the gateway):
  * READ-ONLY against the trading DB.
  * NO personal-surface data: positions, P/L, order/trade rows, approvals,
    notification preferences, and account state never appear in any product.
  * Derived intelligence only — scores, regimes, classifications,
    calibration aggregates — with source attribution, never redistributed
    quotes/bars. Yahoo-RSS-derived rows are filtered out of paid products
    (license posture, see plan §0.2).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from .database import connect, resolve_db_path
from .market_context import current_market_regime
from .repository import AlphaLabRepository
from .review_api import _lex_summary
from .waterfall import build_rejection_waterfall

VERSION = "v1"
DISCLAIMER = (
    "AlphaLabs research signals and calibration telemetry. Informational "
    "derived analytics — not investment advice, not an offer or solicitation, "
    "and not a redistribution of any vendor's market data."
)

# Products in the paid catalog (price is displayed metadata; enforcement is
# the gateway's job so this layer stays payment-agnostic).
CATALOG: dict[str, dict[str, Any]] = {
    "market-snapshot": {
        "price_usd": 0.01,
        "summary": "Regime posture, narrative market summary, and crypto bias from the live regime engine.",
    },
    "catalysts": {
        "price_usd": 0.02,
        "summary": "Scored, classified catalyst events with direction, 8-factor score, and provenance.",
    },
    "daily-brief": {
        "price_usd": 0.05,
        "summary": "The compiled AI market brief: tone, themes, macro risks, watch list, top catalysts.",
    },
    "calibration": {
        "price_usd": 0.05,
        "summary": "Live pipeline calibration telemetry: stage funnel, gate failures, near-misses.",
    },
}

_EXCLUDED_PAID_SOURCES = ("yahoo finance news",)   # license posture: plan §0.2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope(product: str, data: Any, *, provenance: list[dict[str, Any]],
             confidence: Optional[dict[str, Any]] = None,
             reasoning: str = "",
             historical_performance: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "product": product,
        "version": VERSION,
        "generated_at": _now(),
        "data": data,
        "provenance": provenance,
        "confidence": confidence,
        "reasoning": reasoning,
        "historical_performance": historical_performance,
        "disclaimer": DISCLAIMER,
        "usage": {"product_price_usd": CATALOG[product]["price_usd"]} if product in CATALOG else None,
    }


def catalog() -> dict[str, Any]:
    """Free machine-readable product catalog (doubles as the pricing page)."""
    return {
        "platform": "AlphaLabs Intelligence",
        "version": VERSION,
        "generated_at": _now(),
        "products": [
            {"product": name, "endpoint": f"/v1/{name}", **meta}
            for name, meta in CATALOG.items()
        ],
        "auth": "Authorization: Bearer <api-key> (x402 pay-per-call: see gateway docs)",
        "disclaimer": DISCLAIMER,
    }


def market_snapshot(db_path: str | None = None) -> dict[str, Any]:
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        repo = AlphaLabRepository(conn)
        regime = current_market_regime(repo)
        briefings = repo.list_market_briefings(1)
    briefing = briefings[0] if briefings else None
    lex = _lex_summary(briefing)
    payload = (briefing or {}).get("payload") or {}
    crypto = payload.get("crypto_context") or {}
    data = {
        "market_regime": regime,
        "narrative": lex.get("text"),
        "themes": payload.get("themes") or [],
        "btc_bias": crypto.get("btc_bias", "unknown"),
        "as_of_briefing": (briefing or {}).get("generated_at"),
    }
    fresh = bool(briefing)
    return envelope(
        "market-snapshot", data,
        provenance=[{"source": "AlphaLabs regime engine + stored market briefing",
                     "as_of": data["as_of_briefing"] or "unavailable"}],
        confidence={"level": "normal" if fresh else "degraded",
                    "basis": "latest stored briefing" if fresh else "no briefing stored yet"},
        reasoning="Regime posture is computed from the most recent compiled briefing's "
                  "broad-market tone; the narrative is the same deterministic summary the "
                  "operator dashboard renders.",
    )


def catalyst_feed(db_path: str | None = None, limit: int = 25) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT ticker, catalyst_type, strategy_label, direction, headline,
                   source, source_url, published_at, discovered_at,
                   novelty_score, urgency_score, catalyst_score
            FROM catalyst_events
            ORDER BY datetime(discovered_at) DESC, id DESC LIMIT ?
            """,
            (limit * 2,),   # over-fetch to survive the paid-source filter
        ).fetchall()]
    events = [
        r for r in rows
        if str(r.get("source") or "").strip().lower() not in _EXCLUDED_PAID_SOURCES
    ][:limit]
    for event in events:
        event["provenance"] = {"source": event.pop("source"),
                               "url": event.pop("source_url"),
                               "published_at": event.pop("published_at"),
                               "discovered_at": event["discovered_at"]}
    return envelope(
        "catalysts", {"events": events, "count": len(events)},
        provenance=[{"source": "AlphaLabs catalyst radar (classified + scored, cross-source deduped)",
                     "as_of": events[0]["discovered_at"] if events else "empty"}],
        confidence={"level": "per-event", "basis": "each event carries its own scores"},
        reasoning="Events are keyword-classified, source-quality weighted, and scored on "
                  "novelty/urgency/impact by the same engine that feeds the live pipeline. "
                  "Detection latency is observable: discovered_at vs published_at.",
    )


def daily_brief(db_path: str | None = None) -> dict[str, Any]:
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        briefings = AlphaLabRepository(conn).list_market_briefings(1)
    if not briefings:
        return envelope("daily-brief", {"available": False},
                        provenance=[{"source": "AlphaLabs briefing engine", "as_of": "none"}],
                        confidence={"level": "unavailable", "basis": "no briefing stored yet"},
                        reasoning="The scheduler compiles briefings on trading days.")
    briefing = briefings[0]
    payload = briefing.get("payload") or {}
    data = {
        "available": True,
        "broad_market_tone": payload.get("broad_market_tone"),
        "themes": payload.get("themes") or [],
        "macro_risks": payload.get("macro_risks") or [],
        "candidate_tickers_to_monitor": payload.get("candidate_tickers_to_monitor") or [],
        "sector_movement": payload.get("major_indexes_sector_movement") or [],
        "top_catalysts": [
            {"ticker": c.get("ticker"), "headline": c.get("headline"),
             "catalyst_type": c.get("catalyst_type"), "direction": c.get("direction"),
             "score": c.get("catalyst_score")}
            for c in (payload.get("strongest_catalysts_found") or [])[:5]
        ],
        "generated_at": briefing.get("generated_at"),
    }
    return envelope(
        "daily-brief", data,
        provenance=[{"source": "AlphaLabs compiled market briefing",
                     "as_of": briefing.get("generated_at")}],
        confidence={"level": "normal", "basis": "compiled from configured live sources"},
        reasoning="The same brief the operator's research loop consumes: regime tone, theme "
                  "detection over trending+catalyst text, and the strongest scored catalysts.",
    )


def calibration_report(db_path: str | None = None) -> dict[str, Any]:
    path = resolve_db_path(db_path)
    report = build_rejection_waterfall(path, limit=5000)
    gate_failures = [
        {k: g.get(k) for k in ("gate", "evaluated", "failures", "enforced_failures",
                               "advisory_failures", "near_misses", "observed_stats")}
        for g in report.get("gate_failures", [])[:8]
    ]
    data = {
        "window": report.get("window"),
        "stage_funnel": report.get("stage_funnel"),
        "gate_failures": gate_failures,
        "first_failed_gates": report.get("first_failed_gates", [])[:8],
    }
    return envelope(
        "calibration", data,
        provenance=[{"source": "AlphaLabs live gate telemetry (structured traces + legacy parse)",
                     "as_of": report.get("generated_at")}],
        confidence={"level": "measured",
                    "basis": f"{report.get('window', {}).get('structured_rows', 0)} structured decision traces"},
        reasoning="This is the platform's own live calibration: what a real, gated paper-trading "
                  "pipeline evaluated, rejected, and nearly accepted — telemetry no wrapper API "
                  "around public feeds can produce.",
        historical_performance={"note": "outcome-linked performance products arrive in M2 "
                                        "(accepted-vs-rejected edge, score-band hit rates)"},
    )


PRODUCT_FUNCS = {
    "market-snapshot": market_snapshot,
    "catalysts": catalyst_feed,
    "daily-brief": daily_brief,
    "calibration": calibration_report,
}
