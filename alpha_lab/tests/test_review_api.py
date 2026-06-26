"""Tests for the read-only review.v1 briefing endpoint and its pure builder."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.review_api import build_review_briefing
from alpha_lab.service import AlphaLabService

NOW = datetime(2026, 6, 25, 14, 0, 0, tzinfo=timezone.utc)

# review.v1 briefing top-level keys the prototype's REVIEW_MOCK.briefing exposes.
BRIEFING_KEYS = {
    "meta", "market_regime", "lex_summary", "best_opportunity", "top_opportunities",
    "highest_conviction_short", "highest_conviction_long", "watchlist_changes",
    "market_risks", "portfolio_exposure", "pending_approvals",
}
CARD_KEYS = {
    "idea_id", "ticker", "name", "logo_domain", "direction", "conviction_score",
    "star_rating", "star_display", "expected_move_text", "hold_period_text",
    "strategy", "trend_spark", "trend_direction", "tier", "actions",
}

SAFE = {"scheduler_mode": "dry_run", "automation_paper_trading_armed": False}


def test_builder_empty_sources_return_honest_states():
    out = build_review_briefing(
        safety=SAFE, futures_snapshots=[], market_briefings=[],
        ideas=[], pending_approvals=[], now=NOW,
    )
    assert set(out.keys()) == BRIEFING_KEYS
    assert out["meta"]["schema_version"] == "review.v1"
    assert out["meta"]["safety_status"] == {
        "posture": "dry_run", "armed": False, "reviewable": True, "label": "Dry run · disarmed",
    }
    # No real data -> honest unavailable / not_implemented, never faked numbers.
    assert out["market_regime"]["availability"] == "unavailable"
    assert out["market_regime"]["confidence"] is None
    assert out["lex_summary"]["availability"] == "unavailable"
    assert out["portfolio_exposure"]["availability"] == "not_implemented"
    assert out["watchlist_changes"]["availability"] == "not_implemented"
    assert out["best_opportunity"] is None
    assert out["top_opportunities"] == []
    assert out["highest_conviction_short"] is None
    assert out["highest_conviction_long"] is None
    assert out["pending_approvals"] == {"total": 0, "high_conviction": 0, "needs_review": 0}


def test_builder_shapes_real_rows():
    futures = [{
        "generated_at": "2026-06-25T13:30:00Z",
        "regime": "risk_on", "regime_label": "Risk On", "confidence": 0.84,
        "payload": {
            "regime": {"regime": "risk_on", "label": "Risk On", "confidence": 84},
            "moves": [
                {"name": "S&P Futures", "symbol": "ES", "has_data": True, "net_move_pct": 0.68, "direction": "up"},
                {"name": "NASDAQ Futures", "symbol": "NQ", "has_data": True, "net_move_pct": 1.02, "direction": "up"},
                {"name": "Dead Feed", "symbol": "XX", "has_data": False, "net_move_pct": 0.0, "direction": "flat"},
            ],
        },
    }]
    briefings = [{
        "generated_at": "2026-06-25T13:31:00Z",
        "payload": {"broad_market_tone": "constructive", "major_indexes_sector_movement": "Tech leading.",
                    "themes": ["AI infrastructure"], "macro_risks": ["Inflation print tomorrow", "Bond auction"]},
    }]
    ideas = [
        {"id": 1, "ticker": "ORCL", "bias": "bullish", "confidence": 0.92, "timeframe": "swing",
         "status": "needs_review", "created_at": "2026-06-25T13:42:00Z"},
        {"id": 2, "ticker": "TSLA", "bias": "bearish", "confidence": 0.83, "timeframe": "intraday",
         "status": "new", "created_at": "2026-06-25T13:40:00Z"},
        {"id": 3, "ticker": "OLD", "bias": "bullish", "confidence": 0.50, "timeframe": "swing",
         "status": "rejected", "created_at": "2026-06-25T10:00:00Z"},  # filtered out
    ]
    pending = [{"idea_id": 1, "confidence": 0.92}, {"idea_id": 2, "confidence": 0.83}]

    out = build_review_briefing(
        safety={"scheduler_mode": "paper", "automation_paper_trading_armed": False},
        futures_snapshots=futures, market_briefings=briefings,
        ideas=ideas, pending_approvals=pending, now=NOW,
    )

    assert out["meta"]["safety_status"]["posture"] == "paper"
    assert out["meta"]["safety_status"]["label"] == "Paper · disarmed"

    regime = out["market_regime"]
    assert regime["availability"] == "available"
    assert regime["label"] == "RISK ON"
    assert regime["direction"] == "bullish"
    assert regime["confidence"] == 84
    assert [f["name"] for f in regime["futures"]] == ["S&P Futures", "NASDAQ Futures"]  # dead feed dropped
    assert regime["futures"][0]["value_text"] == "+0.68%"

    assert out["lex_summary"]["availability"] == "available"
    assert "constructive" in out["lex_summary"]["text"]

    # rejected idea filtered out; two reviewable ideas, sorted by conviction desc.
    cards = out["top_opportunities"]
    assert len(cards) == 2
    assert all(set(c.keys()) == CARD_KEYS for c in cards)
    assert cards[0]["ticker"] == "ORCL" and cards[0]["conviction_score"] == 92
    assert cards[0]["tier"] == "high_conviction"
    assert cards[0]["expected_move_text"] is None  # honest: not stored
    # watchlist action disabled + not_implemented, approve/reject enabled.
    by_action = {a["action"]: a for a in cards[0]["actions"]}
    assert by_action["watchlist"]["enabled"] is False
    assert by_action["watchlist"]["unavailable_reason"] == "not_implemented"
    assert by_action["approve"]["enabled"] is True

    assert out["best_opportunity"]["ticker"] == "ORCL"
    assert out["highest_conviction_long"]["ticker"] == "ORCL"
    assert out["highest_conviction_short"]["ticker"] == "TSLA"  # the bearish idea

    assert out["market_risks"] == [
        {"label": "Inflation print tomorrow", "severity": "unknown"},
        {"label": "Bond auction", "severity": "unknown"},
    ]
    assert out["pending_approvals"] == {"total": 2, "high_conviction": 2, "needs_review": 2}


def _snapshot_with_confidence(conf):
    return [{
        "generated_at": "2026-06-25T13:30:00Z",
        "regime": "risk_on", "confidence": conf,
        "payload": {"regime": {"regime": "risk_on", "label": "Risk On", "confidence": conf}, "moves": []},
    }]


def test_regime_confidence_fraction_is_scaled_to_100():
    out = build_review_briefing(
        safety=SAFE, futures_snapshots=_snapshot_with_confidence(0.84),
        market_briefings=[], ideas=[], pending_approvals=[], now=NOW,
    )
    assert out["market_regime"]["confidence"] == 84
    assert out["market_regime"]["confidence_text"] == "84% confidence"


def test_regime_confidence_already_scaled_is_kept():
    out = build_review_briefing(
        safety=SAFE, futures_snapshots=_snapshot_with_confidence(84),
        market_briefings=[], ideas=[], pending_approvals=[], now=NOW,
    )
    assert out["market_regime"]["confidence"] == 84
    # boundary: 1.0 is treated as a fraction -> 100; 1 (int) also -> 100
    out_one = build_review_briefing(
        safety=SAFE, futures_snapshots=_snapshot_with_confidence(1.0),
        market_briefings=[], ideas=[], pending_approvals=[], now=NOW,
    )
    assert out_one["market_regime"]["confidence"] == 100


def test_top_opportunities_capped_at_five_but_leaders_and_counts_use_full_set():
    ideas = []
    # 7 longs with descending confidence, plus 1 lower-conviction short.
    for n in range(7):
        ideas.append({"id": n + 1, "ticker": f"L{n}", "bias": "bullish",
                      "confidence": 0.95 - n * 0.05, "timeframe": "swing",
                      "status": "needs_review", "created_at": "2026-06-25T13:00:00Z"})
    ideas.append({"id": 99, "ticker": "SHORTY", "bias": "bearish", "confidence": 0.60,
                  "timeframe": "intraday", "status": "new", "created_at": "2026-06-25T13:00:00Z"})
    pending = [{"idea_id": i["id"], "confidence": i["confidence"]} for i in ideas]

    out = build_review_briefing(
        safety=SAFE, futures_snapshots=[], market_briefings=[],
        ideas=ideas, pending_approvals=pending, now=NOW,
    )
    # display capped at 5
    assert len(out["top_opportunities"]) == 5
    assert out["top_opportunities"][0]["ticker"] == "L0"
    # best_opportunity is the overall top card
    assert out["best_opportunity"]["ticker"] == "L0"
    # leaders consider the FULL reviewable set (SHORTY would be rank 8, beyond top 5)
    assert out["highest_conviction_long"]["ticker"] == "L0"
    assert out["highest_conviction_short"]["ticker"] == "SHORTY"
    # pending count reflects the full pending set, not the capped display
    assert out["pending_approvals"]["total"] == 8


def test_envelope_freshness_is_worst_case_oldest_section():
    # Regime snapshot is fresh (30 min old); briefing is stale (5 hrs old).
    fresh_snapshot = [{
        "generated_at": "2026-06-25T13:30:00Z",
        "payload": {"regime": {"regime": "risk_on", "label": "Risk On", "confidence": 80}, "moves": []},
    }]
    stale_briefing = [{
        "generated_at": "2026-06-25T09:00:00Z",
        "payload": {"broad_market_tone": "mixed", "themes": [], "macro_risks": []},
    }]
    out = build_review_briefing(
        safety=SAFE, futures_snapshots=fresh_snapshot, market_briefings=stale_briefing,
        ideas=[], pending_approvals=[], now=NOW,
    )
    fresh = out["meta"]["data_freshness"]
    # Envelope must reflect the OLDEST (briefing 09:00), not the fresher snapshot.
    assert fresh["as_of"] == "2026-06-25T09:00:00+00:00"
    assert fresh["is_stale"] is True
    assert fresh["level"] == "stale"
    # Section-level freshness still shows the regime as its own (fresher) value.
    assert out["market_regime"]["freshness"]["as_of"] == "2026-06-25T13:30:00+00:00"


def test_strategy_mapping():
    def strat(tf):
        ideas = [{"id": 1, "ticker": "X", "bias": "bullish", "confidence": 0.7,
                  "timeframe": tf, "status": "new", "created_at": "2026-06-25T13:00:00Z"}]
        out = build_review_briefing(safety=SAFE, futures_snapshots=[], market_briefings=[],
                                    ideas=ideas, pending_approvals=[], now=NOW)
        return out["top_opportunities"][0]["strategy"]

    assert strat("intraday") == "Day Trade"
    assert strat("swing") == "Swing"
    assert strat("position") == "LEAPS"
    assert strat("") == "Swing"
    assert strat(None) == "Swing"
    assert strat("weird-unknown") == "Swing"


def test_no_short_returns_null():
    ideas = [{"id": 9, "ticker": "AAA", "bias": "bullish", "confidence": 0.7, "timeframe": "swing",
              "status": "new", "created_at": "2026-06-25T13:00:00Z"}]
    out = build_review_briefing(
        safety=SAFE, futures_snapshots=[], market_briefings=[],
        ideas=ideas, pending_approvals=[], now=NOW,
    )
    assert out["highest_conviction_short"] is None  # graceful empty state
    assert out["highest_conviction_long"]["ticker"] == "AAA"


def test_endpoint_smoke_and_dashboard_unaffected(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "review.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    client = TestClient(create_app(lab))

    created = client.post("/api/ideas", json={
        "ticker": "NVDA", "bias": "bullish", "confidence": 0.82, "timeframe": "intraday",
        "thesis": "AI infrastructure momentum.", "source": "test",
        "timestamp": "2026-06-25T13:00:00Z", "strategy_tags": ["AI"],
    })
    assert created.status_code == 200

    res = client.get("/api/review/briefing")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == BRIEFING_KEYS
    assert body["meta"]["schema_version"] == "review.v1"
    assert body["meta"]["safety_status"]["reviewable"] is True
    # one reviewable idea -> one card with the full review.v1 card shape
    cards = body["top_opportunities"]
    assert len(cards) == 1
    assert set(cards[0].keys()) == CARD_KEYS
    assert cards[0]["ticker"] == "NVDA"
    assert cards[0]["actions"][2]["action"] == "watchlist"
    assert cards[0]["actions"][2]["enabled"] is False
    # honest unavailable states with no seeded regime/briefing/positions
    assert body["market_regime"]["availability"] == "unavailable"
    assert body["lex_summary"]["availability"] == "unavailable"
    assert body["portfolio_exposure"]["availability"] == "not_implemented"
    assert body["highest_conviction_short"] is None

    # Existing dashboard endpoint is unchanged and still serves.
    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    assert dash.json()["counts"]["ideas_today"] >= 1
