from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha_lab.database import connect, init_db
from alpha_lab.source_coverage_report import build_report, render_markdown


def test_source_coverage_reads_scanner_runs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    db_path = str(tmp_path / "coverage.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scanner_runs (source, run_type, payload_json, created_at)
            VALUES ('options_flow', 'preview',
                    '{"requests_attempted": 3, "raw_items": 3, "candidates_found": 1, "ideas_persisted": 0, "rejected": 2, "top_rejection_reasons": [{"reason": "no options data", "count": 2}]}',
                    '2026-06-16 16:00:00')
            """
        )
        conn.commit()

    report = build_report(db_path, date(2026, 6, 16))
    options = next(row for row in report["rows"] if row["source"] == "Options Flow")
    assert options["enabled"] == "yes"
    assert options["requests"] == 3
    assert options["candidates"] == 1
    assert options["top_reason"] == "no options data: 2"
    assert "## Source Coverage" in render_markdown(report)


def test_source_coverage_flags_unscheduled_source(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    db_path = str(tmp_path / "coverage_empty.sqlite3")
    init_db(db_path)
    report = build_report(db_path, date(2026, 6, 16))
    sec = next(row for row in report["rows"] if row["source"] == "SEC EDGAR")
    assert sec["enabled"] == "no"
    assert "missing env var" in sec["problem"]
