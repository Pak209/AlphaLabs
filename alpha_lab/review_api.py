"""review.v1 read-model builder for the PM Approval UX.

Pure, side-effect-free shaping of already-fetched AlphaLabs data into the
`review.v1` briefing contract consumed by the mobile prototype
(`prototype/data.js` -> REVIEW_MOCK.briefing). This module performs NO I/O:
the service layer fetches rows (safety status, futures snapshots, market
briefings, alpha ideas, approval queue) and hands them here for shaping, so the
logic is unit-testable without a database or network.

Honesty contract: fields the backend cannot yet compute are returned with an
explicit ``availability`` of "not_implemented" / "no_entitlement" /
"insufficient_data" / "unavailable" and a null value, never a fabricated number.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "review.v1"

# Conviction tier thresholds (mirror scoring_engine tiers).
_TIER_HIGH = 80.0
_TIER_TRADEABLE = 70.0
_TIER_WATCHLIST = 60.0

# Idea statuses that are still in front of a reviewer.
_REVIEWABLE_STATUSES = {"new", "needs_review"}

# Max cards returned in the displayed briefing queue (leaders/counts use full set).
_TOP_OPPORTUNITIES = 5

# Freshness bucketing (seconds).
_FRESH_MAX = 15 * 60
_RECENT_MAX = 2 * 60 * 60


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #
def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _freshness(as_of: Optional[str], now: datetime) -> dict[str, Any]:
    """Build a DataFreshness block from an ISO timestamp relative to ``now``."""
    dt = _parse_iso(as_of)
    if dt is None:
        return {
            "level": "unknown",
            "as_of": None,
            "age_seconds": None,
            "label": "Freshness unknown",
            "is_stale": True,
        }
    age = max(0, int((now - dt).total_seconds()))
    if age < _FRESH_MAX:
        level, is_stale = "fresh", False
    elif age < _RECENT_MAX:
        level, is_stale = "recent", False
    else:
        level, is_stale = "stale", True
    return {
        "level": level,
        "as_of": _iso(dt),
        "age_seconds": age,
        "label": _age_label(age),
        "is_stale": is_stale,
    }


def _age_label(age_seconds: int) -> str:
    minutes = age_seconds // 60
    if minutes < 1:
        return "Updated just now"
    if minutes < 60:
        return f"Updated {minutes} min ago"
    hours = age_seconds / 3600
    return f"Updated {hours:.1f} hrs ago"


def _normalize_confidence(value: Any) -> Optional[int]:
    """Return a 0-100 integer confidence.

    Snapshots persist confidence either as a 0-1 fraction (e.g. 0.84) or as an
    already-scaled 0-100 value. Treat anything in [0, 1] as a fraction and scale
    it; values above 1 are assumed to already be on the 0-100 scale.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= num <= 1.0:
        num *= 100.0
    return int(round(num))


def _conviction_from_idea(idea: dict[str, Any]) -> Optional[int]:
    """Best-available conviction (0-100) for an un-traded idea.

    The composite alpha score (`alpha_composite`) is only written on the trades
    table after a scoring/trade run, so for a pending idea the most honest single
    number is the analyst confidence (0-1). Returns None if absent.
    """
    confidence = idea.get("confidence")
    if confidence is None:
        return None
    try:
        return int(round(float(confidence) * 100))
    except (TypeError, ValueError):
        return None


def _tier(score: Optional[float]) -> str:
    if score is None:
        return "ignore"
    if score >= _TIER_HIGH:
        return "high_conviction"
    if score >= _TIER_TRADEABLE:
        return "tradeable"
    if score >= _TIER_WATCHLIST:
        return "watchlist"
    return "ignore"


def _direction(bias: Optional[str]) -> str:
    return "SHORT" if str(bias or "").strip().lower() == "bearish" else "LONG"


def _strategy(timeframe: Optional[str]) -> str:
    tf = str(timeframe or "").strip().lower()
    if tf == "intraday":
        return "Day Trade"
    if tf == "swing":
        return "Swing"
    if tf == "position":
        return "LEAPS"
    return "Swing"


