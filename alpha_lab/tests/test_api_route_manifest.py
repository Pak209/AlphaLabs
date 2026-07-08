"""Route-manifest characterization of the API surface (Phase 2 PR4).

Pins the COMPLETE (method, path) inventory of create_app so router
extractions are provably path-neutral: moving a handler between files must
leave this list byte-identical. Update the manifest only for a deliberate,
human-approved endpoint addition/removal, in the same commit, with a handoff
entry.

Also spot-pins the response shapes of the two ops-cluster endpoints that had
no direct test before the router split (db-status, agent-status).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.service import AlphaLabService


def make_client(tmp_path: Path) -> TestClient:
    lab = AlphaLabService(
        db_path=str(tmp_path / "manifest.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    return TestClient(create_app(lab))


def current_manifest(app) -> list[str]:
    entries = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                entries.append(f"{method} {route.path}")
    return sorted(entries)


def test_route_manifest_is_frozen(tmp_path: Path):
    client = make_client(tmp_path)
    assert current_manifest(client.app) == MANIFEST


def test_db_status_response_shape(tmp_path: Path):
    body = make_client(tmp_path).get("/api/db-status").json()
    for key in ("db_path", "db_exists", "ideas_count", "trades_count",
                "catalyst_events_count", "last_scanner_run_at",
                "scheduler_heartbeat_at", "scheduler_heartbeat"):
        assert key in body, key
    assert body["db_exists"] is True
    assert isinstance(body["ideas_count"], int)


def test_agent_status_response_shape(tmp_path: Path):
    body = make_client(tmp_path).get("/api/ops/agent-status").json()
    for key in ("status", "read_only", "scanner_runs",
                "scheduler_job_count", "scheduler_jobs"):
        assert key in body, key
    assert body["read_only"] is True
    assert body["status"] in {"ok", "needs_attention"}


MANIFEST: list[str] = [
    "GET /",
    "GET /api/after-hours/btc",
    "GET /api/alerts",
    "GET /api/alerts/levels",
    "GET /api/alerts/{alert_id}",
    "GET /api/alpaca/health",
    "GET /api/brief/daily",
    "GET /api/briefings",
    "GET /api/business-profiles",
    "GET /api/catalysts/intelligence",
    "GET /api/catalysts/radar",
    "GET /api/dashboard",
    "GET /api/db-status",
    "GET /api/diagnostics/rejection-waterfall",
    "GET /api/execution-audit",
    "GET /api/futures/pulse",
    "GET /api/futures/snapshots",
    "GET /api/health",
    "GET /api/ideas",
    "GET /api/ideas/pending-approval",
    "GET /api/ideas/{idea_id}/explanation",
    "GET /api/market/bitcoin",
    "GET /api/market/liquidity",
    "GET /api/market/oil",
    "GET /api/market/trending-stocks",
    "GET /api/notifications/audit",
    "GET /api/notifications/preferences",
    "GET /api/notifications/vapid-public-key",
    "GET /api/ops/agent-status",
    "GET /api/options/flow-preview",
    "GET /api/performance/ideas",
    "GET /api/performance/report",
    "GET /api/performance/scoreboard",
    "GET /api/review/briefing",
    "GET /api/review/opportunity/{idea_id}",
    "GET /api/safety-status",
    "GET /api/signals/evaluations",
    "GET /api/stats/strategies",
    "GET /api/stats/strategies/diagnostics",
    "GET /api/trades",
    "GET /review",
    "GET /sw.js",
    "POST /api/after-hours/btc/generate",
    "POST /api/alerts/{alert_id}/status",
    "POST /api/alpaca/sync",
    "POST /api/brief/daily/import-and-test",
    "POST /api/briefings/daily/generate",
    "POST /api/catalysts/import-and-test",
    "POST /api/catalysts/intelligence",
    "POST /api/catalysts/poll",
    "POST /api/catalysts/score",
    "POST /api/chat",
    "POST /api/config",
    "POST /api/ideas",
    "POST /api/ideas/import",
    "POST /api/ideas/import-and-test",
    "POST /api/ideas/test-new",
    "POST /api/ideas/{idea_id}/approval/approve",
    "POST /api/ideas/{idea_id}/approval/expire",
    "POST /api/ideas/{idea_id}/approval/reject",
    "POST /api/ideas/{idea_id}/approve",
    "POST /api/ideas/{idea_id}/decision",
    "POST /api/ideas/{idea_id}/dry-run-trade",
    "POST /api/ideas/{idea_id}/explanation/regenerate",
    "POST /api/ideas/{idea_id}/paper-trade",
    "POST /api/ideas/{idea_id}/reject",
    "POST /api/journal",
    "POST /api/notifications/preferences",
    "POST /api/notifications/subscribe",
    "POST /api/notifications/test",
    "POST /api/notifications/unsubscribe",
    "POST /api/signals/evaluate",
    "POST /api/strategies/test-trending",
]
