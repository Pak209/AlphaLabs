"""Ops/diagnostics router: the five read-only status endpoints.

Handlers moved VERBATIM from api.create_app (Phase 2 PR4); paths, response
shapes, and behavior are pinned by test_api_route_manifest.py and the
existing endpoint tests. Read-only by design — nothing here can approve,
import, or trade.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import os

from ..agent_status import build_agent_status
from ..scanning import CRYPTO_SCAN_COOLDOWN_MINUTES, MAX_SIMULATED_CRYPTO_IDEAS_PER_DAY
from ..scheduler import scheduler_safety_status
from ..scoring_engine import (
    CATALYST_CONFIRM_MIN, PRICE_VOLUME_CONFIRM_MIN, WATCHLIST_CEILING, WEIGHTS,
)
from paper_trader.config import load_config


def build_ops_router(lab) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        # Expose the resolved DB identity (path + device:inode) so a health check
        # can PROVE the dashboard and scheduler are reading/writing the SAME file,
        # not just two same-named DBs. Identity errors must never down the probe.
        try:
            identity = lab.db_identity()
        except Exception as exc:  # pragma: no cover - defensive
            identity = {"db_error": str(exc)}
        return {"status": "ok", "mode": "paper-research", "default_execution": "dry-run", **identity}

    @router.get("/api/db-status")
    def db_status() -> dict[str, Any]:
        # Full operational snapshot of the active database for dashboards / phone:
        # path, existence, idea + trade counts, and the scheduler heartbeat.
        return lab.db_status()

    @router.get("/api/safety-status")
    def safety_status() -> dict[str, Any]:
        return scheduler_safety_status()

    @router.get("/api/diagnostics/rejection-waterfall")
    def rejection_waterfall(limit: int = 5000) -> dict[str, Any]:
        # Read-only pipeline observability: stage funnel, per-gate failure
        # counts (structured traces + legacy reason parsing), first-failed-gate
        # histogram, and threshold near-miss impact. Never mutates state.
        return lab.rejection_waterfall(limit=max(100, min(int(limit), 20000)))


    @router.get("/api/system-controls")
    def system_controls() -> dict[str, Any]:
        """Read-only visibility into every backend switch, limit, and gate.

        VISUALIZATION ONLY by design: gates/limits change through the
        calibration protocol (evidence -> shadow -> approval), env switches
        through .env + agent restart — never through a web form. Each entry
        says where it lives and how it is legitimately changed.
        """
        def flag(name: str, default: str, meaning: str) -> dict[str, Any]:
            return {"name": name, "value": os.getenv(name, "").strip() or f"(default: {default})",
                    "meaning": meaning, "change": ".env + restart affected agent(s)"}

        def limits(profile: str) -> dict[str, Any]:
            c = load_config("alpha_lab/config.example.json", profile=profile)
            return {"min_confidence": c.min_confidence,
                    "max_position_size_usd": c.max_position_size_usd,
                    "max_equity_pct_per_trade": c.max_equity_pct_per_trade,
                    "max_trades_per_day": c.max_trades_per_day,
                    "max_open_positions": c.max_open_positions,
                    "approved_tickers": sorted(c.approved_tickers),
                    "stop_loss_pct": c.stop_loss_pct,
                    "take_profit_pct": c.take_profit_pct,
                    "max_daily_drawdown_pct": c.max_daily_drawdown_pct,
                    "allow_short": c.allow_short}

        return {
            "read_only": True,
            "runtime_switches": [
                flag("ALPHALAB_SCHEDULER_MODE", "dry_run", "paper = scheduler jobs may place Alpaca paper orders"),
                flag("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "false", "second arm switch — both must be set for scheduler paper orders"),
                flag("ALPHALAB_ALLOW_MANUAL_PAPER_TRADES", "true", "manual paper-trade buttons/endpoints"),
                flag("ALPHALAB_REQUIRE_PAPER_APPROVAL", "true", "human sign-off before LLM/crypto paper orders (false = paper-learning)"),
                flag("ALPHALAB_REQUIRE_OPTION_APPROVAL", "true", "human sign-off before ANY option order (independent of the above)"),
                flag("ALPHALAB_OPTIONS_AUTOMATION", "off", "off|shadow|on — 'on' behaves as shadow until the arming PR"),
                flag("ALPHALAB_EXIT_MANAGEMENT", "off", "off|shadow|on — stop/target exit engine (on also needs the arm switches)"),
                flag("YAHOO_NEWS_ENABLED", "false", "keyless Yahoo RSS news source"),
                flag("ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS", "false", "permits REAL test pushes via API (remove after testing)"),
                flag("ALERT_DELIVERY_DRY_RUN", "unset", "forces notification dry-run regardless of preferences"),
            ],
            "risk_limits": {
                "source": "alpha_lab/config.example.json (LIVE config despite the name — see docs/CONFIG_SOURCES.md)",
                "change": "risk-limit changes are human-approved edits + deploy; loosening is never automated",
                "default_profile": limits("default"),
                "crypto_profile": limits("crypto"),
            },
            "gate_thresholds": [
                {"gate": "alpha composite (paper execution)", "value": ">= 70 and tier tradeable/high_conviction",
                 "source": "alpha_lab/service.py _paper_order_eligibility_error", "change": "calibration protocol"},
                {"gate": "catalyst confirmation minimum", "value": CATALYST_CONFIRM_MIN,
                 "source": "alpha_lab/scoring_engine.py", "change": "calibration protocol"},
                {"gate": "price/volume confirmation minimum", "value": PRICE_VOLUME_CONFIRM_MIN,
                 "source": "alpha_lab/scoring_engine.py", "change": "calibration protocol"},
                {"gate": "unconfirmed-idea ceiling", "value": WATCHLIST_CEILING,
                 "source": "alpha_lab/scoring_engine.py", "change": "structural safety — not tunable"},
                {"gate": "composite weights", "value": WEIGHTS,
                 "source": "alpha_lab/scoring_engine.py", "change": "calibration protocol (replay evidence)"},
                {"gate": "radar trade-candidate floor", "value": "catalyst_score >= 68, actionability >= 3.5, confidence >= 0.75",
                 "source": "alpha_lab/catalysts.py score_catalyst", "change": "calibration protocol"},
                {"gate": "PV gap deadband", "value": "0.25%",
                 "source": "alpha_lab/service.py _PV_GAP_DEADBAND_PCT", "change": "calibration protocol"},
                {"gate": "near-miss margin (telemetry)", "value": "10% of threshold",
                 "source": "alpha_lab/waterfall.py", "change": "diagnostics-only constant"},
                {"gate": "crypto scan cooldown / daily cap", "value": f"{CRYPTO_SCAN_COOLDOWN_MINUTES} min / {MAX_SIMULATED_CRYPTO_IDEAS_PER_DAY} ideas",
                 "source": "alpha_lab/scanning.py", "change": "human-approved edit"},
                {"gate": "option selector", "value": "7-14 DTE, spread <= 15%, 1 contract within budget",
                 "source": "alpha_lab/options_selector.py", "change": "PR-C parameterization (planned)"},
            ],
            "data_sources": [
                {"name": name, "configured": bool(os.getenv(env, "").strip())}
                for name, env in (
                    ("Polygon (PV confirmation + news)", "POLYGON_API_KEY"),
                    ("Alpaca (broker + IEX data)", "ALPACA_API_KEY"),
                    ("SEC EDGAR", "SEC_USER_AGENT"),
                    ("Yahoo News (flag)", "YAHOO_NEWS_ENABLED"),
                    ("Benzinga", "BENZINGA_API_KEY"),
                    ("Tiingo", "TIINGO_API_KEY"),
                    ("Newsfilter", "NEWSFILTER_API_KEY"),
                )
            ],
            "invariants": [
                "Paper-only: non-paper Alpaca endpoints are refused in code, not config.",
                "Rejected/expired ideas never execute.",
                "Option orders always require human approval unless explicitly disabled.",
                "The system may only tighten on its own; only a human loosens, arms, or spends.",
            ],
        }

    @router.get("/api/ops/agent-status")
    def agent_status(limit: int = 50) -> dict[str, Any]:
        return build_agent_status(lab.db_path, limit=limit)

    return router