def _hold_period_text(timeframe: Optional[str]) -> Optional[str]:
    tf = str(timeframe or "").strip().lower()
    if tf == "intraday":
        return "Intraday"
    if tf == "swing":
        return "Multi-day"
    if tf == "position":
        return "Weeks+"
    return None


def _star_rating(score: Optional[float]) -> float:
    if score is None:
        return 0.0
    return round((score / 100.0) * 5 * 2) / 2  # nearest half-star


def _star_display(rating: float) -> str:
    full = int(rating)
    half = (rating - full) >= 0.5
    return "★" * full + ("½" if half else "")


def _actions(idea_id: int) -> list[dict[str, Any]]:
    """Action metadata. Read endpoints never mutate; they only describe which
    button to show and which OTHER endpoint the UI would call. watchlist has no
    backend yet, so it is returned disabled + not_implemented rather than faked.
    The approve/reject/explain endpoints already exist in api.py."""
    return [
        {"action": "approve", "label": "Approve", "method": "POST",
         "endpoint": f"/api/ideas/{idea_id}/approval/approve", "enabled": True, "style": "primary"},
        {"action": "reject", "label": "Reject", "method": "POST",
         "endpoint": f"/api/ideas/{idea_id}/approval/reject", "enabled": True, "style": "danger"},
        {"action": "watchlist", "label": "Watchlist", "method": "POST",
         "endpoint": f"/api/ideas/{idea_id}/watchlist", "enabled": False, "style": "neutral",
         "unavailable_reason": "not_implemented"},
        {"action": "explain", "label": "Explain", "method": "GET",
         "endpoint": f"/api/ideas/{idea_id}/explanation", "enabled": True, "style": "ghost"},
    ]


def _card_from_idea(idea: dict[str, Any]) -> dict[str, Any]:
    idea_id = int(idea["id"])
    score = _conviction_from_idea(idea)
    rating = _star_rating(score)
    return {
        "idea_id": idea_id,
        "ticker": idea.get("ticker"),
        "name": idea.get("ticker"),  # human company name not stored on idea -> ticker
        "logo_domain": None,  # presentation-only; not stored server-side
        "direction": _direction(idea.get("bias")),
        "conviction_score": score,
        "star_rating": rating,
        "star_display": _star_display(rating),
        # expected move is not stored on a pending idea -> honest null, not faked.
        "expected_move_text": None,
        "hold_period_text": _hold_period_text(idea.get("timeframe")),
        "strategy": _strategy(idea.get("timeframe")),
        "trend_spark": [],  # no per-idea score history persisted yet
        "trend_direction": "flat",
        "tier": _tier(score),
        "actions": _actions(idea_id),
    }


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _safety_block(safety: dict[str, Any]) -> dict[str, Any]:
    """Map scheduler_safety_status() -> review.v1 SafetyStatus. Read-only: this
    never changes posture, it only describes it."""
    posture = "paper" if safety.get("scheduler_mode") == "paper" else "dry_run"
    armed = bool(safety.get("automation_paper_trading_armed"))
    posture_label = "Paper" if posture == "paper" else "Dry run"
    return {
        "posture": posture,
        "armed": armed,
        "reviewable": True,  # reading/reviewing is always allowed
        "label": f"{posture_label} · {'armed' if armed else 'disarmed'}",
    }


def _regime_direction(regime: str) -> str:
    r = str(regime or "").strip().lower()
    if r in {"risk_on", "bullish"}:
        return "bullish"
    if r in {"risk_off", "bearish", "safe_haven_unwind", "oil_shock", "inflation_rates_shock"}:
        return "bearish"
    return "neutral"


