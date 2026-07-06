from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.replay import (
    BASELINE, ReplayScenario, build_replay_dataset, compare_to_baseline,
    load_scenarios_file, run_replay, run_scenario, score_row,
    spearman_rank_correlation,
)
from alpha_lab.scoring_engine import (
    CATALYST_TYPE_WEIGHTS, WEIGHTS, catalyst_type_weight, composite,
    score_catalyst, score_narrative, score_macro, score_price_volume,
)
from alpha_lab.scoring_models import CatalystInputs, MacroInputs, PriceVolumeInputs
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "replay.sqlite3"),
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
        "thesis": f"{ticker} replay test idea",
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
    lab = service(tmp_path)
    winner = make_idea(lab, "NVDA", "bullish", 0.82)          # +4% -> hit
    loser = make_idea(lab, "AMD", "bullish", 0.80)            # -2% -> miss
    short_win = make_idea(lab, "SMCI", "bearish", 0.78)       # -5% -> hit for a short
    make_idea(lab, "MSFT", "bullish", 0.76)                   # no outcome yet
    set_outcome(lab, winner["id"], 4.0)
    set_outcome(lab, loser["id"], -2.0)
    set_outcome(lab, short_win["id"], -5.0)
    return lab


# ─── engine parameterization stays default-identical ─────────────────────────

def test_overrides_default_to_live_behavior():
    inputs = CatalystInputs(catalyst_type="financing", gap_pct=2.0, materiality=70)
    assert score_catalyst(inputs) == score_catalyst(inputs, type_weights=None)
    assert catalyst_type_weight("financing") == CATALYST_TYPE_WEIGHTS["financing"]

    parts = dict(
        catalyst=score_catalyst(inputs),
        narrative=score_narrative(__import__("alpha_lab.scoring_engine", fromlist=["narrative_inputs_for_ticker"]).narrative_inputs_for_ticker("NVDA")),
        macro=score_macro(MacroInputs()),
        price_volume=score_price_volume(PriceVolumeInputs(bias="bullish")),
    )
    assert composite(**parts) == composite(**parts, weights=None,
                                           catalyst_confirm_min=None,
                                           price_volume_confirm_min=None)


def test_type_weight_override_changes_catalyst_score_only_for_that_type():
    inputs = CatalystInputs(catalyst_type="financing", materiality=70)
    live = score_catalyst(inputs)
    boosted = score_catalyst(inputs, type_weights={"financing": 85})
    assert boosted.score > live.score
    other = CatalystInputs(catalyst_type="contract", materiality=70)
    assert score_catalyst(other, type_weights={"financing": 85}) == score_catalyst(other)


def test_composite_weight_override_renormalizes():
    catalyst = score_catalyst(CatalystInputs(catalyst_type="contract", gap_pct=4.0, materiality=80))
    narrative = score_narrative(__import__("alpha_lab.scoring_engine", fromlist=["x"]).narrative_inputs_for_ticker("NVDA"))
    macro = score_macro(MacroInputs())
    pv = score_price_volume(PriceVolumeInputs(bias="bullish", relative_volume=2.5,
                                              gap_pct=4.0, trend_confirms=True))
    live = composite(catalyst, narrative, macro, price_volume=pv)
    tilted = composite(catalyst, narrative, macro, price_volume=pv,
                       weights={**WEIGHTS, "catalyst": 0.6, "price_volume": 0.2,
                                "narrative": 0.1, "macro": 0.1})
    assert tilted.composite_score != live.composite_score


# ─── spearman ─────────────────────────────────────────────────────────────────

def test_spearman_perfect_and_inverse_and_short():
    assert spearman_rank_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman_rank_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert spearman_rank_correlation([1, 2], [2, 1]) is None
    assert spearman_rank_correlation([1, 1, 1], [1, 2, 3]) is None


# ─── dataset + scenarios ──────────────────────────────────────────────────────

