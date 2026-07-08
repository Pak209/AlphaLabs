"""
alpha_lab/scanning.py — the scanner summary vocabulary (pure builders).

Extracted verbatim from AlphaLabService (Phase 2 PR8, docs/PHASE2_PLAN.md):
Tier A of the scanning cluster. These four builders emit the scanner_runs
payload contract that downstream readers parse — the rejection waterfall's
pre-idea stage (candidates_found, top_rejection_reasons), agent-status, and
the crypto dashboard's signal_logs. Shapes are value-pinned by
tests/test_scanning_vocabulary.py.

The service keeps one-line delegates for all four — not because anything
monkeypatches them (nothing does) but so the Codex-active poll bodies stay
byte-untouched by the extraction (zero merge surface). The cooldown/cap
constants live here as the single source of truth; the service class
attributes reference them for the Tier-B DB accessors that still use self.
"""
from __future__ import annotations

from typing import Any

from .market_data import CRYPTO_ALLOWLIST, normalize_crypto_symbol

CRYPTO_SCAN_COOLDOWN_MINUTES = 30
MAX_SIMULATED_CRYPTO_IDEAS_PER_DAY = 24


def scanner_summary(
    *,
    candidates_found: int,
    ideas_persisted: int,
    rejected: int,
    skipped: int,
    reasons: dict[str, int],
    dry_run: bool,
    note: str = "",
) -> dict[str, Any]:
    top_reasons = [
        {"reason": reason, "count": int(count)}
        for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True)
        if int(count) > 0
    ][:5]
    return {
        "status": "ok",
        "candidates_found": max(0, int(candidates_found)),
        "ideas_persisted": max(0, int(ideas_persisted)),
        "rejected": max(0, int(rejected)),
        "skipped": max(0, int(skipped)),
        "top_rejection_reasons": top_reasons,
        "dry_run": dry_run,
        "note": note,
    }


def crypto_scanner_summary(
    *,
    candidates_found: int,
    ideas_persisted: int,
    rejected: int,
    skipped: int,
    reasons: dict[str, int],
    signal_logs: list[dict[str, Any]],
    note: str = "",
) -> dict[str, Any]:
    summary = scanner_summary(
        candidates_found=candidates_found,
        ideas_persisted=ideas_persisted,
        rejected=rejected,
        skipped=skipped,
        reasons=reasons,
        dry_run=True,
        note=note,
    )
    summary.update(
        {
            "crypto_signal_logs": signal_logs,
            "allowlist": list(CRYPTO_ALLOWLIST),
            "cooldown_minutes": CRYPTO_SCAN_COOLDOWN_MINUTES,
            "max_simulated_crypto_ideas_per_day": MAX_SIMULATED_CRYPTO_IDEAS_PER_DAY,
            "safety_gates": {
                "dry_run_only": True,
                "paper_orders_allowed": False,
                "no_shorts": True,
                "no_leverage": True,
                "duplicate_open_position_check": True,
                "per_symbol_cooldown": True,
                "max_simulated_crypto_ideas_per_day": MAX_SIMULATED_CRYPTO_IDEAS_PER_DAY,
            },
        }
    )
    return summary


def crypto_signal_log(
    symbol: str,
    *,
    signal: dict[str, Any] | None = None,
    reason: str,
    freshness: str | None = None,
) -> dict[str, Any]:
    signal = signal or {}
    return {
        "symbol": normalize_crypto_symbol(symbol),
        "catalyst_or_technical_reason": signal.get("catalyst") or signal.get("reason") or reason,
        "alpha_tier": None,
        "alpha_composite": None,
        "source_data_freshness": freshness or signal.get("timestamp") or "",
        "paper_eligible": False,
        "paper_eligibility_reason": reason,
        "safety_reason": reason,
    }


def catalyst_source_accounting(payload: dict[str, Any]) -> dict[str, Any]:
    live_status = payload.get("live_status") or {}
    providers = live_status.get("providers") if isinstance(live_status, dict) else []
    problems = []
    responses = 0
    requests = 0
    if isinstance(providers, list):
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            requests += 1
            status = str(provider.get("status") or "unknown")
            if status == "ok":
                responses += 1
            else:
                name = provider.get("name", "provider")
                reason = provider.get("reason") or provider.get("error") or status
                problems.append(f"{name}: {reason}")
    return {
        "enabled": payload.get("mode") == "live",
        "requests_attempted": requests,
        "responses_received": responses,
        "raw_items": len(payload.get("catalysts") or []),
        "candidates_filtered": max(0, len(payload.get("catalysts") or []) - len(payload.get("signals") or [])),
        "source_problems": problems[:8],
    }