def _market_regime(snapshot: Optional[dict[str, Any]], now: datetime) -> dict[str, Any]:
    if not snapshot:
        return {
            "availability": "unavailable",
            "label": "UNKNOWN", "direction": "neutral",
            "confidence": None, "confidence_text": "No regime snapshot",
            "futures": [], "freshness": _freshness(None, now),
            "note": "No futures snapshot available yet.",
        }
    payload = snapshot.get("payload") or {}
    regime = payload.get("regime") or {}
    regime_name = regime.get("regime") or snapshot.get("regime") or "neutral"
    label = regime.get("label") or snapshot.get("regime_label") or str(regime_name).upper()
    confidence = regime.get("confidence")
    if confidence is None:
        confidence = snapshot.get("confidence")
    confidence = _normalize_confidence(confidence)

    futures = []
    for move in payload.get("moves") or []:
        if not move.get("has_data"):
            continue
        net = move.get("net_move_pct")
        try:
            net = float(net)
        except (TypeError, ValueError):
            continue
        futures.append({
            "name": move.get("name") or move.get("symbol"),
            "value_text": f"{net:+.2f}%",
            "change_pct": round(net, 2),
            "direction": move.get("direction") or "flat",
        })

    return {
        "availability": "available",
        "label": str(label).upper(),
        "direction": _regime_direction(regime_name),
        "confidence": confidence,
        "confidence_text": (f"{confidence}% confidence" if confidence is not None else "Confidence unknown"),
        "futures": futures,
        "freshness": _freshness(snapshot.get("generated_at"), now),
    }


