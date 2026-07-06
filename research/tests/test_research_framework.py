"""Tests for the research framework against a synthetic fixture database."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from research import metrics, telemetry
from research.run_experiment import load_spec, run
from research.tests.fixtures import THRESHOLD, build_fixture_db

SPEC_PATH = "research/experiments/EXP-0000-synthetic-sample.json"


@pytest.fixture()
def fixture_db(tmp_path):
    db_path = str(tmp_path / "fixture.sqlite3")
    expected = build_fixture_db(db_path)
    return db_path, expected


# ── metric math ──────────────────────────────────────────────────────────────

def test_wilson_interval_known_value():
    interval = metrics.wilson_interval(8, 10)
    assert interval["rate"] == 0.8
    assert interval["low"] == pytest.approx(0.4902, abs=1e-3)
    assert interval["high"] == pytest.approx(0.9433, abs=1e-3)
    assert metrics.wilson_interval(1, 0) is None


def test_signed_moves_credits_bearish_direction():
    # Bearish idea, price fell 3% while the market fell 1%: signed move +3,
    # excess +2, hit.
    labels = telemetry._signed_moves("bearish", -3.0, -1.0)
    assert labels == {"signed_move_pct": 3.0, "excess_move_pct": 2.0, "hit": 1}
    # Unevaluated rows label as None, never zero.
    assert telemetry._signed_moves("bullish", None, None)["hit"] is None


def test_spearman_monotone():
    assert metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert metrics.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0


# ── telemetry loaders ────────────────────────────────────────────────────────

def test_connect_readonly_rejects_writes_and_missing_files(fixture_db, tmp_path):
    db_path, _ = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO strategies (name) VALUES ('nope')")
    missing = tmp_path / "does-not-exist.sqlite3"
    with pytest.raises(FileNotFoundError):
        telemetry.connect_readonly(str(missing))
    assert not missing.exists()  # read-only access must never create the file


def test_idea_outcomes_frame(fixture_db):
    db_path, expected = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        frame = telemetry.load_idea_outcomes(conn)
    assert len(frame) == 36
    assert all(row["evaluated"] for row in frame)
    assert {row["session"] for row in frame} == {i["session"] for i in expected["ideas"]}
    by_id = {row["idea_id"]: row for row in frame}
    for idea in expected["ideas"]:
        assert by_id[idea["idea_id"]]["hit"] == (1 if idea["hit"] else 0)


def test_decision_outcomes_skips_legacy_and_attributes_first_failed(fixture_db):
    db_path, expected = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        frame = telemetry.load_decision_outcomes(conn)
    assert len(frame) == 18  # the legacy free-text row is excluded
    accepted = [r for r in frame if r["accepted"]]
    rejected = [r for r in frame if not r["accepted"]]
    assert len(accepted) == len(expected["accepted"])
    assert all(r["first_failed_gate"] == "confidence" for r in rejected)
    near_flags = [
        any(g["gate"] == "confidence" and g["near_miss"] for g in r["gates"])
        for r in rejected
    ]
    assert sum(near_flags) == len(expected["near"])


# ── battery on the fixture population ────────────────────────────────────────

def test_threshold_step_band_partition(fixture_db):
    db_path, expected = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        frame = telemetry.load_idea_outcomes(conn)
    result = metrics.threshold_step(frame, "confidence", THRESHOLD)
    counts = {name: result["bands"][name]["rows"] for name in ("below", "near_miss", "above")}
    expected_counts = {"below": 0, "near_miss": 0, "above": 0}
    for idea in expected["ideas"]:
        expected_counts[idea["band"]] += 1
    assert counts == expected_counts
    assert sum(counts.values()) == 36
    for name in counts:
        band_ideas = [i for i in expected["ideas"] if i["band"] == name]
        band_hits = sum(1 for i in band_ideas if i["hit"])
        assert result["bands"][name]["hit"]["rate"] == pytest.approx(
            band_hits / len(band_ideas), abs=1e-4)


def test_regret_analysis_groups(fixture_db):
    db_path, expected = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        frame = telemetry.load_decision_outcomes(conn)
    result = metrics.regret_analysis(frame, "confidence")
    assert result["accepted"]["rows"] == len(expected["accepted"])
    assert result["rejected_near_miss"]["rows"] == len(expected["near"])
    assert result["rejected_far"]["rows"] == len(expected["far"])
    assert result["regret_flag"] in (True, False)


def test_session_stability_counts_sessions(fixture_db):
    db_path, _ = fixture_db
    with telemetry.connect_readonly(db_path) as conn:
        frame = telemetry.load_idea_outcomes(conn)
    result = metrics.session_stability(frame)
    assert result["session_count"] == 6
    assert result["qualifying_sessions"] == 6


# ── runner end-to-end ────────────────────────────────────────────────────────

def test_run_experiment_emits_validation_report(fixture_db, tmp_path):
    db_path, _ = fixture_db
    out_dir = tmp_path / "validation"
    written = run(Path(SPEC_PATH), db_path=db_path, out_dir=out_dir)
    assert written["verdict"] == "READY_FOR_REVIEW"
    report = written["markdown"].read_text(encoding="utf-8")
    for section in ("Hypothesis (pre-registered)", "Sample gates",
                    "Analysis: threshold_step", "Analysis: regret", "Reproduction"):
        assert section in report
    data = json.loads(written["json"].read_text(encoding="utf-8"))
    assert data["meta"]["verdict"] == "READY_FOR_REVIEW"
    assert data["sample_gates"]["passed"] is True
    assert {r["analysis"] for r in data["results"]} == {
        "summary", "threshold_step", "buckets", "calibration",
        "session_stability", "regret"}


def test_run_experiment_insufficient_data_verdict(fixture_db, tmp_path):
    db_path, _ = fixture_db
    spec = json.loads(Path(SPEC_PATH).read_text(encoding="utf-8"))
    spec["sample_gates"]["min_rows"] = 10_000  # unreachable on the fixture
    strict = tmp_path / "strict-spec.json"
    strict.write_text(json.dumps(spec), encoding="utf-8")
    written = run(strict, db_path=db_path, out_dir=tmp_path / "validation")
    assert written["verdict"] == "INSUFFICIENT_DATA"


def test_spec_validation_rejects_incomplete_specs(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "EXP-9999", "title": "no fields"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fields"):
        load_spec(bad)
