from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .live_sources import fetch_live_catalysts
from .scoring_engine import (
    score_idea,
    catalyst_inputs_from_radar_row,
    narrative_inputs_for_ticker,
)
from .scoring_models import MacroInputs


CATALYST_KEYWORDS: dict[str, dict[str, Any]] = {
    "8-k": {"weight": 1.8, "bias": "bullish", "label": "SEC 8-K filing"},
    "s-1": {"weight": 1.8, "bias": "bullish", "label": "IPO/S-1 filing"},
    "ipo": {"weight": 1.6, "bias": "bullish", "label": "IPO activity"},
    "ai": {"weight": 1.0, "bias": "bullish", "label": "AI keyword"},
    "artificial intelligence": {"weight": 1.5, "bias": "bullish", "label": "AI keyword"},
    "machine learning": {"weight": 1.1, "bias": "bullish", "label": "AI keyword"},
    "agreement": {"weight": 1.2, "bias": "bullish", "label": "commercial agreement"},
    "contract": {"weight": 1.5, "bias": "bullish", "label": "commercial contract"},
    "government contract": {"weight": 2.2, "bias": "bullish", "label": "government contract"},
    "defense contract": {"weight": 2.0, "bias": "bullish", "label": "government contract"},
    "awarded": {"weight": 1.4, "bias": "bullish", "label": "award announcement"},
    "partnership": {"weight": 1.2, "bias": "bullish", "label": "partnership"},
    "acquisition": {"weight": 1.8, "bias": "bullish", "label": "acquisition"},
    "acquires": {"weight": 1.8, "bias": "bullish", "label": "acquisition"},
    "upgrade": {"weight": 1.4, "bias": "bullish", "label": "analyst upgrade"},
    "initiates coverage": {"weight": 1.2, "bias": "bullish", "label": "analyst action"},
    "fda approval": {"weight": 2.4, "bias": "bullish", "label": "FDA approval"},
    "phase 3": {"weight": 1.6, "bias": "bullish", "label": "late-stage clinical data"},
    "raises guidance": {"weight": 2.0, "bias": "bullish", "label": "guidance raise"},
    "beat": {"weight": 1.2, "bias": "bullish", "label": "earnings beat"},
    "insider purchase": {"weight": 1.5, "bias": "bullish", "label": "insider activity"},
    "form 4": {"weight": 1.1, "bias": "bullish", "label": "insider filing"},
    "sec investigation": {"weight": -2.4, "bias": "bearish", "label": "SEC investigation"},
    "offering": {"weight": -1.7, "bias": "bearish", "label": "possible dilution"},
    "financing": {"weight": -1.2, "bias": "bearish", "label": "financing event"},
    "downgrade": {"weight": -1.4, "bias": "bearish", "label": "analyst downgrade"},
    "registered direct": {"weight": -2.0, "bias": "bearish", "label": "registered direct offering"},
    "shelf registration": {"weight": -1.3, "bias": "bearish", "label": "shelf registration"},
    "424b5": {"weight": -1.6, "bias": "bearish", "label": "SEC 424B5 offering prospectus"},
    "424b3": {"weight": -1.5, "bias": "bearish", "label": "SEC 424B3 offering prospectus"},
    "s-3": {"weight": -1.4, "bias": "bearish", "label": "SEC S-3 shelf registration"},
    "delisting": {"weight": -2.3, "bias": "bearish", "label": "delisting risk"},
    "bankruptcy": {"weight": -3.0, "bias": "bearish", "label": "bankruptcy risk"},
    "cuts guidance": {"weight": -2.0, "bias": "bearish", "label": "guidance cut"},
}

BROAD_MARKET_TERMS = [
    "stock market", "market indexes", "nasdaq", "s&p 500", "dow jones", "russell 2000",
    "sell-off", "selloff", "crash", "cpi", "fed", "rate hike", "yields", "jobs report",
    "volatility", "vix", "etf", "stocks on watch",
]

BROAD_INDEX_MACRO_TERMS = [
    "stock market", "market indexes", "nasdaq", "s&p 500", "dow jones", "russell 2000",
    "sell-off", "selloff", "crash", "cpi", "fed", "rate hike", "yields", "jobs report",
    "volatility", "vix",
]

LOW_ACTIONABILITY_TERMS = [
    "why stock", "should you buy", "buy on the dip", "could be", "according to analysts",
    "billionaire", "favorite stocks", "case for", "investors could", "what that means",
    "just filed for an ipo", "poll", "readers say", "watchlist", "watch list",
    "here's why", "heres why", "things to know", "what to know",
]

