from __future__ import annotations

from datetime import date
from pathlib import Path

from alpha_lab.daily_activity_report import build_report, render_markdown, save_markdown
from alpha_lab.database import init_db, connect


REPORT_DAY = date(2026, 6, 15)
TODAY_UTC = "2026-06-15 16:00:00"


def _db(tmp_path: Path) -> str:
    path = str(tmp_path / "activity.sqlite3")
    init_db(path)
    return path


def test_daily_activity_report_runs_on_empty_database(tmp_path: Path):
    db_path = _db(tmp_path)
    report = build_report(db_path, REPORT_DAY)
    assert report["summary"]["ideas_generated_today"] == 0
    assert report["summary"]["orders_placed_today"] == 0
    assert "no ideas today" in render_markdown(report)


def test_daily_activity_report_detects_today_idea(tmp_path: Path):
    db_path = _db(tmp_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, catalyst, source, timestamp,
               source_tags, market_regime, created_at)
            VALUES
              ('NVDA', 'bullish', 0.84, 'intraday', 'AI momentum', 'product cycle',
               'catalyst_radar', '2026-06-15T16:00:00Z', '["catalyst_radar"]',
               'risk-on watch', ?)
            """,
            (TODAY_UTC,),
        )
        idea_id = conn.execute("SELECT id FROM alpha_ideas").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO signal_evaluations
              (idea_id, ticker, source, source_tags, generated_at, evaluated_at,
               direction, confidence, market_regime, alert_price, price_after,
               move_after_pct, early_detection_score, provisional_grade, final_grade, status)
            VALUES
              (?, 'NVDA', 'catalyst_radar', '["catalyst_radar"]', ?, ?,
               'bullish', 0.84, 'risk-on watch', 100, 106, 6.0, 88.0, 'C', 'A', 'evaluated')
            """,
            (idea_id, TODAY_UTC, TODAY_UTC),
        )
        conn.commit()

    report = build_report(db_path, REPORT_DAY)
    assert report["summary"]["ideas_generated_today"] == 1
    assert report["summary"]["signals_evaluated_today"] == 1
    assert report["ideas"][0]["ticker"] == "NVDA"
    assert report["ideas"][0]["grade"] == "A"


def test_daily_activity_report_shows_scanner_run_counts(tmp_path: Path):
    db_path = _db(tmp_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scanner_runs (source, run_type, payload_json, created_at)
            VALUES ('catalyst_radar', 'poll_live',
                    '{"candidates_found": 18, "ideas_persisted": 2, "rejected": 16, "top_rejection_reasons": [{"reason": "not trade candidate", "count": 16}]}',
                    ?)
            """,
            (TODAY_UTC,),
        )
        conn.commit()

    report = build_report(db_path, REPORT_DAY)
    assert report["summary"]["scanners_ran"] == 1
    assert report["summary"]["candidates_found"] == 18
    markdown = render_markdown(report)
    assert "## Scanner Runs" in markdown
    assert "| catalyst_radar | yes | 18 | 2 | 16 | not trade candidate: 16 |" in markdown


def test_daily_activity_report_warns_scanner_candidates_without_ideas(tmp_path: Path):
    db_path = _db(tmp_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scanner_runs (source, run_type, payload_json, created_at)
            VALUES ('daily_market_brief', 'import_and_test',
                    '{"candidates_found": 4, "ideas_persisted": 0, "rejected": 4}',
                    ?)
            """,
            (TODAY_UTC,),
        )
        conn.commit()

    report = build_report(db_path, REPORT_DAY)
    assert any("persisted zero ideas" in warning for warning in report["warnings"])


def test_daily_activity_report_detects_paper_orders_and_missing_audit(tmp_path: Path):
    db_path = _db(tmp_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, catalyst, source, timestamp,
               source_tags, market_regime, created_at)
            VALUES ('AAPL', 'bullish', 0.8, 'intraday', 'thesis', 'catalyst',
                    'manual', '2026-06-15T16:00:00Z', '["manual"]', 'unknown', ?)
            """,
            (TODAY_UTC,),
        )
        idea_id = conn.execute("SELECT id FROM alpha_ideas").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO trades (idea_id, ticker, side, quantity, notional, status, dry_run, opened_at)
            VALUES (?, 'AAPL', 'buy', 1, 10, 'paper_open', 0, ?)
            """,
            (idea_id, TODAY_UTC),
        )
        trade_id = conn.execute("SELECT id FROM trades").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO orders (trade_id, alpaca_order_id, ticker, side, payload_json, status, dry_run, created_at)
            VALUES (?, 'paper-1', 'AAPL', 'buy', '{}', 'submitted', 0, ?)
            """,
            (trade_id, TODAY_UTC),
        )
        conn.commit()

    report = build_report(db_path, REPORT_DAY)
    assert report["summary"]["paper_orders_today"] == 1
    assert report["summary"]["paper_orders_missing_audit"] == 1
    assert any("has no matching execution audit" in warning for warning in report["warnings"])


def test_daily_activity_report_flags_live_order_path(tmp_path: Path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://api.alpaca.markets")
    report = build_report(db_path, REPORT_DAY)
    assert report["summary"]["live_order_path_present"] is True
    assert any("live order path" in warning for warning in report["warnings"])


def test_daily_activity_report_saves_markdown(tmp_path: Path):
    db_path = _db(tmp_path)
    report = build_report(db_path, REPORT_DAY)
    path = save_markdown(report, str(tmp_path / "reports"))
    assert path.name == "2026-06-15-alpha-activity.md"
    assert path.exists()


def test_daily_activity_report_does_not_import_broker_client():
    import sys

    sys.modules.pop("paper_trader.alpaca_client", None)
    __import__("alpha_lab.daily_activity_report")
    assert "paper_trader.alpaca_client" not in sys.modules