def _lex_summary(briefing: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not briefing:
        return {"availability": "unavailable", "text": None, "generated_at": None, "source": None,
                "note": "No stored market briefing yet."}
    payload = briefing.get("payload") or {}
    tone = payload.get("broad_market_tone") or "mixed"
    sector = payload.get("major_indexes_sector_movement")
    themes = payload.get("themes") or []
    theme_text = ""
    if themes:
        first = themes[0]
        theme_text = first if isinstance(first, str) else (first.get("label") or first.get("name") or "")
    parts = [f"Broad market tone is {tone}."]
    if sector:
        parts.append(str(sector))
    if theme_text:
        parts.append(f"Leading theme: {theme_text}.")
    return {
        "availability": "available",
        "text": " ".join(parts),
        "generated_at": briefing.get("generated_at") or payload.get("generated_at"),
        "source": "stored_briefing",
    }


def _market_risks(briefing: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not briefing:
        return []
    payload = briefing.get("payload") or {}
    risks = payload.get("macro_risks") or []
    out = []
    for risk in risks:
        label = risk if isinstance(risk, str) else (risk.get("label") or risk.get("name") or "")
        if not label:
            continue
        # Severity ranking of macro risks is not modeled yet -> honest "unknown".
        out.append({"label": label, "severity": "unknown"})
    return out


def _pending_approvals(pending: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(pending)
    high = 0
    for item in pending:
        conf = item.get("confidence")
        try:
            if conf is not None and float(conf) * 100 >= _TIER_HIGH:
                high += 1
        except (TypeError, ValueError):
            continue
    return {"total": total, "high_conviction": high, "needs_review": total}


# --------------------------------------------------------------------------- #
# Top-level builder
# --------------------------------------------------------------------------- #
def build_review_briefing(
    *,
    safety: dict[str, Any],
    futures_snapshots: list[dict[str, Any]],
    market_briefings: list[dict[str, Any]],
    ideas: list[dict[str, Any]],
    pending_approvals: list[dict[str, Any]],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Shape raw AlphaLabs rows into a review.v1 briefing payload.

    All inputs are already-fetched plain dicts/lists; this function does no I/O.
    """
    now = now or datetime.now(timezone.utc)
    snapshot = futures_snapshots[0] if futures_snapshots else None
    briefing = market_briefings[0] if market_briefings else None

    reviewable = [i for i in ideas if str(i.get("status", "")).lower() in _REVIEWABLE_STATUSES]
    # Full ranked set: used for best_opportunity and the long/short leaders so
    # those always consider every reviewable idea, not just the displayed top N.
    cards = [_card_from_idea(i) for i in reviewable]
    cards.sort(key=lambda c: (c["conviction_score"] is None, -(c["conviction_score"] or 0)))

    longs = [c for c in cards if c["direction"] == "LONG"]
    shorts = [c for c in cards if c["direction"] == "SHORT"]

    # Envelope freshness = WORST-CASE across contributing dated sections (regime
    # snapshot + stored briefing), i.e. the OLDEST timestamp. The contract treats
    # the envelope as "the whole briefing is only as fresh as its stalest input",
    # so a recent snapshot does not mask a stale briefing (or vice versa).
    contributing_times = [
        snapshot.get("generated_at") if snapshot else None,
        briefing.get("generated_at") if briefing else None,
    ]
    oldest = None
    for ts in contributing_times:
        dt = _parse_iso(ts)
        if dt and (oldest is None or dt < oldest):
            oldest = dt

    meta = {
        "generated_at": _iso(now),
        "schema_version": SCHEMA_VERSION,
        "data_freshness": _freshness(_iso(oldest) if oldest else None, now),
        "safety_status": _safety_block(safety),
    }

    return {
        "meta": meta,
        "market_regime": _market_regime(snapshot, now),
        "lex_summary": _lex_summary(briefing),
        # best_opportunity is the single top card across the FULL reviewable set.
        "best_opportunity": cards[0] if cards else None,
        # Displayed queue is capped to the top N; leaders/counts below still use
        # the full set so capping the display never hides a conviction leader.
        "top_opportunities": cards[:_TOP_OPPORTUNITIES],
        # Honest null when there is genuinely no high-conviction short today.
        "highest_conviction_short": shorts[0] if shorts else None,
        "highest_conviction_long": longs[0] if longs else None,
        # No add/remove tracking persisted yet.
        "watchlist_changes": {"availability": "not_implemented", "added": None, "removed": None,
                              "note": "Watchlist change tracking not implemented."},
        "market_risks": _market_risks(briefing),
        # Sector exposure needs live broker positions + a classifier; neither is
        # wired into this read path, so it is honestly marked not_implemented.
        "portfolio_exposure": {"availability": "not_implemented", "segments": [], "freshness": None,
                               "note": "Sector exposure computation not implemented in the read API."},
        "pending_approvals": _pending_approvals(pending_approvals),
    }


# --------------------------------------------------------------------------- #
# Opportunity detail (Screen B) — read-only shaping
# --------------------------------------------------------------------------- #
_AI_DISCLAIMER = "AlphaLabs AI may make mistakes. Verify before acting. Paper research only — not financial advice."

# Canonical six-source confidence breakdown shown on Screen B. Per-source scoring
# is NOT computed in this read path, so every source is returned not_implemented
# with a null score rather than a fabricated number.
_CONFIDENCE_SOURCES = [
    ("news", "News"),
    ("sec", "SEC Filings"),
    ("historical_similarity", "Historical Similarity"),
    ("options", "Options Activity"),
    ("technicals", "Technicals"),
    ("macro", "Macro Environment"),
]


def _tier_text(tier: str) -> str:
    return {
        "high_conviction": "High Conviction",
        "tradeable": "Tradeable",
        "watchlist": "Watchlist",
        "ignore": "Ignore",
    }.get(tier, "Unknown")


def _chips(idea: dict[str, Any]) -> list[str]:
    """Presentation chips derived from real idea attributes (theme/sector/catalyst
    type). De-duplicated, blanks dropped, order preserved."""
    chips: list[str] = []
    for value in (idea.get("theme"), idea.get("sector"), idea.get("catalyst_type")):
        text = str(value or "").strip()
        if text and text not in chips:
            chips.append(text)
    return chips


def _detail_actions(idea_id: int, status: Optional[str]) -> list[dict[str, Any]]:
    """Status-aware action metadata. The read endpoint NEVER mutates; it only
    describes which buttons to show and which OTHER endpoint the UI would call.
    approve/reject are enabled only while the idea is still reviewable; once
    decided they are disabled with an honest reason. watchlist has no backend yet."""
    state = str(status or "").strip().lower()
    reviewable = state in _REVIEWABLE_STATUSES
    if reviewable:
        decided_reason = None
    elif state in {"approved", "rejected", "expired"}:
        decided_reason = "already_decided"
    else:
        decided_reason = "not_reviewable"

    def decision(action: str, label: str, endpoint: str, style: str) -> dict[str, Any]:
        meta = {"action": action, "label": label, "method": "POST",
                "endpoint": endpoint, "enabled": reviewable, "style": style}
        if not reviewable:
            meta["unavailable_reason"] = decided_reason
        return meta

    return [
        decision("approve", "Approve", f"/api/ideas/{idea_id}/approval/approve", "primary"),
        decision("reject", "Reject", f"/api/ideas/{idea_id}/approval/reject", "danger"),
        {"action": "watchlist", "label": "Watchlist", "method": "POST",
         "endpoint": f"/api/ideas/{idea_id}/watchlist", "enabled": False, "style": "neutral",
         "unavailable_reason": "not_implemented"},
        {"action": "explain", "label": "Explain", "method": "GET",
         "endpoint": f"/api/ideas/{idea_id}/explanation", "enabled": True, "style": "ghost"},
    ]


def _confidence_breakdown() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": label, "score": None, "score_text": "—",
         "availability": "not_implemented",
         "note": "Per-source confidence breakdown not computed in the read API."}
        for key, label in _CONFIDENCE_SOURCES
    ]


def _opportunity_thesis(idea: dict[str, Any], expl: dict[str, Any]) -> dict[str, Any]:
    """Thesis text from the analyst explanation (preferred) or the idea's stored
    thesis. Structured bull/bear decomposition is not modeled, so those lists are
    honestly empty rather than fabricated."""
    why = (str(expl.get("why_this_matters") or "").strip()
           or str(idea.get("thesis") or "").strip()
           or str(expl.get("thesis_summary") or "").strip())
    return {
        "availability": "available" if why else "insufficient_data",
        "why_this_matters": why or None,
        "bull_case": [],
        "bear_case": [],
        "note": "Structured bull/bear decomposition is not modeled; see thesis text and key risks.",
    }


def _ai_explanation(expl: dict[str, Any], expl_generated_at: Optional[str]) -> dict[str, Any]:
    """Screen B AI explanation, drawn from the persisted analyst explanation. When
    no explanation exists the section is honestly insufficient_data, never faked."""
    if not expl:
        return {"availability": "insufficient_data", "bullets": [], "probability": None,
                "disclaimer": _AI_DISCLAIMER, "generated_at": None, "source": None}
    bullets: list[str] = []
    for field in ("thesis_summary", "why_this_matters", "catalyst", "setup_type", "market_context"):
        text = str(expl.get(field) or "").strip()
        if text and text not in bullets:
            bullets.append(text)
    probability = _normalize_confidence(expl.get("confidence_score"))
    return {
        "availability": "available",
        "bullets": bullets,
        "probability": probability,
        "disclaimer": _AI_DISCLAIMER,
        "generated_at": expl_generated_at or expl.get("created_at"),
        "source": "stored_explanation",
    }


def _key_risks(expl: dict[str, Any]) -> list[str]:
    risks = expl.get("risk_factors")
    if isinstance(risks, str):
        risks = [risks]
    if not isinstance(risks, list):
        return []
    return [str(r).strip() for r in risks if str(r).strip()]


def _normalize_refs(refs: Any) -> list[Any]:
    return refs if isinstance(refs, list) else []


def _supporting_evidence(idea: dict[str, Any], expl: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence chips from the real catalyst text + explanation source refs. De-duped
    by label; empty when nothing is stored (no fabricated evidence)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(label: str, kind: str) -> None:
        text = str(label or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append({"label": text, "kind": kind})

    catalyst = str(idea.get("catalyst") or "").strip()
    if catalyst:
        add(catalyst, str(idea.get("catalyst_type") or "catalyst").strip() or "catalyst")
    for ref in _normalize_refs(expl.get("source_refs")):
        if isinstance(ref, dict):
            add(ref.get("label") or ref.get("url") or "", "reference")
        else:
            add(str(ref), "reference")
    return out


def _opportunity_source_refs(idea: dict[str, Any], expl: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured source references. The catalyst event (if linked) resolves to a
    real /api/catalysts/{id} URL; explanation refs are passed through honestly."""
    out: list[dict[str, Any]] = []
    event_id = idea.get("catalyst_event_id")
    if event_id is not None:
        ctype = str(idea.get("catalyst_type") or "catalyst").strip() or "catalyst"
        out.append({"id": f"cat_{event_id}", "kind": "catalyst",
                    "label": f"{ctype} · {idea.get('ticker')}",
                    "url": f"/api/catalysts/{event_id}"})
    for ref in _normalize_refs(expl.get("source_refs")):
        if isinstance(ref, dict):
            out.append({"id": None, "kind": "reference",
                        "label": ref.get("label") or ref.get("url") or "reference",
                        "url": ref.get("url")})
        else:
            out.append({"id": None, "kind": "reference", "label": str(ref), "url": None})
    return out


def build_review_opportunity(
    *,
    idea: dict[str, Any],
    explanation: Optional[dict[str, Any]],
    safety: dict[str, Any],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Shape one already-fetched alpha idea (+ its analyst explanation) into the
    review.v1 Screen B OpportunityDetail contract.

    Pure: no I/O, no mutation, no side effects. ``idea`` is a row dict from the
    repository (already carrying ``trade_explanation`` and ``strategies``);
    ``explanation`` is the full trade_explanation row (or None). Fields the backend
    cannot compute are returned with honest availability states and null values.
    """
    now = now or datetime.now(timezone.utc)

    # Inner explanation dict: prefer the full row's parsed explanation, fall back
    # to the copy the repository attached to the idea.
    expl = {}
    expl_generated_at = None
    if explanation:
        expl = explanation.get("explanation") or {}
        expl_generated_at = explanation.get("created_at")
    if not expl:
        expl = idea.get("trade_explanation") or {}

    idea_id = int(idea["id"])
    score = _conviction_from_idea(idea)
    tier = _tier(score)
    rating = _star_rating(score)
    status = idea.get("status")

    # as_of = when the idea record was last produced/touched (real timestamp).
    as_of = idea.get("updated_at") or idea.get("created_at")

    meta = {
        "generated_at": _iso(now),
        "schema_version": SCHEMA_VERSION,
        "data_freshness": _freshness(as_of, now),
        "safety_status": _safety_block(safety),
    }

    header = {
        "idea_id": idea_id,
        "ticker": idea.get("ticker"),
        "name": idea.get("ticker"),  # company name not stored server-side -> ticker
        "logo_domain": None,          # presentation-only; not stored
        "chips": _chips(idea),
        "direction": _direction(idea.get("bias")),
        "strategy": _strategy(idea.get("timeframe")),
    }

    conviction = {
        "score": score,
        "tier": tier,
        "tier_text": _tier_text(tier),
        "star_rating": rating,
        "star_display": _star_display(rating),
        # No per-idea conviction history persisted yet -> honest empty trend.
        "trend_series": [],
        "trend_labels": [],
        "trend_direction": "flat",
        "trend_text": None,
        # Expected move %, modeled risk level, and a distinct win probability are
        # not stored on a pending idea -> honest nulls rather than fabricated values.
        "expected_move_text": None,
        "risk_level": None,
        "hold_period_text": _hold_period_text(idea.get("timeframe")),
        "win_probability": None,
        "snapshotted_at": idea.get("created_at"),
    }

    return {
        "meta": meta,
        "header": header,
        "conviction": conviction,
        "thesis": _opportunity_thesis(idea, expl),
        "confidence_breakdown": _confidence_breakdown(),
        "supporting_evidence": _supporting_evidence(idea, expl),
        # Historical similarity matching is not wired into this read path.
        "historical_setups": {"status": "not_implemented", "summary_text": None, "setups": [],
                              "note": "Historical similarity matching not implemented in the read API."},
        "ai_explanation": _ai_explanation(expl, expl_generated_at),
        "key_risks": _key_risks(expl),
        "source_refs": _opportunity_source_refs(idea, expl),
        # Action metadata only — the read endpoint performs no approve/reject/watchlist.
        "actions": _detail_actions(idea_id, status),
    }