DIRECT_CATALYST_TERMS = [
    "announces", "launches", "signs", "wins", "awarded", "expands", "partners with",
    "partnership", "contract", "agreement", "raises guidance", "cuts guidance", "files",
    "filed", "offering", "registered direct", "fda approval", "phase 3", "earnings",
    "8-k", "s-1", "ipo", "upgrade", "downgrade", "acquires", "acquisition",
    "government contract", "insider", "form 4", "financing",
]

DIRECT_SOURCE_FEEDS = ["sec edgar", "globenewswire", "business wire", "pr newswire"]

SECTOR_SYMPATHY_TERMS = [
    "semiconductor", "semiconductors", "chip stocks", "ai stocks", "defense stocks",
    "energy stocks", "software stocks", "sector", "industry", "etfs", "rival", "supplier",
    "sympathy", "read-through", "read through",
]

CATALYST_SOURCE_QUALITY = {
    "sec edgar": 96,
    "business wire": 88,
    "globenewswire": 84,
    "pr newswire": 84,
    "benzinga": 78,
    "polygon": 74,
    "newsfilter": 74,
    "manual": 60,
}

CATALYST_STRATEGY_LABELS = {
    "ai": "AI Catalyst",
    "sec": "SEC Filing",
    "ipo": "IPO Momentum",
    "government": "Government Contract",
    "earnings": "Earnings Revision",
    "analyst": "Analyst Upgrade",
    "partnership": "Partnership Catalyst",
    "acquisition": "Partnership Catalyst",
    "financing": "SEC Filing",
}


SAMPLE_CATALYSTS: list[dict[str, Any]] = [
    {
        "ticker": "NVDA",
        "headline": "NVIDIA supplier announces expanded AI infrastructure contract",
        "summary": "Supplier language points to AI data-center demand, but AlphaLab still requires price/volume confirmation before any paper test.",
        "source": "sample_press_release_feed",
        "source_url": "",
        "published_at": "2026-06-08T13:02:00Z",
        "security_type": "stock",
        "exchange": "NASDAQ",
    },
    {
        "ticker": "AAPL",
        "headline": "Apple files product-related 8-K with no clear revenue guidance change",
        "summary": "Headline is relevant but not obviously directional. Keep as watchlist context unless price confirms.",
        "source": "sample_sec_feed",
        "source_url": "",
        "published_at": "2026-06-08T13:08:00Z",
        "security_type": "stock",
        "exchange": "NASDAQ",
    },
    {
        "ticker": "SMCI",
        "headline": "Super Micro announces registered direct offering",
        "summary": "Offering language is normally dilution-sensitive and can pressure momentum names.",
        "source": "sample_press_release_feed",
        "source_url": "",
        "published_at": "2026-06-08T13:13:00Z",
        "security_type": "stock",
        "exchange": "NASDAQ",
    },
]


def get_catalyst_radar(payload: dict[str, Any] | None = None, live: bool = False) -> dict[str, Any]:
    live_result = None
    if live and not payload:
        live_result = fetch_live_catalysts()
        catalysts = live_result.get("catalysts") or SAMPLE_CATALYSTS
    else:
        catalysts = _normalize_catalysts(payload) if payload else SAMPLE_CATALYSTS
    scored = [score_catalyst(item) for item in catalysts]
    scored.sort(key=lambda row: (row["catalyst_score"], row["category_rank"], row["published_at"]), reverse=True)
    return {
        "status": "ok",
        "mode": "live" if live_result and live_result.get("catalysts") else "sample_fallback" if live_result else "sample" if not payload else "custom_payload",
        "live_status": live_result,
        "source_note": (
            "Catalyst Radar is a FoxRunner-style workflow: fast news/filing/press-release items, "
            "keyword matches, impact scoring, then AlphaLab risk checks. Current built-in rows are samples "
            "unless live vendor feeds are configured and reachable."
        ),
        "keyword_count": len(CATALYST_KEYWORDS),
        "categories": _categorized(scored),
        "catalysts": scored,
        "signals": [catalyst_to_signal(row) for row in scored if row["trade_candidate"]],
    }


