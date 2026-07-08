"""Value-pin characterization of the scanner summary vocabulary (Phase 2 PR8).

These four builders emit the scanner_runs payload contract that downstream
readers parse — the waterfall's pre_idea_skips (candidates_found +
top_rejection_reasons), agent-status, and the crypto dashboard's signal_logs.
Exact-dict pins, written BEFORE the extraction and called through the service
methods, which keep one-line delegates (for Codex-conflict avoidance), so
these tests need no retargeting after the move.
"""
from __future__ import annotations

from pathlib import Path

from alpha_lab.market_data import CRYPTO_ALLOWLIST
from alpha_lab.service import AlphaLabService


def service(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "vocab.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def test_scanner_summary_sorts_caps_and_clamps(tmp_path: Path):
    summary = service(tmp_path)._scanner_summary(
        candidates_found=-3,            # clamped to 0
        ideas_persisted=2,
        rejected=7,
        skipped=4,
        reasons={"a": 3, "zero": 0, "b": 5, "c": 1, "d": 2, "e": 4, "f": 6},
        dry_run=True,
    )
    assert summary == {
        "status": "ok",
        "candidates_found": 0,
        "ideas_persisted": 2,
        "rejected": 7,
        "skipped": 4,
        # sorted desc by count, zero-count dropped, capped at five
        "top_rejection_reasons": [
            {"reason": "f", "count": 6},
            {"reason": "b", "count": 5},
            {"reason": "e", "count": 4},
            {"reason": "a", "count": 3},
            {"reason": "d", "count": 2},
        ],
        "dry_run": True,
        "note": "",
    }


def test_crypto_scanner_summary_composes_and_adds_safety_gates(tmp_path: Path):
    logs = [{"symbol": "BTC/USD", "safety_reason": "queued"}]
    summary = service(tmp_path)._crypto_scanner_summary(
        candidates_found=6, ideas_persisted=6, rejected=0, skipped=0,
        reasons={}, signal_logs=logs, note="ok",
    )
    assert summary["status"] == "ok" and summary["dry_run"] is True
    assert summary["note"] == "ok"
    assert summary["crypto_signal_logs"] is logs
    assert summary["allowlist"] == list(CRYPTO_ALLOWLIST)
    assert summary["cooldown_minutes"] == 30
    assert summary["max_simulated_crypto_ideas_per_day"] == 24
    assert summary["safety_gates"] == {
        "dry_run_only": True,
        "paper_orders_allowed": False,
        "no_shorts": True,
        "no_leverage": True,
        "duplicate_open_position_check": True,
        "per_symbol_cooldown": True,
        "max_simulated_crypto_ideas_per_day": 24,
    }


def test_crypto_signal_log_normalizes_and_prefers_catalyst(tmp_path: Path):
    lab = service(tmp_path)
    with_signal = lab._crypto_signal_log(
        "btcusd",
        signal={"catalyst": "24h vol spike", "reason": "thesis text", "timestamp": "2026-07-08T02:00:00Z"},
        reason="queued for dry-run simulation",
    )
    assert with_signal == {
        "symbol": "BTC/USD",
        "catalyst_or_technical_reason": "24h vol spike",
        "alpha_tier": None,
        "alpha_composite": None,
        "source_data_freshness": "2026-07-08T02:00:00Z",
        "paper_eligible": False,
        "paper_eligibility_reason": "queued for dry-run simulation",
        "safety_reason": "queued for dry-run simulation",
    }
    bare = lab._crypto_signal_log("eth-usd", reason="per-symbol cooldown active",
                                  freshness="2026-07-08T01:00:00Z")
    assert bare["symbol"] == "ETH/USD"
    assert bare["catalyst_or_technical_reason"] == "per-symbol cooldown active"
    assert bare["source_data_freshness"] == "2026-07-08T01:00:00Z"


def test_catalyst_source_accounting_counts_and_caps_problems(tmp_path: Path):
    payload = {
        "mode": "live",
        "live_status": {"providers": [
            {"name": "SEC EDGAR", "status": "ok"},
            {"name": "Polygon News", "status": "disabled", "reason": "no key"},
            {"name": "Tiingo News", "status": "error", "error": "HTTP 500"},
            "not-a-dict-ignored",
        ]},
        "catalysts": [{}, {}, {}],
        "signals": [{}],
    }
    accounting = service(tmp_path)._catalyst_source_accounting(payload)
    assert accounting == {
        "enabled": True,
        "requests_attempted": 3,
        "responses_received": 1,
        "raw_items": 3,
        "candidates_filtered": 2,
        "source_problems": ["Polygon News: no key", "Tiingo News: HTTP 500"],
    }
    sample = service(tmp_path)._catalyst_source_accounting({"mode": "sample", "catalysts": [], "signals": []})
    assert sample["enabled"] is False and sample["requests_attempted"] == 0
