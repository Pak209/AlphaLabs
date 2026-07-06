from pathlib import Path

from alpha_lab.attribution import (
    categorical_feature_report, feature_attribution_report, gate_regret_report,
    numeric_feature_report, selected_vs_rejected_report, _attribution_rows,
)
from alpha_lab.database import connect
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "attr.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def make_idea(lab: AlphaLabService, ticker: str, bias: str, confidence: float,
              catalyst_type: str = "Financing Event", catalyst_score: int = 70):
    return lab.create_idea({
        "ticker": ticker,
        "bias": bias,
        "confidence": confidence,
        "timeframe": "intraday",
        "thesis": f"{ticker} attribution test idea",
        "catalyst": "registered direct offering announced",
        "catalyst_type": catalyst_type,
        "catalyst_score": catalyst_score,
        "source": "test",
        "timestamp": "2026-06-20T14:00:00Z",
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
    """High-confidence winners, low-confidence losers -> confidence should rank."""
    lab = service(tmp_path)
    spec = [
        ("NVDA", "bullish", 0.90, 5.0, "Government Contract", 85),
        ("MSFT", "bullish", 0.85, 3.0, "Government Contract", 80),
        ("AMD", "bullish", 0.62, -2.0, "Financing Event", 45),
        ("META", "bullish", 0.58, -3.0, "Financing Event", 40),
        ("SMCI", "bearish", 0.80, -4.0, "Earnings Revision", 75),   # short winner
        ("TSLA", "bullish", 0.60, -1.0, "Financing Event", 42),
    ]
    for ticker, bias, confidence, move, ctype, cscore in spec:
        idea = make_idea(lab, ticker, bias, confidence, ctype, cscore)
        set_outcome(lab, idea["id"], move)
    return lab


def test_numeric_report_ranks_confidence_positively(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, fingerprint = _attribution_rows(lab.db_path)
    assert fingerprint["evaluated_count"] == 6
    report = numeric_feature_report(rows, "confidence")
    assert report["dead_input"] is False
    assert report["spearman"] is not None and report["spearman"] > 0.5
    split = report["median_split"]
    assert split["top_half"]["hit_rate"] > split["bottom_half"]["hit_rate"]
    assert split["avg_move_delta_pct"] > 0


def test_dead_inputs_flagged_not_correlated(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, _ = _attribution_rows(lab.db_path)
    # novelty is constant 100 while prior_count_30d is unwired; macro is
    # constant at decision-time defaults — both must surface as dead inputs.
    novelty = numeric_feature_report(rows, "sub_novelty")
    macro = numeric_feature_report(rows, "component_macro")
    assert novelty["dead_input"] is True and novelty["constant_value"] == 100.0
    assert macro["dead_input"] is True
    assert novelty["spearman"] is None


def test_categorical_report_pools_small_groups(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, _ = _attribution_rows(lab.db_path)
    report = categorical_feature_report(rows, "catalyst_type")
    levels = {l["level"] for l in report["levels"]}
    assert "financing event" in levels          # n=3 meets the floor
    assert "earnings revision" not in levels    # n=1 pooled
    assert report["small_groups_pooled_n"] >= 1


def test_selected_vs_rejected_gaps_present(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, _ = _attribution_rows(lab.db_path)
    # With neutral PV reconstruction nothing clears the 70 bar yet, so both
    # populations only exist once real PV data accrues. Exercise the contract
    # directly: selection flags in, per-feature distribution gaps out.
    for r in rows:
        r["selected"] = r["confidence"] >= 0.80
    report = selected_vs_rejected_report(rows)
    assert report["n_selected"] == 3 and report["n_rejected"] == 3
    gaps = {g["feature"]: g for g in report["feature_gaps"]}
    assert gaps["confidence"]["selection_gap"] > 0
    assert "replay_composite" in gaps
    assert report["selected_outcomes"]["hit_rate"] > report["rejected_outcomes"]["hit_rate"]


def test_selected_vs_rejected_handles_empty_side(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    rows, _ = _attribution_rows(lab.db_path)
    report = selected_vs_rejected_report(rows)
    assert report["n_selected"] == 0            # neutral-PV era: nothing clears 70
    assert report["feature_gaps"] == []          # gaps undefined with an empty side


def test_gate_regret_links_rejections_to_outcomes(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    # A rejected-by-confidence idea that then went on to WIN -> regret at the
    # confidence gate. place_trade(dry_run) writes the structured gate trace.
    winner_rejected = make_idea(lab, "GOOGL", "bullish", 0.55)
    lab.place_trade(winner_rejected["id"], dry_run=True)
    set_outcome(lab, winner_rejected["id"], 6.0)

    report = gate_regret_report(lab.db_path)
    assert report["structured_ideas"] >= 1
    confidence_gate = next(g for g in report["gates"] if g["gate"] == "confidence")
    assert confidence_gate["n_rejected"] >= 1
    assert confidence_gate["regret_rate"] == 1.0
    assert confidence_gate["avg_missed_move_pct"] == 6.0


def test_full_report_shape_deterministic_read_only(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    with connect(lab.db_path) as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("alpha_ideas", "trades", "execution_audit", "decision_logs")}
    first = feature_attribution_report(lab.db_path)
    second = feature_attribution_report(lab.db_path)
    assert first == second
    with connect(lab.db_path) as conn:
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("alpha_ideas", "trades", "execution_audit", "decision_logs")}
    assert after == before

    assert first["fingerprint"]["row_count"] == 6
    ranked = [r["feature"] for r in first["importance_ranking"]]
    assert "confidence" in ranked
    assert "sub_novelty" in first["dead_inputs"]
    assert {c["feature"] for c in first["categorical_features"]} >= {"catalyst_type", "source", "bias"}
    assert first["caveats"]


def test_report_file_written(tmp_path: Path, capsys):
    from scripts.feature_attribution import print_report, write_report

    lab = seeded_lab(tmp_path)
    report = feature_attribution_report(lab.db_path)
    path = write_report(report, tmp_path / "reports")
    assert path.exists()
    print_report(report)
    output = capsys.readouterr().out
    assert "feature importance" in output
    assert "dead inputs" in output