def import_catalysts_payload(payload: dict[str, Any]) -> dict[str, Any]:
    has_catalyst_payload = bool(payload.get("catalysts") or payload.get("items") or payload.get("ticker"))
    live = bool(payload.get("live", False)) and not has_catalyst_payload
    radar = get_catalyst_radar(payload if has_catalyst_payload else None, live=live)
    return {
        "signals": radar["signals"],
        "catalysts": radar["catalysts"],
        "live_status": radar.get("live_status"),
        "mode": radar.get("mode"),
        "source": "catalyst_radar",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def score_catalyst(item: dict[str, Any]) -> dict[str, Any]:
    headline = str(item.get("headline", "")).strip()
    summary = str(item.get("summary", "")).strip()
    text = f"{headline} {summary}".lower()
    ticker = str(item.get("ticker", "")).strip().upper()
    source = str(item.get("source", "unknown")).strip() or "unknown"
    published_at = str(item.get("published_at") or datetime.now(timezone.utc).isoformat())
    category, category_reason = classify_catalyst(item, text)
    matches = []
    raw_score = 0.0
    bullish = 0.0
    bearish = 0.0
    for keyword, meta in CATALYST_KEYWORDS.items():
        if keyword in text:
            weight = float(meta["weight"])
            raw_score += weight
            if weight > 0:
                bullish += weight
            else:
                bearish += abs(weight)
            matches.append({"keyword": keyword, "label": meta["label"], "weight": weight, "bias": meta["bias"]})

    if bullish > bearish and bullish >= 1.5:
        bias = "bullish"
    elif bearish > bullish and bearish >= 1.5:
        bias = "bearish"
    else:
        bias = "neutral"

    category_multiplier = {
        "direct_company_catalyst": 1.0,
        "sympathy_sector_read": 0.55,
        "broad_market_mention": 0.35,
        "low_actionability": 0.2,
    }[category]
    actionability_score = min(10.0, round((abs(raw_score) * 2.0 + len(matches) * 0.35) * category_multiplier, 2))
    confidence = min(0.93, max(0.55, 0.56 + actionability_score / 20))
    trade_candidate = (
        category == "direct_company_catalyst"
        and bias in {"bullish", "bearish"}
        and confidence >= 0.75
        and actionability_score >= 3.5
    )
    reason_bits = [match["label"] for match in matches[:4]]
    if not reason_bits:
        reason_bits = ["no high-impact keyword match"]
    catalyst_type = _catalyst_type(item, text, source, matches)
    strategy_label = _strategy_label(catalyst_type, text)
    source_quality_score = _source_quality(source)
    novelty_score = _novelty_score(category, matches, text)
    urgency_score = _urgency_score(published_at)
    historical_score = _historical_score(catalyst_type, matches)
    relevance_score = _relevance_score(category, ticker, text)
    market_impact_score = _market_impact_score(catalyst_type, matches, text)
    keyword_score = min(100.0, max(0.0, abs(raw_score) * 18 + len(matches) * 4))
    sector_score = _sector_score(item, text)
    catalyst_score = int(round(
        novelty_score * 0.16
        + urgency_score * 0.12
        + historical_score * 0.16
        + relevance_score * 0.14
        + market_impact_score * 0.18
        + source_quality_score * 0.10
        + keyword_score * 0.08
        + sector_score * 0.06
    ))
    catalyst_score = max(0, min(100, catalyst_score))
    confidence = min(0.95, max(0.50, (catalyst_score / 100) * 0.78 + source_quality_score / 500))
    explanation = _explanation(
        catalyst_type=catalyst_type,
        catalyst_score=catalyst_score,
        matches=matches,
        item=item,
        category=category,
        source_quality_score=source_quality_score,
        sector_score=sector_score,
        historical_score=historical_score,
    )
    supporting_evidence = _supporting_evidence(item, matches, source, published_at)

    result = {
        "ticker": ticker,
        "headline": headline,
        "summary": summary,
        "source": source,
        "source_url": str(item.get("source_url", "")).strip(),
        "published_at": published_at,
        "discovered_at": str(item.get("discovered_at") or datetime.now(timezone.utc).isoformat()),
        "security_type": str(item.get("security_type", "stock")).strip() or "stock",
        "exchange": str(item.get("exchange", "")).strip(),
        "sector": str(item.get("sector", "")).strip(),
        "catalyst_type": catalyst_type,
        "strategy_label": strategy_label,
        "direction": bias,
        "novelty_score": round(novelty_score, 1),
        "urgency_score": round(urgency_score, 1),
        "historical_score": round(historical_score, 1),
        "relevance_score": round(relevance_score, 1),
        "market_impact_score": round(market_impact_score, 1),
        "source_quality_score": round(source_quality_score, 1),
        "keyword_score": round(keyword_score, 1),
        "sector_score": round(sector_score, 1),
        "catalyst_score": catalyst_score,
        "explanation": explanation,
        "supporting_evidence": supporting_evidence,
        "matched_keywords": matches,
        "category": category,
        "category_label": category.replace("_", " ").title(),
        "category_reason": category_reason,
        "category_rank": _category_rank(category),
        "bias": bias,
        "confidence": round(confidence, 2),
        "actionability_score": actionability_score,
        "trade_candidate": trade_candidate and catalyst_score >= 68,
        "read": f"{bias.title()} {category.replace('_', ' ')} read from {', '.join(reason_bits)}.",
        "next_check": "Confirm float, relative volume, spread, halt risk, and chart level before paper testing.",
        "raw_payload": item,
    }
    # MVP Analyst Brain score (deterministic). Macro defaults to neutral here — the
    # radar has no macro snapshot — so catalyst + narrative do the differentiating.
    alpha = score_idea(
        catalyst_inputs_from_radar_row(result),
        narrative_inputs_for_ticker(ticker),
        MacroInputs(),
    )
    result["alpha"] = alpha.model_dump()
    return result


def classify_catalyst(item: dict[str, Any], text: str | None = None) -> tuple[str, str]:
    headline = str(item.get("headline", "")).strip()
    summary = str(item.get("summary", "")).strip()
    ticker = str(item.get("ticker", "")).strip().upper()
    source = str(item.get("source", "")).lower()
    text = text or f"{headline} {summary}".lower()
    related_tickers = [str(symbol).upper() for symbol in item.get("related_tickers", []) if symbol]

    if any(term in text for term in LOW_ACTIONABILITY_TERMS):
        return "low_actionability", "opinion, recap, or low-specificity article"

    is_broad_market = any(term in text for term in BROAD_MARKET_TERMS)
    is_sector_read = any(term in text for term in SECTOR_SYMPATHY_TERMS)
    has_many_related = len(set(related_tickers)) >= 3
    has_direct_source = any(feed in source for feed in DIRECT_SOURCE_FEEDS)
    has_direct_terms = any(term in text for term in DIRECT_CATALYST_TERMS)
    has_company_specificity = _has_company_specificity(ticker, text, related_tickers, source)

    if any(term in text for term in BROAD_INDEX_MACRO_TERMS) and not has_direct_source:
        return "broad_market_mention", "broad index, macro, or market-wide story"

    if is_sector_read and has_many_related:
        return "sympathy_sector_read", "sector, supplier, peer, or multi-ticker read-through"

    if (has_direct_source or has_direct_terms) and has_company_specificity:
        if ticker and (ticker.lower() in text or _company_name_hint(ticker, text) or "sec edgar" in source):
            return "direct_company_catalyst", "direct ticker/company catalyst language"
        if has_direct_source and not has_many_related and not is_broad_market:
            return "direct_company_catalyst", "single-company source item with catalyst language"

    if is_broad_market and not has_direct_source:
        return "broad_market_mention", "broad index, macro, ETF, or market-wide story"

    if is_sector_read:
        return "sympathy_sector_read", "sector, supplier, peer, or multi-ticker read-through"

    if is_broad_market:
        return "broad_market_mention", "broad index, macro, or market-wide story"

    if has_many_related:
        return "sympathy_sector_read", "sector, supplier, peer, or multi-ticker read-through"

    if any(match in text for match in ["ai", "artificial intelligence", "data center", "datacenter"]):
        return "sympathy_sector_read", "theme-level AI/datacenter mention without direct company action"

    return "low_actionability", "no direct catalyst language detected"


def _has_company_specificity(ticker: str, text: str, related_tickers: list[str], source: str) -> bool:
    if "sec edgar" in source:
        return True
    if ticker and (ticker.lower() in text or _company_name_hint(ticker, text)):
        return True
    if ticker and related_tickers and set(related_tickers) == {ticker}:
        return True
    return False


def _company_name_hint(ticker: str, text: str) -> bool:
    hints = {
        "AAPL": ["apple"],
        "AMZN": ["amazon"],
        "AMD": ["amd", "advanced micro"],
        "AVGO": ["broadcom"],
        "COIN": ["coinbase"],
        "GOOGL": ["alphabet", "google"],
        "META": ["meta"],
        "MSFT": ["microsoft"],
        "MSTR": ["microstrategy", "strategy"],
        "NVDA": ["nvidia"],
        "ORCL": ["oracle"],
        "PLTR": ["palantir"],
        "SMCI": ["super micro"],
        "TSLA": ["tesla"],
    }
    return any(hint in text for hint in hints.get(ticker, []))


def _category_rank(category: str) -> int:
    return {
        "direct_company_catalyst": 4,
        "sympathy_sector_read": 3,
        "broad_market_mention": 2,
        "low_actionability": 1,
    }.get(category, 0)


def _catalyst_type(item: dict[str, Any], text: str, source: str, matches: list[dict[str, Any]]) -> str:
    explicit = str(item.get("catalyst_type") or "").strip()
    if explicit:
        return explicit
    labels = " ".join(match["label"].lower() for match in matches)
    source_l = source.lower()
    combined = f"{text} {labels} {source_l}"
    if any(term in combined for term in ["artificial intelligence", "machine learning", " ai ", "data center", "datacenter"]):
        return "AI Partnership" if "partner" in combined or "agreement" in combined else "AI Catalyst"
    if "government contract" in combined or "defense contract" in combined:
        return "Government Contract"
    if "8-k" in combined or "sec edgar" in combined or "form 4" in combined:
        return "SEC Filing"
    if "s-1" in combined or "ipo" in combined:
        return "IPO Momentum"
    if "raises guidance" in combined or "cuts guidance" in combined or "earnings" in combined:
        return "Earnings Revision"
    if "upgrade" in combined or "downgrade" in combined or "initiates coverage" in combined:
        return "Analyst Upgrade" if "downgrade" not in combined else "Analyst Downgrade"
    if "partnership" in combined or "agreement" in combined or "partners with" in combined:
        return "Partnership Catalyst"
    if "acquisition" in combined or "acquires" in combined:
        return "Acquisition Catalyst"
    if "offering" in combined or "financing" in combined or "registered direct" in combined:
        return "Financing Event"
    return "News Catalyst"


def _strategy_label(catalyst_type: str, text: str) -> str:
    combined = f"{catalyst_type} {text}".lower()
    for token, label in CATALYST_STRATEGY_LABELS.items():
        if token in combined:
            if label == "Analyst Upgrade" and "downgrade" in combined:
                return "Analyst Downgrade"
            return label
    return "News Catalyst"


def _source_quality(source: str) -> float:
    source_l = source.lower()
    for token, score in CATALYST_SOURCE_QUALITY.items():
        if token in source_l:
            return float(score)
    return 65.0


def _urgency_score(published_at: str) -> float:
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)
    except ValueError:
        return 55.0
    if age_hours <= 1:
        return 100.0
    if age_hours <= 6:
        return 88.0
    if age_hours <= 24:
        return 72.0
    if age_hours <= 72:
        return 50.0
    return 30.0


