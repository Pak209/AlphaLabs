from __future__ import annotations

from pathlib import Path

from alpha_lab.database import connect, init_db
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.strategy_attribution_audit import audit_strategy_attribution, main


def _idea_payload() -> dict:
    return {
        "ticker": "NVDA",
        "asset_type": "equity",
        "sector": "",
        "theme": "",
        "bias": "bullish",
        "confidence": 0.82,
        "timeframe": "intraday",
        "thesis": "AI infrastructure momentum with relative strength.",
        "catalyst": "unit catalyst",
        "source": "test",
        "timestamp": "2026-06-04T13:00:00Z",
        "strategies": ["AI bottleneck"],
        "source_tags": ["test"],
        "market_regime": "unknown",
    }


def test_strategy_attribution_audit_passes_for_tagged_idea_and_trade(tmp_path: Path):
    db_path = str(tmp_path / "strategy_ok.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        repo = AlphaLabRepository(conn)
        repo.seed_defaults()
        idea = repo.create_idea(_idea_payload())
        conn.execute(
            """
            INSERT INTO trades (idea_id, ticker, side, quantity, notional, status, dry_run)
            VALUES (?, 'NVDA', 'buy', 1, 100, 'dry_run', 1)
            """,
            (idea["id"],),
        )
        conn.commit()

    report = audit_strategy_attribution(db_path)

    assert report["status"] == "ok"
    assert report["read_only"] is True
    assert report["ideas_missing_strategy_labels"] == 0
    assert report["trades_missing_strategy_labels"] == 0


def test_strategy_attribution_audit_finds_missing_labels_without_backfill(tmp_path: Path):
    db_path = str(tmp_path / "strategy_gap.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, source, timestamp)
            VALUES ('MSFT', 'bullish', 0.8, 'intraday', 'manual idea', 'manual',
                    '2026-06-04T13:00:00Z')
            """
        )
        idea_id = conn.execute("SELECT id FROM alpha_ideas WHERE ticker = 'MSFT'").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO trades (idea_id, ticker, side, quantity, notional, status, dry_run)
            VALUES (?, 'MSFT', 'buy', 1, 100, 'dry_run', 1)
            """,
            (idea_id,),
        )
        conn.commit()

    report = audit_strategy_attribution(db_path)

    assert report["status"] == "needs_attention"
    assert report["ideas_missing_strategy_labels"] == 1
    assert report["trades_missing_strategy_labels"] == 1
    assert report["samples"]["ideas_missing_strategy_labels"][0]["ticker"] == "MSFT"

    second_report = audit_strategy_attribution(db_path)
    assert second_report["ideas_missing_strategy_labels"] == 1
    assert second_report["trades_missing_strategy_labels"] == 1


def test_strategy_attribution_audit_strict_exit_code(tmp_path: Path):
    db_path = str(tmp_path / "strategy_strict.sqlite3")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alpha_ideas
              (ticker, bias, confidence, timeframe, thesis, source, timestamp)
            VALUES ('MSFT', 'bullish', 0.8, 'intraday', 'manual idea', 'manual',
                    '2026-06-04T13:00:00Z')
            """
        )
        conn.commit()

    assert main(["--db", db_path, "--strict", "--json"]) == 1
