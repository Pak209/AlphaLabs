"""Ops/diagnostics router: the five read-only status endpoints.

Handlers moved VERBATIM from api.create_app (Phase 2 PR4); paths, response
shapes, and behavior are pinned by test_api_route_manifest.py and the
existing endpoint tests. Read-only by design — nothing here can approve,
import, or trade.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..agent_status import build_agent_status
from ..scheduler import scheduler_safety_status


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

    @router.get("/api/ops/agent-status")
    def agent_status(limit: int = 50) -> dict[str, Any]:
        return build_agent_status(lab.db_path, limit=limit)

    return router
