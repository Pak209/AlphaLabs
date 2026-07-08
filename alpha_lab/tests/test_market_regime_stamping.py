"""Public-path characterization of market-regime stamping (Phase 2 PR7).

Written BEFORE moving the repo-coupled context helpers so the contract is
pinned through the public surface, which survives the move untouched:
create_idea stamps market_regime from the latest saved briefing's
broad_market_tone (lowercased), and "unknown" when no briefing exists.
"""
from __future__ import annotations

from pathlib import Path

from alpha_lab.database import connect
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "regime.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def idea_payload(ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker, "bias": "bullish", "confidence": 0.8,
        "timeframe": "intraday", "thesis": "regime stamp test",
        "source": "test", "timestamp": "2026-07-08T14:00:00Z",
    }


def test_create_idea_stamps_unknown_without_briefing(tmp_path: Path):
    lab = service(tmp_path)
    idea = lab.create_idea(idea_payload())
    assert idea["market_regime"] == "unknown"


def test_create_idea_stamps_lowercased_briefing_tone(tmp_path: Path):
    lab = service(tmp_path)
    with connect(lab.db_path) as conn:
        AlphaLabRepository(conn).save_market_briefing({
            "brief_type": "daily_market_brief",
            "broad_market_tone": "Risk-On Watch",
            "generated_at": "2026-07-08T13:00:00Z",
        })
    idea = lab.create_idea(idea_payload("MSFT"))
    assert idea["market_regime"] == "risk-on watch"


def test_explicit_regime_wins_over_briefing(tmp_path: Path):
    lab = service(tmp_path)
    with connect(lab.db_path) as conn:
        AlphaLabRepository(conn).save_market_briefing({
            "brief_type": "daily_market_brief",
            "broad_market_tone": "Defensive",
            "generated_at": "2026-07-08T13:00:00Z",
        })
    idea = lab.create_idea({**idea_payload("AMD"), "market_regime": "custom-regime"})
    assert idea["market_regime"] == "custom-regime"
