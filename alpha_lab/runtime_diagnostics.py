from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import SchedulerNotRunningError

from .database import connect, resolve_db_path
from .env import find_dotenv, load_dotenv, parse_dotenv
from .scheduler import automation_mode, build_scheduler


LOCAL_TZ = ZoneInfo("America/Los_Angeles")
CHECKOUT_PATH = Path(__file__).resolve().parents[1]


def _resolve_db_path(raw_path: str | None = None) -> Path:
    # Delegate the precedence chain (explicit > ALPHA_LAB_DB_PATH > default) to
    # the one shared resolver so diagnostics report the SAME path the service,
    # scheduler, and reports use; just normalize to an absolute Path here.
    path = Path(resolve_db_path(raw_path)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _env_names(dotenv_path: Path | None) -> list[str]:
    if not dotenv_path or not dotenv_path.is_file():
        return []
    try:
        parsed = parse_dotenv(dotenv_path.read_text(encoding="utf-8"))
    except OSError:
        return []
    return sorted(parsed.keys())


def _public_env_names() -> list[str]:
    return sorted(
        key
        for key in os.environ
        if key.startswith(("ALPHA", "ALPHALAB", "POLYGON", "ALPACA", "TAILSCALE"))
    )


def _git_status() -> dict[str, Any]:
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=CHECKOUT_PATH,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=CHECKOUT_PATH,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=CHECKOUT_PATH,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.splitlines()
        return {"is_git_repo": True, "root": root, "branch": branch, "dirty_files": len(status)}
    except (OSError, subprocess.SubprocessError):
        return {"is_git_repo": False}


def _scheduler_jobs() -> list[dict[str, Any]]:
    scheduler = build_scheduler(service=object())
    now = datetime.now(LOCAL_TZ)
    jobs: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        next_run = job.trigger.get_next_fire_time(None, now)
        jobs.append(
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
    return jobs


def build_diagnostics() -> dict[str, Any]:
    dotenv_path = CHECKOUT_PATH / ".env"
    if not dotenv_path.is_file():
        dotenv_path = find_dotenv(Path(__file__).resolve())
    applied = load_dotenv(dotenv_path)
    db_path = _resolve_db_path()
    db_stat = db_path.stat() if db_path.exists() else None
    jobs = _scheduler_jobs()
    return {
        "checkout_path": str(CHECKOUT_PATH),
        "current_working_directory": str(Path.cwd().resolve()),
        "python_executable": sys.executable,
        "dotenv_path": str(dotenv_path) if dotenv_path else None,
        "dotenv_keys": _env_names(dotenv_path),
        "loaded_env_var_names": _public_env_names(),
        "loaded_dotenv_key_names": sorted(applied.keys()),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_dir_writable": os.access(db_path.parent, os.W_OK) if db_path.parent.exists() else False,
        "db_last_modified": (
            datetime.fromtimestamp(db_stat.st_mtime, LOCAL_TZ).isoformat() if db_stat else None
        ),
        "scheduler_mode": automation_mode(),
        "scheduler_enabled_by_launchd": "unknown",
        "scheduler_job_count": len(jobs),
        "scheduler_jobs": jobs,
        "timezone": "America/Los_Angeles",
        "now_local": datetime.now(LOCAL_TZ).isoformat(),
        "launch_mode": os.getenv("ALPHALAB_LAUNCH_MODE", "cli"),
        "process_pid": os.getpid(),
        "git": _git_status(),
    }


def write_smoke_test(db_path: Path, scheduler_label: str | None) -> int:
    payload = {
        "cwd": str(Path.cwd().resolve()),
        "checkout_path": str(CHECKOUT_PATH),
        "db_path": str(db_path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "process_pid": os.getpid(),
        "scheduler_label": scheduler_label or "",
        "python_executable": sys.executable,
    }
    with connect(str(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO scanner_runs (source, run_type, payload_json) VALUES (?, ?, ?)",
            ("runtime_path_smoke_test", "runtime_path_verification", json.dumps(payload, sort_keys=True)),
        )
        conn.commit()
        return int(cur.lastrowid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only AlphaLab runtime path diagnostics.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--write-smoke-test", action="store_true", help="Write one scanner_runs runtime smoke row.")
    parser.add_argument("--scheduler-label", default="", help="launchd label to record on the smoke row.")
    args = parser.parse_args()

    diagnostics = build_diagnostics()
    db_path = _resolve_db_path(args.db)
    diagnostics["db_path"] = str(db_path)
    if args.write_smoke_test:
        diagnostics["smoke_test_scanner_run_id"] = write_smoke_test(db_path, args.scheduler_label)

    print(json.dumps(diagnostics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
