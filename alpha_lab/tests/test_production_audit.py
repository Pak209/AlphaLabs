from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from alpha_lab.database import connect, init_db
from alpha_lab.production_audit import build_audit, data_reasons, to_kv

REPORT_DAY = date(2026, 6, 15)
TODAY_UTC = "2026-06-15 16:00:00"  # 09:00 PDT on the report day — inside the LA window
OPS_SCRIPT = Path(__file__).resolve().parents[2] / "ops"


@pytest.fixture(autouse=True)
def _clean_automation_env(monkeypatch):
    monkeypatch.delenv("ALPHALAB_SCHEDULER_MODE", raising=False)
    monkeypatch.delenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", raising=False)
    monkeypatch.delenv("ALPHA_LAB_DB_PATH", raising=False)


def _db(tmp_path: Path) -> str:
    path = str(tmp_path / "audit.sqlite3")
    init_db(path)
    return path


def _seed(db_path: str) -> None:
    with connect(db_path) as conn:
        # Polygon-sourced catalyst gathered today + SEC EDGAR gathered today.
        conn.execute(
            """
            INSERT INTO catalyst_events
              (ticker, catalyst_type, strategy_label, headline, source, published_at, discovered_at)
            VALUES
              ('AMZN', 'AI Partnership', 'momentum', 'AMZN cloud deal',
               'Polygon News / The Motley Fool', ?, ?)
            """,
            (TODAY_UTC, TODAY_UTC),
        )
        catalyst_id = conn.execute("SELECT id FROM catalyst_events").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO catalyst_events
              (ticker, catalyst_type, strategy_label, headline, source, published_at, discovered_at)
            VALUES
              ('NVDA', 'filing', 'event', 'NVDA filed 424B5 with the SEC',
               'SEC EDGAR submissions', ?, ?)
            """,
            (TODAY_UTC, TODAY_UTC),
        )
        # Idea generated today, linked to the Polygon catalyst.
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, catalyst, source, status,
               timestamp, source_tags, market_regime, catalyst_event_id, created_at)
            VALUES
              ('AMZN', 'bullish', 0.85, 'intraday', 'cloud deal', 'AI Partnership',
               'catalyst_radar', 'traded', ?, '["catalyst_radar"]', 'risk_on', ?, ?)
            """,
            (TODAY_UTC, catalyst_id, TODAY_UTC),
        )
        idea_id = conn.execute("SELECT id FROM alpha_ideas").fetchone()["id"]
        # One paper trade (dry_run=0) and one dry-run trade (dry_run=1), both today.
        conn.execute(
            "INSERT INTO trades (idea_id, ticker, side, status, dry_run, opened_at) "
            "VALUES (?, 'AMZN', 'buy', 'paper_open', 0, ?)",
            (idea_id, TODAY_UTC),
        )
        trade_id = conn.execute("SELECT id FROM trades").fetchone()["id"]
        conn.execute(
            "INSERT INTO trades (ticker, side, status, dry_run, opened_at) "
            "VALUES ('IWM', 'buy', 'dry_run', 1, ?)",
            (TODAY_UTC,),
        )
        # Paper order with a broker id, plus a reject in the execution audit.
        conn.execute(
            "INSERT INTO orders (trade_id, alpaca_order_id, ticker, side, payload_json, status, dry_run, created_at) "
            "VALUES (?, '3ba70426-800', 'AMZN', 'buy', '{}', 'submitted', 0, ?)",
            (trade_id, TODAY_UTC),
        )
        conn.execute(
            "INSERT INTO execution_audit (ticker, status, dry_run, created_at) "
            "VALUES ('TSLA', 'reject', 0, ?)",
            (TODAY_UTC,),
        )
        # Scanner runs: one healthy, one error payload.
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json, created_at) "
            "VALUES ('catalyst_radar', 'poll_live', '{\"status\": \"ok\"}', ?)",
            (TODAY_UTC,),
        )
        conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json, created_at) "
            "VALUES ('catalyst_radar', 'poll_live', '{\"status\": \"error\"}', ?)",
            (TODAY_UTC,),
        )
        conn.commit()


def test_empty_database_reports_no_ingestion(tmp_path: Path):
    audit = build_audit(_db(tmp_path), REPORT_DAY)
    assert audit["polygon"]["today"] == 0
    assert audit["sec"]["today"] == 0
    assert audit["ideas_today"] == 0
    assert audit["ideas_to_trades"] == []
    reasons = audit["data_reasons"]
    assert "Polygon gathered no alpha today" in reasons
    assert "SEC EDGAR gathered no alpha today" in reasons
    assert "no ideas generated today" in reasons


def test_detects_sources_trades_and_errors(tmp_path: Path):
    db_path = _db(tmp_path)
    _seed(db_path)
    audit = build_audit(db_path, REPORT_DAY)

    assert audit["polygon"]["today"] == 1
    assert audit["sec"]["today"] == 1
    assert audit["ideas_today"] == 1
    assert audit["paper_trades_today"] == 1
    assert audit["dry_run_trades_today"] == 1
    assert audit["paper_orders_today"] == 1
    assert audit["paper_orders_with_broker_id"] == 1
    assert audit["rejects_today"] == 1
    assert audit["scanner_errors_today"] == 1
    assert audit["catalyst_radar_runs_today"] == 2

    assert len(audit["ideas_to_trades"]) == 2
    paper = next(t for t in audit["ideas_to_trades"] if t["mode"] == "paper")
    assert paper["ticker"] == "AMZN"
    assert "Polygon" in paper["catalyst_source"]
    assert paper["broker_order"] is True


def test_to_kv_is_flat_and_parseable(tmp_path: Path):
    db_path = _db(tmp_path)
    _seed(db_path)
    lines = to_kv(build_audit(db_path, REPORT_DAY))
    blob = "\n".join(lines)
    assert "polygon_today=1" in blob
    assert "sec_today=1" in blob
    assert "paper_trades_today=1" in blob
    # every non-trade/non-reason line is a single key=value with no stray pipes
    for line in lines:
        assert "\n" not in line
        if not line.startswith(("trade=", "data_reason=")):
            assert "|" not in line


def test_automation_state_reflects_paper_arming(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "paper")
    monkeypatch.setenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "true")
    audit = build_audit(_db(tmp_path), REPORT_DAY)
    assert audit["automation"] == {
        "scheduler_mode": "paper",
        "paper_trades_armed": True,
        "paper_trades_can_trigger": True,
    }
    # paper mode + no trades today is a yellow-level reason
    assert any("paper mode" in r for r in audit["data_reasons"])


def test_missing_database_is_flagged(tmp_path: Path):
    audit = build_audit(str(tmp_path / "does_not_exist.sqlite3"), REPORT_DAY)
    assert audit["db_exists"] is False
    assert "error" in audit
    assert audit["data_reasons"] == ["database file not found at resolved path"]


def test_data_reasons_clear_when_healthy():
    audit = {
        "polygon": {"today": 3},
        "sec": {"today": 1},
        "ideas_today": 5,
        "scanner_errors_today": 0,
        "broker_unavailable_today": 0,
        "paper_trades_today": 2,
        "automation": {"scheduler_mode": "paper"},
    }
    assert data_reasons(audit) == []


def test_ops_script_passes_zsh_syntax_check():
    result = subprocess.run(
        ["zsh", "-n", str(OPS_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_ops_script_wires_production_audit_command():
    text = OPS_SCRIPT.read_text(encoding="utf-8")
    assert "production-audit)" in text
    assert "cmd_production_audit" in text
    assert "reports/production_audit" in text
