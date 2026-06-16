from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .catalysts import get_catalyst_radar
from .market_data import get_bitcoin_market, get_liquidity_flows, get_oil_market, get_trending_stocks


_BRIEF_CACHE: dict[str, Any] = {"key": None, "created_at": None, "payload": None}
_BRIEF_CACHE_SECONDS = 90


def build_daily_market_brief(live_catalysts: bool = True, max_signals: int = 6) -> dict[str, Any]:
    cached = _cached_brief(live_catalysts, max_signals)
    if cached:
        return cached
    fetched_at = datetime.now(timezone.utc).isoformat()
    sections = {
        "bitcoin": _safe(get_bitcoin_market),
        "liquidity": _safe(get_liquidity_flows),
        "trending_stocks": _safe(lambda: get_trending_stocks(limit=10)),
        "oil_energy": _safe(get_oil_market),
        "catalysts": _safe(lambda: get_catalyst_radar(live=live_catalysts)),
    }
    signals = _brief_signals(sections, max_signals=max_signals)
    regime = _market_regime(sections)
    brief = {
        "status": "ok",
        "brief_type": "daily_market_brief",
        "generated_at": fetched_at,
        "regime": regime,
        "headline": _headline(regime, signals),
        "sections": sections,
        "signals": signals,
        "source_note": (
            "Daily Market Brief compiles AlphaLab's available source-backed reads into a strict signals[] block. "
            "It is research and paper-trading input only, not financial advice or autonomous live trading."
        ),
        "automation_contract": {
            "destination": "/api/brief/daily/import-and-test",
            "execution_default": "dry_run",
            "paper_trading_requires": "explicit paper action plus Alpaca paper endpoint availability",
        },
    }
    _BRIEF_CACHE.update({"key": _cache_key(live_catalysts, max_signals), "created_at": datetime.now(timezone.utc), "payload": brief})
    return brief


def _brief_signals(sections: dict[str, Any], max_signals: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for stock in sections.get("trending_stocks", {}).get("stocks", []):
        candidate = stock.get("strategy_candidate") or {}
        if not candidate.get("actionable"):
            continue
        output.append({
            "ticker": stock["ticker"],
            "bias": stock.get("bias", "neutral"),
            "confidence": min(0.92, max(0.75, float(stock.get("confidence") or 0.78))),
            "timeframe": "intraday" if stock.get("bias") == "bearish" else "swing",
            "reason": stock.get("scenario", {}).get("setup") or candidate.get("reason") or "Daily brief trend/liquidity candidate.",
            "source": "daily_market_brief",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_tags": [candidate.get("name") or "daily brief", "market brief"],
            "theme": stock.get("theme") or stock.get("sector") or "Daily Market Brief",
            "catalyst": candidate.get("trigger") or "",
        })
    for signal in sections.get("catalysts", {}).get("signals", []):
        output.append({**signal, "source": "daily_market_brief", "strategy_tags": list(set((signal.get("strategy_tags") or []) + ["market brief"]))})
    return _dedupe_signals(output)[: max(1, min(max_signals, 12))]


def _market_regime(sections: dict[str, Any]) -> dict[str, Any]:
    btc = sections.get("bitcoin", {})
    liquidity_groups = sections.get("liquidity", {}).get("groups", [])
    trending = sections.get("trending_stocks", {}).get("stocks", [])
    bullish = sum(1 for stock in trending if stock.get("bias") == "bullish")
    bearish = sum(1 for stock in trending if stock.get("bias") == "bearish")
    risk_groups = [group for group in liquidity_groups if group.get("name") in {"Risk ETFs", "Crypto Majors", "AI Stocks"}]
    positive_flow = sum(1 for group in risk_groups if (group.get("volume_vs_5d_avg_pct") or group.get("weighted_change_24h_pct") or 0) > 0)
    if bearish > bullish or btc.get("bias") == "bearish":
        posture = "defensive"
    elif bullish >= bearish and positive_flow >= 2:
        posture = "risk-on watch"
    else:
        posture = "mixed"
    return {
        "posture": posture,
        "btc_bias": btc.get("bias", "unknown"),
        "bullish_setups": bullish,
        "bearish_setups": bearish,
        "positive_flow_groups": positive_flow,
        "data_limits": _data_limits(sections),
    }


def _headline(regime: dict[str, Any], signals: list[dict[str, Any]]) -> str:
    if not signals:
        return f"{regime['posture'].title()} market read with no clean paper-test signals from current inputs."
    return f"{regime['posture'].title()} market read with {len(signals)} paper-test candidate signal{'s' if len(signals) != 1 else ''}."


def _data_limits(sections: dict[str, Any]) -> list[str]:
    limits = []
    for name, payload in sections.items():
        status = payload.get("status")
        if status and status not in {"ok", "partial"}:
            limits.append(f"{name}: {status}")
        if payload.get("error"):
            limits.append(f"{name}: {payload['error']}")
    return limits


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for signal in signals:
        key = (signal.get("ticker"), signal.get("bias"), signal.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        output.append(signal)
    return output


def _safe(fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _cached_brief(live_catalysts: bool, max_signals: int) -> dict[str, Any] | None:
    created_at = _BRIEF_CACHE.get("created_at")
    if _BRIEF_CACHE.get("key") != _cache_key(live_catalysts, max_signals) or created_at is None:
        return None
    age = (datetime.now(timezone.utc) - created_at).total_seconds()
    if age > _BRIEF_CACHE_SECONDS:
        return None
    payload = _BRIEF_CACHE.get("payload")
    if not payload:
        return None
    return {**payload, "cached": True, "cache_age_seconds": round(age, 1)}


def _cache_key(live_catalysts: bool, max_signals: int) -> str:
    return f"live={live_catalysts}:max={max_signals}"
