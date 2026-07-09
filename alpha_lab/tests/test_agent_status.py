from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from alpha_lab.agent_status import build_agent_status
from alpha_lab.api import create_app
from alpha_lab.database import connect, init_db
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService


def test_agent_status_builds_recent_scanner_run_rows(tmp_path: Path):
    db_path = str(tmp_path / "agent_status.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (
                "catalyst_radar",
                "scheduled_poll",
                json.dumps(
                    {
                        "status": "ok",
                        "started_at": "2026-06-17T13:00:00Z",
                        "finished_at": "2026-06-17T13:00:02Z",
                        "ideas_persisted": 2,
                        "duration_ms": 2000,
                        "dry_run": True,
                    }
                ),
                "2026-06-17 13:00:02",
            ),
        )
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (
                "daily_market_brief",
                "scheduled_import",
                json.dumps({"status": "error", "error_message": "provider unavailable"}),
                "2026-06-17 13:01:00",
            ),
        )
        conn.commit()

    report = build_agent_status(db_path, limit=10)

    assert report["read_only"] is True
    assert report["status"] == "needs_attention"
    assert report["scheduler_job_count"] == 19
    assert len(report["scanner_runs"]) == 2
    latest = report["scanner_runs"][0]
    assert latest["agent"] == "daily_market_brief"
    assert latest["status"] == "error"
    assert latest["error_message"] == "provider unavailable"
    prior = report["scanner_runs"][1]
    assert prior["items_created"] == 2
    assert prior["duration_ms"] == 2000
    assert prior["dry_run"] is True


def test_agent_status_endpoint_is_read_only(tmp_path: Path):
    lab = AlphaLabService(
        db_path=str(tmp_path / "api_agent_status.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit_agent_status.jsonl"),
    )
    with connect(lab.db_path) as conn:
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json) VALUES (?, ?, ?)",
            ("runtime_path_smoke_test", "verification", json.dumps({"timestamp": "2026-06-17T13:00:00Z"})),
        )
        conn.commit()
    client = TestClient(create_app(lab))

    response = client.get("/api/ops/agent-status?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is True
    assert body["scanner_runs"][0]["agent"] == "runtime_path_smoke_test"
    assert body["scanner_runs"][0]["last_started_at"] == "2026-06-17T13:00:00Z"
    assert body["scanner_runs"][0]["duration_ms"] is None


def test_scanner_run_preserves_timing_fields_for_agent_status(tmp_path: Path):
    db_path = str(tmp_path / "scanner_timing.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        repo = AlphaLabRepository(conn)
        repo.log_scanner_run(
            "catalyst_radar",
            "scheduled_poll",
            {
                "status": "ok",
                "started_at": "2026-06-17T13:00:00Z",
                "finished_at": "2026-06-17T13:00:03Z",
                "duration_ms": 3000,
                "items_created": 4,
                "error_message": "",
                "secretish_extra": "must not persist",
            },
        )
        row = repo.list_scanner_runs(1)[0]

    assert row["payload"]["started_at"] == "2026-06-17T13:00:00Z"
    assert row["payload"]["finished_at"] == "2026-06-17T13:00:03Z"
    assert row["payload"]["duration_ms"] == 3000
    assert row["payload"]["items_created"] == 4
    assert "secretish_extra" not in row["payload"]