def _novelty_score(category: str, matches: list[dict[str, Any]], text: str) -> float:
    score = 40.0 + len(matches) * 8
    if category == "direct_company_catalyst":
        score += 25
    if any(term in text for term in ["first", "new", "launches", "wins", "awarded", "approval"]):
        score += 15
    if category in {"broad_market_mention", "low_actionability"}:
        score -= 20
    return max(0.0, min(100.0, score))


def _historical_score(catalyst_type: str, matches: list[dict[str, Any]]) -> float:
    type_l = catalyst_type.lower()
    base = 58.0
    if any(term in type_l for term in ["ai", "government contract", "ipo", "sec filing", "earnings", "analyst", "partnership", "acquisition"]):
        base += 22
    if any(match["weight"] < 0 for match in matches):
        base += 8
    return min(100.0, base)


def _relevance_score(category: str, ticker: str, text: str) -> float:
    score = 45.0
    if ticker and (ticker.lower() in text or _company_name_hint(ticker, text)):
        score += 35
    if category == "direct_company_catalyst":
        score += 18
    elif category == "sympathy_sector_read":
        score += 5
    else:
        score -= 15
    return max(0.0, min(100.0, score))


def _market_impact_score(catalyst_type: str, matches: list[dict[str, Any]], text: str) -> float:
    score = 42.0 + sum(abs(float(match["weight"])) for match in matches) * 10
    if any(term in catalyst_type.lower() for term in ["government contract", "ai", "ipo", "earnings", "acquisition"]):
        score += 18
    if any(term in text for term in ["small float", "above-average volume", "large contract", "exclusive", "strategic"]):
        score += 14
    return max(0.0, min(100.0, score))


