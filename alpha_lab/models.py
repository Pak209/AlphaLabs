from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_STRATEGIES = [
    "News Catalyst",
    "AI Catalyst",
    "IPO Momentum",
    "SEC Filing",
    "Government Contract",
    "Earnings Revision",
    "Analyst Upgrade",
    "Partnership Catalyst",
    "AI bottleneck",
    "liquidity cycle",
    "earnings momentum",
    "macro reaction",
    "breakout",
    "sector rotation",
    "unusual volume",
    "sympathy trade",
    "mean reversion",
    "untagged",
]

CRYPTO_TICKERS = {
    "BTC", "BTC/USD", "BTCUSD",
    "ETH", "ETH/USD", "ETHUSD",
    "SOL", "SOL/USD", "SOLUSD",
    "LINK", "LINK/USD", "LINKUSD",
    "BNB", "BNB/USD", "BNBUSD",
    "DOGE", "DOGE/USD", "DOGEUSD",
}


def normalize_idea_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(payload.get("ticker", "")).strip().upper()
    asset_type = str(payload.get("asset_type") or _infer_asset_type(ticker)).strip().lower()
    if asset_type == "equities":
        asset_type = "equity"
    if asset_type == "options":
        asset_type = "option"
    bias = str(payload.get("bias", "")).strip().lower()
    confidence = float(payload.get("confidence", -1))
    timeframe = str(payload.get("timeframe", "")).strip().lower()
    thesis = str(payload.get("thesis") or payload.get("reason") or "").strip()
    source = str(payload.get("source", "")).strip() or "manual"
    timestamp = str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat())

    errors = []
    if not ticker:
        errors.append("ticker is required")
    if asset_type not in {"equity", "option", "crypto"}:
        errors.append("asset_type must be equity, option, or crypto")
    if bias not in {"bullish", "bearish", "neutral"}:
        errors.append("bias must be bullish, bearish, or neutral")
    if confidence < 0 or confidence > 1:
        errors.append("confidence must be between 0 and 1")
    if timeframe not in {"intraday", "swing"}:
        errors.append("timeframe must be intraday or swing")
    if not thesis:
        errors.append("thesis or reason is required")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        errors.append("timestamp must be an ISO date")
    if errors:
        raise ValueError("; ".join(errors))

    strategies = payload.get("strategies") or payload.get("strategy_tags") or payload.get("strategy_tag") or []
    if isinstance(strategies, str):
        strategies = [strategies]

    normalized_strategies = [str(tag).strip() for tag in strategies if str(tag).strip()]
    if not normalized_strategies:
        normalized_strategies = [str(payload.get("theme") or source or "untagged").strip() or "untagged"]

    # Descriptive provenance tags for the Source Performance Leaderboard. Use any
    # explicit tags from the signal, otherwise fall back to the source label plus
    # strategy tags so every signal carries at least one bucket.
    source_tags = payload.get("source_tags") or []
    if isinstance(source_tags, str):
        source_tags = [source_tags]
    source_tags = [str(tag).strip() for tag in source_tags if str(tag).strip()]
    if not source_tags:
        source_tags = [source] + normalized_strategies
    source_tags = list(dict.fromkeys(source_tags))

    return {
        "ticker": ticker,
        "asset_type": asset_type,
        "sector": str(payload.get("sector", "")).strip(),
        "theme": str(payload.get("theme", "")).strip(),
        "bias": bias,
        "confidence": confidence,
        "timeframe": timeframe,
        "thesis": thesis,
        "catalyst": str(payload.get("catalyst", "")).strip(),
        "source_url": str(payload.get("source_url", "")).strip(),
        "source_refs": payload.get("source_refs") or [],
        "source": source,
        "timestamp": timestamp,
        "market_regime": str(payload.get("market_regime", "")).strip(),
        "catalyst_type": str(payload.get("catalyst_type", "")).strip(),
        "catalyst_score": payload.get("catalyst_score"),
        "catalyst_event_id": payload.get("catalyst_event_id"),
        "strategies": normalized_strategies,
        "source_tags": source_tags,
    }


def _infer_asset_type(ticker: str) -> str:
    if ticker in CRYPTO_TICKERS:
        return "crypto"
    if ticker.endswith("/USD") and ticker.split("/")[0] in {symbol.split("/")[0] for symbol in CRYPTO_TICKERS}:
        return "crypto"
    return "equity"