def test_dataset_builds_directional_outcomes(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    dataset = build_replay_dataset(lab.db_path)
    assert dataset["fingerprint"]["row_count"] == 4
    assert dataset["fingerprint"]["evaluated_count"] == 3
    by_ticker = {r["ticker"]: r for r in dataset["rows"]}
    assert by_ticker["NVDA"]["directional_move_pct"] == 4.0
    assert by_ticker["NVDA"]["hit"] is True
    # bearish idea: -5% market move is +5% directional
    assert by_ticker["SMCI"]["directional_move_pct"] == 5.0
    assert by_ticker["SMCI"]["hit"] is True
    assert by_ticker["MSFT"]["directional_move_pct"] is None


def test_replay_is_deterministic_and_read_only(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    with connect(lab.db_path) as conn:
        counts_before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("alpha_ideas", "trades", "execution_audit", "decision_logs")
        }
    dataset = build_replay_dataset(lab.db_path)
    first = run_scenario(dataset, BASELINE)
    second = run_scenario(dataset, BASELINE)
    assert first["metrics"] == second["metrics"]
    with connect(lab.db_path) as conn:
        counts_after = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("alpha_ideas", "trades", "execution_audit", "decision_logs")
        }
    assert counts_after == counts_before


def test_scenario_shifts_selection_and_compare_reports_it(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    dataset = build_replay_dataset(lab.db_path)
    baseline = run_scenario(dataset, BASELINE)
    # Lowering the composite bar in replay is an OFFLINE what-if — it changes
    # nothing live; it exists exactly so this question never has to be answered
    # by editing the real gate.
    permissive = run_scenario(dataset, ReplayScenario(
        name="composite-60", paper_composite_min=60.0, min_confidence=0.70,
    ))
    assert permissive["metrics"]["n_selected"] >= baseline["metrics"]["n_selected"]
    comparison = compare_to_baseline(baseline, permissive)
    assert comparison["selected_candidate"] >= comparison["selected_baseline"]
    assert comparison["newly_dropped"]["count"] == 0


def test_compare_rejects_mismatched_fingerprints(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    dataset = build_replay_dataset(lab.db_path)
    baseline = run_scenario(dataset, BASELINE)
    make_idea(lab, "META", "bullish", 0.9)
    other = run_scenario(build_replay_dataset(lab.db_path), BASELINE)
    try:
        compare_to_baseline(baseline, other)
        assert False, "expected fingerprint mismatch to raise"
    except ValueError as exc:
        assert "not comparable" in str(exc)


def test_feature_hook_supplies_candidate_inputs(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    dataset = build_replay_dataset(lab.db_path)

    def confirmed_pv_hook(row):
        return {"price_volume_inputs": PriceVolumeInputs(
            bias=row["bias"], relative_volume=3.5, gap_pct=4.0, trend_confirms=True)}

    hooked = ReplayScenario(name="pv-backfill", feature_hook=confirmed_pv_hook)
    baseline_rows = [score_row(r, BASELINE) for r in dataset["rows"]]
    hooked_rows = [score_row(r, hooked) for r in dataset["rows"]]
    assert all(r["pv_source"] == "feature_hook" for r in hooked_rows)
    assert sum(r["composite_score"] for r in hooked_rows) > sum(r["composite_score"] for r in baseline_rows)


def test_run_replay_report_shape_and_scenario_file(tmp_path: Path):
    lab = seeded_lab(tmp_path)
    scenario_file = tmp_path / "scenarios.json"
    scenario_file.write_text(
        '[{"name": "financing-45", "catalyst_type_weights": {"financing": 45}}]',
        encoding="utf-8",
    )
    scenarios = load_scenarios_file(str(scenario_file))
    report = run_replay(scenarios, db_path=lab.db_path)
    assert [r["scenario"]["name"] for r in report["results"]] == ["baseline", "financing-45"]
    assert report["comparisons"][0]["candidate"] == "financing-45"
    for result in report["results"]:
        assert "scored_rows" not in result
        assert result["fingerprint"] == report["fingerprint"]
        assert "calibration_bands" in result["metrics"]


def test_scenario_file_rejects_unknown_fields(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text('[{"name": "x", "watchlist_ceiling": 99}]', encoding="utf-8")
    try:
        load_scenarios_file(str(bad))
        assert False, "expected unknown-field rejection"
    except ValueError as exc:
        assert "unknown scenario fields" in str(exc)