def _sector_score(item: dict[str, Any], text: str) -> float:
    explicit = str(item.get("sector") or "").lower()
    combined = f"{explicit} {text}"
    if any(term in combined for term in ["ai", "semiconductor", "defense", "biotech", "energy", "crypto"]):
        return 88.0
    if explicit:
        return 68.0
    return 50.0


def _explanation(
    catalyst_type: str,
    catalyst_score: int,
    matches: list[dict[str, Any]],
    item: dict[str, Any],
    category: str,
    source_quality_score: float,
    sector_score: float,
    historical_score: float,
) -> list[str]:
    bits = [f"Catalyst Score: {catalyst_score}"]
    if catalyst_type:
        bits.append(f"+ {catalyst_type}")
    bits.extend([f"+ {match['label']}" for match in matches[:4]])
    if category == "direct_company_catalyst":
        bits.append("+ Direct company-specific catalyst")
    if source_quality_score >= 80:
        bits.append("+ High-quality primary or wire source")
    if sector_score >= 80:
        bits.append("+ Strong sector relevance")
    if historical_score >= 80:
        bits.append("+ Similar catalyst types have historically mattered")
    if item.get("float") or item.get("relative_volume"):
        bits.append("+ Float or volume context supplied")
    return list(dict.fromkeys(bits))


