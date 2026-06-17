from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import SchedulerNotRunningError

from .scheduler import build_scheduler


LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _parse_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"status": "error", "error_message": "invalid scanner_runs payload_json"}
    return payload if isinstance(payload, dict) else {"status": "error", "error_message": "non-object payload_json"}


def _status_from_payload(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    if status:
        return status
    if payload.get("source_problems"):
        return "warning"
    if payload.get("error") or payload.get("error_message"):
        return "error"
    return "ok"


def _items_created(payload: dict[str, Any]) -> int:
    for key in ("ideas_persisted", "items_created", "orders_created", "candidates_found", "raw_items"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _error_message(payload: dict[str, Any]) -> str:
    for key in ("error_message", "error", "reason", "note"):
        value = payload.get(key)
        if value:
            return str(value)
    problems = payload.get("source_problems")
    if problems:
        return json.dumps(problems, sort_keys=True, default=str)
    rejections = payload.get("top_rejection_reasons")
    if rejections:
        return json.dumps(rejections, sort_keys=True, default=str)
    return ""


def _scanner_run_statuses(db_path: str, limit: int) -> list[dict[str, Any]]:
    path = Path(db_path).expanduser().resolve()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT source, run_type, payload_json, created_at
            FROM scanner_runs
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        payload = _parse_payload(row["payload_json"])
        created_at = row["created_at"]
        output.append(
            {
                "agent": row["source"],
                "run_type": row["run_type"],
                "last_started_at": payload.get("started_at") or payload.get("timestamp") or created_at,
                "last_finished_at": payload.get("finished_at") or created_at,
                "status": _status_from_payload(payload),
                "items_created": _items_created(payload),
                "error_message": _error_message(payload),
                "duration_ms": payload.get("duration_ms"),
                "dry_run": payload.get("dry_run"),
            }
        )
    return output


def _scheduler_job_statuses() -> list[dict[str, Any]]:
    scheduler = build_scheduler(service=object())
    now = datetime.now(LOCAL_TZ)
    output: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        next_run = job.trigger.get_next_fire_time(None, now)
        output.append(
            {
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next_run_time": next_run.isoformat() if next_run else "",
            }
        )
    try:
        scheduler.shutdown(wait=False)
    except SchedulerNotRunningError:
        pass
    return output


def build_agent_status(db_path: str, limit: int = 50) -> dict[str, Any]:
    runs = _scanner_run_statuses(db_path, limit=max(1, limit))
    jobs = _scheduler_job_statuses()
    statuses = {row["status"] for row in runs}
    overall = "needs_attention" if statuses.intersection({"error", "failed", "unauthorized"}) else "ok"
    return {
        "status": overall,
        "read_only": True,
        "scanner_runs": runs,
        "scheduler_job_count": len(jobs),
        "scheduler_jobs": jobs,
    }
