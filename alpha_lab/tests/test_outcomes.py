from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.outcomes import (
    build_outcome_rows, near_miss_report, outcome_report,
)
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "outcomes.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def make_idea(lab: AlphaLabService, ticker: str, bias: str, confidence: float,
              source: str = "test", catalyst_type: str = "Government Contract"):
    return lab.create_idea({
        "ticker": ticker,
        "bias": bias,
        "confidence": confidence,
        "timeframe": "intraday",
        "thesis": f"{ticker} outcome test idea",
        "catalyst": "major contract awarded",
        "catalyst_type": catalyst_type,
        "catalyst_score": 75,
        "source": source,
        "timestamp": "2026-06-22T14:00:00Z",
    })


def set_outcome(lab: AlphaLabService, idea_id: int, move_after_pct: float):
    with connect(lab.db_path) as conn:
        conn.execute(
            "UPDATE signal_evaluations SET move_after_pct=?, status='evaluated', "
            "early_detection_score=50 WHERE idea_id=?",
            (move_after_pct, idea_id),
        )
        conn.commit()


def seeded_lab(tmp_path: Path) -> AlphaLabService:
    """Three populations: accepted winner, hard-rejected loser, near-miss winner."""
    lab = service(tmp_path)

    accepted = make_idea(lab, "NVDA", "bullish", 0.85, source="catalyst_radar")
    lab.place_trade(accepted["id"], dry_run=True)           # accepted -> status tested
    set_outcome(lab, accepted["id"], 3.0)

    hard_reject = make_idea(lab, "AMD", "bullish", 0.50, source="daily_market_brief",
                            catalyst_type="Financing Event")
    lab.place_trade(hard_reject["id"], dry_run=True)        # confidence 0.50: not a near-miss
    set_outcome(lab, hard_reject["id"], -2.0)

    near_miss = make_idea(lab, "MSFT", "bullish", 0.72, source="catalyst_radar")
    lab.place_trade(near_miss["id"], dry_run=True)          # 0.72 vs 0.75 -> near-miss
    set_outcome(lab, near_miss["id"], 4.0)

    make_idea(lab, "META", "bearish", 0.80, source="futures_pulse")  # never tested, no outcome
    return lab


def test_outcome_rows_carry_status_and_gate_info(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, fingerprint = build_outcome_rows(lab.db_path)
    assert fingerprint["row_count"] == 4
    by_ticker = {r["ticker"]: r for r in rows}

    assert by_ticker["NVDA"]["accepted"] is True
    assert by_ticker["NVDA"]["first_failed_gate"] is None

    assert by_ticker["AMD"]["rejected"] is True
    assert by_ticker["AMD"]["first_failed_gate"] == "confidence"
    assert by_ticker["AMD"]["near_missed_gates"] == []      # 0.50 misses by far

    msft = by_ticker["MSFT"]
    assert msft["rejected"] is True
    assert [m["gate"] for m in msft["near_missed_gates"]] == ["confidence"]
    assert abs(msft["near_missed_gates"][0]["shortfall"] - 0.03) < 1e-9

    assert by_ticker["META"]["accepted"] is False and by_ticker["META"]["rejected"] is False


def test_near_miss_report_flags_strict_margin(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, _ = build_outcome_rows(lab.db_path)
    report = near_miss_report(rows)
    assert report["accepted_reference"]["n_ideas"] == 1
    gate = next(g for g in report["gates"] if g["gate"] == "confidence")
    assert gate["n_near_miss"] == 1
    assert gate["avg_move_pct"] == 4.0
    # near-miss (4%) beat accepted (3%) -> the strict-at-the-margin verdict
    assert "strict at the margin" in gate["verdict_vs_accepted"]
    assert gate["examples"][0]["ticker"] == "MSFT"


def test_report_sections_and_groupings(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    report = outcome_report(lab.db_path)

    assert report["overall"]["n_ideas"] == 4
    assert report["overall"]["n_with_outcome"] == 3
    assert report["overall"]["status_counts"]["rejected"] == 2

    sources = {g["group"] for g in report["by_source"]}
    assert {"catalyst_radar", "daily_market_brief", "futures_pulse"} <= sources
    radar = next(g for g in report["by_source"] if g["group"] == "catalyst_radar")
    assert radar["n_ideas"] == 2 and radar["hit_rate"] == 1.0

    types = {g["group"] for g in report["by_catalyst_type"]}
    assert "government contract" in types and "financing event" in types

    avr = report["accepted_vs_rejected"]
    assert avr["accepted"]["n_ideas"] == 1 and avr["rejected"]["n_ideas"] == 2
    # accepted +3.0 vs rejected avg (+4.0 - 2.0)/2 = +1.0 -> edge +2.0
    assert avr["acceptance_edge_pct"] == 2.0
    assert avr["other"]["n_ideas"] == 1

    gate_groups = {g["group"] for g in report["by_gate_result"]}
    assert "accepted (no failed gate)" in gate_groups and "confidence" in gate_groups

    conf_bands = {b["band"]: b for b in report["score_bands"]["confidence"]}
    assert conf_bands["0.7-0.75"]["n_ideas"] == 1          # the near-miss
    assert conf_bands["0.75-0.85"]["n_ideas"] == 1         # the bearish untested idea (0.80)
    composite_bands = report["score_bands"]["replay_composite"]
    assert sum(b["n_ideas"] for b in composite_bands) == 4


def test_report_deterministic_and_read_only(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    with connect(lab.db_path) as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("alpha_ideas", "trades", "execution_audit", "decision_logs")}
    first = outcome_report(lab.db_path)
    second = outcome_report(lab.db_path)
    assert first == second
    with connect(lab.db_path) as conn:
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("alpha_ideas", "trades", "execution_audit", "decision_logs")}
    assert after == before


def test_cli_prints_and_writes(tmp_path: Path, capsys):
    from scripts.outcome_report import print_report, write_report

    lab = seeded_lab(tmp_path)
    report = outcome_report(lab.db_path)
    path = write_report(report, tmp_path / "reports")
    assert path.exists()
    print_report(report)
    output = capsys.readouterr().out
    assert "near-miss performance" in output
    assert "accepted vs rejected" in output
    assert "by gate result" in output