def _supporting_evidence(
    item: dict[str, Any],
    matches: list[dict[str, Any]],
    source: str,
    published_at: str,
) -> list[dict[str, Any]]:
    evidence = [
        {
            "label": source,
            "url": str(item.get("source_url", "")).strip(),
            "timestamp": published_at,
        }
    ]
    for match in matches[:5]:
        evidence.append({"label": match["label"], "keyword": match["keyword"], "weight": match["weight"]})
    return evidence


def _categorized(scored: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "direct_company_catalysts": [],
        "broad_market_mentions": [],
        "sympathy_sector_reads": [],
        "low_actionability_articles": [],
    }
    mapping = {
        "direct_company_catalyst": "direct_company_catalysts",
        "broad_market_mention": "broad_market_mentions",
        "sympathy_sector_read": "sympathy_sector_reads",
        "low_actionability": "low_actionability_articles",
    }
    for row in scored:
        key = mapping.get(row["category"], "low_actionability_articles")
        groups[key].append(row)
    return groups


def catalyst_to_signal(catalyst: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": catalyst["ticker"],
        "asset_type": "crypto" if catalyst.get("security_type") == "crypto" else "equity",
        "sector": catalyst.get("sector", ""),
        "bias": catalyst["bias"],
        "confidence": catalyst["confidence"],
        "timeframe": "intraday",
        "reason": (
            f"Catalyst Radar: {catalyst['headline']} "
            f"Score {catalyst['catalyst_score']}/100; matched "
            f"{', '.join(match['keyword'] for match in catalyst['matched_keywords']) or 'no keywords'}. "
            f"Source {catalyst['source']} at {catalyst['published_at']}."
        ),
        "source": "catalyst_radar",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_tags": [catalyst["strategy_label"], catalyst["catalyst_type"], catalyst["category"]],
        "theme": catalyst["catalyst_type"],
        "catalyst": catalyst["summary"] or catalyst["headline"],
        "catalyst_type": catalyst["catalyst_type"],
        "catalyst_score": catalyst["catalyst_score"],
        "catalyst_event_id": catalyst.get("id"),
        "market_regime": catalyst.get("market_regime", ""),
        "source_url": catalyst.get("source_url", ""),
        "source_refs": catalyst.get("supporting_evidence") or [
            {"label": catalyst["source"], "url": catalyst.get("source_url", ""), "timestamp": catalyst["published_at"]}
        ],
        "supporting_evidence": catalyst.get("supporting_evidence", []),
        "explanation": catalyst.get("explanation", []),
        "alpha": catalyst.get("alpha"),
    }


def _normalize_catalysts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("catalysts") if isinstance(payload.get("catalysts"), list) else payload.get("items")
    if raw is None:
        raw = [payload]
    catalysts = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        headline = str(item.get("headline", "")).strip()
        if ticker and headline:
            catalysts.append({**item, "ticker": ticker, "headline": headline})
    return catalysts
