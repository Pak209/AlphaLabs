from pathlib import Path

from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.performance import (
    build_performance_report,
    grade_for_return,
    grade_for_score,
    group_score,
)
from alpha_lab.service import AlphaLabService


def _row(idea_id, source, regime, percent_return, executed=True):
    return {
        "id": idea_id,
        "ticker": f"T{idea_id}",
        "bias": "bullish",
        "source": source,
        "market_regime": regime,
        "source_tags": [source],
        "status": "tested",
        "trade_status": "dry_run",
        "trade_id": idea_id if executed else None,
        "percent_return": percent_return if executed else None,
        "trade_explanation": {"thesis_summary": "summary"},
    }


def _evaluated_row(idea_id, source, regime, score, move_after_pct):
    row = _row(idea_id, source, regime, None, executed=False)
    row.update(
        {
            "early_detection_score": score,
            "signal_move_after_pct": move_after_pct,
            "signal_alert_price": 100.0,
            "signal_price_after": 100.0 + move_after_pct,
            "evaluation_status": "evaluated",
            "final_grade": "A" if score >= 85 else "B" if score >= 70 else "C",
        }
    )
    return row


def test_grade_bands():
    assert grade_for_return(6) == "A"
    assert grade_for_return(3) == "B"
    assert grade_for_return(0) == "C"
    assert grade_for_return(-3) == "D"
    assert grade_for_return(-9) == "F"
    assert grade_for_return(None) is None
    assert grade_for_score(None) is None
    assert grade_for_score(90) == "A"
    assert grade_for_score(10) == "F"


def test_group_score_blends_winrate_and_return():
    # All winners with a strong +10% avg should land near the top of the band.
    assert group_score(1.0, 10.0) == 100.0
    # All losers with a -10% avg should bottom out.
    assert group_score(0.0, -10.0) == 0.0


def test_report_accumulating_with_no_executed_signals():
    rows = [_row(1, "catalyst_radar", "mixed", None, executed=False)]
    report = build_performance_report(rows)
    assert report["report_card"]["overall_grade"] is None
    assert report["report_card"]["total_signals"] == 1
    assert report["report_card"]["executed_signals"] == 0
    assert report["report_card"]["evaluated_signals"] == 0
    assert report["alpha_iq"]["score"] is None
    assert report["alpha_iq"]["label"] == "Accumulating"
    assert report["recent_signals"][0]["grade"] is None


def test_report_grades_and_iq_with_executed_signals():
    rows = [
        _row(1, "catalyst_radar", "risk-on watch", 8.0),
        _row(2, "catalyst_radar", "risk-on watch", 4.0),
        _row(3, "daily_market_brief", "defensive", -6.0),
    ]
    report = build_performance_report(rows)
    card = report["report_card"]
    assert card["executed_signals"] == 3
    assert 0 < card["win_rate"] <= 1
    assert card["overall_grade"] in {"A", "B", "C", "D", "F"}

    sources = {g["name"]: g for g in report["source_leaderboard"]}
    assert sources["catalyst_radar"]["grade"] in {"A", "B"}  # two winners
    assert sources["daily_market_brief"]["grade"] in {"D", "F"}  # single loser

    iq = report["alpha_iq"]
    assert iq["score"] is not None
    # All three rows carry a known regime, so awareness should be full.
    assert iq["components"]["regime_awareness"] == 100.0

    # Per-signal grades surface in the recent feed.
    grades = {s["ticker"]: s["grade"] for s in report["recent_signals"]}
    assert grades["T1"] == "A"
    assert grades["T3"] == "F"


def test_report_uses_signal_evaluations_before_trade_returns():
    rows = [
        _evaluated_row(1, "catalyst_radar", "risk-on watch", 92.0, 7.5),
        _evaluated_row(2, "daily_market_brief", "defensive", 48.0, -1.2),
    ]
    report = build_performance_report(rows)
    card = report["report_card"]
    assert card["executed_signals"] == 0
    assert card["evaluated_signals"] == 2
    assert card["overall_grade"] == "B"
    assert card["avg_move_after_alert"] == 3.15
    assert report["alpha_iq"]["score"] is not None
    assert report["recent_signals"][0]["early_detection_score"] == 92.0


def test_alpha_iq_explainability_shows_futures_options_context():
    rows = [_evaluated_row(1, "catalyst_radar", "risk-on watch", 92.0, 7.5)]
    report = build_performance_report(
        rows,
        context={
            "futures": {"available": True, "regime": "risk_on", "latest_at": "2026-06-16 13:05:00"},
            "options": {"available": True, "samples": 3, "latest_at": "2026-06-16 13:12:00"},
        },
    )
    explain = report["alpha_iq"]["explainability"]
    assert explain["futures"]["affected_component"] == "regime_awareness"
    assert explain["options"]["affected_component"] is None
    assert "not enough samples" in explain["options"]["effect"]


def test_report_endpoint_stamps_source_and_regime(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "perf.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    client = TestClient(create_app(lab))
    created = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.82,
            "timeframe": "intraday",
            "thesis": "AI infrastructure momentum.",
            "source": "catalyst_radar",
            "timestamp": "2026-06-04T13:00:00Z",
        },
    )
    assert created.status_code == 200

    report = client.get("/api/performance/report").json()
    assert set(report.keys()) == {
        "report_card",
        "source_leaderboard",
        "regime_dashboard",
        "recent_signals",
        "alpha_iq",
    }
    recent = report["recent_signals"][0]
    assert recent["source"] == "catalyst_radar"
    assert recent["source_tags"]  # non-empty provenance tags
    assert recent["market_regime"] == "unknown"  # no briefing generated yet
    assert recent["evaluation_status"] == "provisional"
    assert "explainability" in report["alpha_iq"]


def test_signal_evaluation_endpoint_scores_without_trading(tmp_path: Path, monkeypatch):
    lab = AlphaLabService(
        db_path=str(tmp_path / "validation.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    prices = iter([100.0, 108.0])
    monkeypatch.setattr(lab, "_validation_price", lambda ticker: next(prices))
    client = TestClient(create_app(lab))
    created = client.post(
        "/api/ideas",
        json={
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.9,
            "timeframe": "intraday",
            "thesis": "AI infrastructure momentum.",
            "source": "catalyst_radar",
            "timestamp": "2026-06-04T13:00:00Z",
        },
    )
    assert created.status_code == 200

    result = client.post("/api/signals/evaluate", params={"limit": 1})
    assert result.status_code == 200
    assert result.json()["status_counts"]["evaluated"] == 1

    evaluations = client.get("/api/signals/evaluations").json()
    assert evaluations[0]["early_detection_score"] == 98.0
    assert evaluations[0]["final_grade"] == "A"

    report = client.get("/api/performance/report").json()
    assert report["report_card"]["evaluated_signals"] == 1
    assert report["recent_signals"][0]["grade"] == "A"
