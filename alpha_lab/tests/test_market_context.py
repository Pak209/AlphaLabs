"""Unit tests for the self-free market-context helpers (Phase 2 PR6).

These arrive WITH the module (they could not precede it): the session clock
becomes testable for the first time via the injectable ``now``, and the
error-envelope wrapper gets direct cases. The quote-chain fallback order is
covered by the retargeted test in test_price_volume_feed.py.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alpha_lab.market_context import regular_equity_session_open, safe_market_payload

ET = ZoneInfo("America/New_York")


def et(weekday_date: str, hh: int, mm: int) -> datetime:
    return datetime.fromisoformat(f"{weekday_date}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET)


def test_session_boundaries_on_a_weekday():
    # 2026-07-08 is a Wednesday.
    assert regular_equity_session_open(et("2026-07-08", 9, 29)) is False
    assert regular_equity_session_open(et("2026-07-08", 9, 30)) is True
    assert regular_equity_session_open(et("2026-07-08", 12, 0)) is True
    assert regular_equity_session_open(et("2026-07-08", 15, 59)) is True
    assert regular_equity_session_open(et("2026-07-08", 16, 0)) is False


def test_session_closed_all_weekend():
    # 2026-07-11/12 are Saturday/Sunday — closed even at midday.
    assert regular_equity_session_open(et("2026-07-11", 12, 0)) is False
    assert regular_equity_session_open(et("2026-07-12", 12, 0)) is False


def test_session_no_arg_reads_real_clock():
    assert regular_equity_session_open() in (True, False)   # smoke: no-arg path works


def test_safe_market_payload_passes_through_success():
    assert safe_market_payload(lambda: {"status": "ok", "price": 1.0}) == {"status": "ok", "price": 1.0}


def test_safe_market_payload_wraps_exceptions():
    def boom():
        raise RuntimeError("feed down")

    result = safe_market_payload(boom)
    assert result == {"status": "unavailable", "error": "feed down"}


# ─── repo-coupled tier (Phase 2 PR7) ─────────────────────────────────────────

def test_current_market_regime_reads_latest_briefing(tmp_path):
    from pathlib import Path

    from alpha_lab.database import connect, init_db
    from alpha_lab.market_context import current_market_regime
    from alpha_lab.repository import AlphaLabRepository

    db = str(Path(tmp_path) / "regime.sqlite3")
    init_db(db)
    with connect(db) as conn:
        repo = AlphaLabRepository(conn)
        assert current_market_regime(repo) == "unknown"        # no briefing yet
        repo.save_market_briefing({"brief_type": "daily_market_brief",
                                   "broad_market_tone": "Defensive",
                                   "generated_at": "2026-07-08T13:00:00Z"})
        assert current_market_regime(repo) == "defensive"      # lowercased tone


def test_current_market_regime_unknown_fail_safe():
    from alpha_lab.market_context import current_market_regime

    class BrokenRepo:
        def list_market_briefings(self, limit):
            raise RuntimeError("db locked")

    # Load-bearing behavior: a regime read must never block idea creation.
    assert current_market_regime(BrokenRepo()) == "unknown"


def test_latest_briefing_context_empty_and_populated(tmp_path):
    from pathlib import Path

    from alpha_lab.database import connect, init_db
    from alpha_lab.market_context import latest_briefing_context
    from alpha_lab.repository import AlphaLabRepository

    db = str(Path(tmp_path) / "context.sqlite3")
    init_db(db)
    with connect(db) as conn:
        assert latest_briefing_context(conn) == {}
        AlphaLabRepository(conn).save_market_briefing({
            "brief_type": "daily_market_brief",
            "broad_market_tone": "Risk-On Watch",
            "generated_at": "2026-07-08T13:00:00Z",
        })
        assert latest_briefing_context(conn) == {
            "headline": "Risk-On Watch",
            "market_context": "Risk-On Watch",
            "source": "stored_market_briefing",
            "generated_at": "2026-07-08T13:00:00Z",
        }
