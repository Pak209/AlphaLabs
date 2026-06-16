"""
alpha_lab/db_status.py — one-shot "where is my data and is it live?" report.

Prints the ACTIVE database path (resolved through the same precedence chain the
dashboard and scheduler use), whether it exists, the latest idea/trade counts,
and the most recent scheduler heartbeat + scanner-run timestamps. Run it on the
old Mac (the source of truth) or from anywhere that resolves the same path:

    .venv/bin/python -m alpha_lab.db_status          # human-readable
    .venv/bin/python -m alpha_lab.db_status --json    # machine-readable
    .venv/bin/python -m alpha_lab.db_status --db /path/to/alphalab.db

It is strictly READ-ONLY: it opens the database in SQLite read-only (uri) mode
and NEVER creates the file. That is deliberate — constructing the service would
auto-create an empty DB and make "DB exists" always true, defeating the check.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import resolve_db_path
from .env import load_dotenv


def _scalar(conn: sqlite3.Connection, query: str) -> Any:
    try:
        row = conn.execute(query).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def collect_status(db_path_arg: str | None = None) -> dict[str, Any]:
    path = Path(resolve_db_path(db_path_arg)).expanduser().resolve()
    status: dict[str, Any] = {
        "db_path": str(path),
        "db_exists": path.exists(),
        "ideas_count": None,
        "trades_count": None,
        "scheduler_heartbeat_at": None,
        "scheduler_heartbeat_mode": None,
        "scheduler_heartbeat_db_path": None,
        "last_scanner_run_at": None,
        "last_scanner_run_source": None,
        "db_modified": None,
        "db_size_bytes": None,
    }
    if not path.exists():
        return status

    st = path.stat()
    status["db_size_bytes"] = st.st_size
    status["db_modified"] = datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat()

    # Read-only open: never create or migrate the file from a status command.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        status["ideas_count"] = _scalar(conn, "SELECT COUNT(*) FROM alpha_ideas")
        status["trades_count"] = _scalar(conn, "SELECT COUNT(*) FROM trades")
        run = None
        try:
            run = conn.execute(
                "SELECT source, created_at FROM scanner_runs ORDER BY datetime(created_at) DESC, id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            run = None
        if run:
            status["last_scanner_run_at"] = run["created_at"]
            status["last_scanner_run_source"] = run["source"]
        try:
            beat_row = conn.execute(
                "SELECT value_json FROM app_config WHERE key='scheduler_heartbeat'"
            ).fetchone()
        except sqlite3.Error:
            beat_row = None
        if beat_row:
            try:
                beat = json.loads(beat_row["value_json"])
            except (TypeError, ValueError):
                beat = {}
            status["scheduler_heartbeat_at"] = beat.get("timestamp")
            status["scheduler_heartbeat_mode"] = beat.get("scheduler_mode")
            status["scheduler_heartbeat_db_path"] = beat.get("db_path")
    finally:
        conn.close()
    return status


def _format_human(status: dict[str, Any]) -> str:
    yes_no = "yes" if status["db_exists"] else "NO"
    lines = [
        "AlphaLab database status",
        "========================",
        f"  active DB path        : {status['db_path']}",
        f"  DB exists             : {yes_no}",
    ]
    if status["db_exists"]:
        size_kb = (status["db_size_bytes"] or 0) / 1024
        lines += [
            f"  DB size               : {size_kb:.1f} KB",
            f"  DB last modified      : {status['db_modified']}",
            f"  ideas (count)         : {status['ideas_count']}",
            f"  trades (count)        : {status['trades_count']}",
            f"  scheduler heartbeat   : {status['scheduler_heartbeat_at'] or 'never (scheduler not running?)'}",
            f"  heartbeat mode        : {status['scheduler_heartbeat_mode'] or '-'}",
            f"  latest scanner run    : {status['last_scanner_run_at'] or '-'}"
            + (f"  ({status['last_scanner_run_source']})" if status['last_scanner_run_source'] else ""),
        ]
        beat_db = status.get("scheduler_heartbeat_db_path")
        if beat_db and beat_db != status["db_path"]:
            lines.append(
                f"  WARNING: scheduler last wrote a DIFFERENT db_path: {beat_db}"
            )
    else:
        lines.append("  (no database at the active path yet — start the dashboard/scheduler to create it)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the active AlphaLab DB path, existence, and live counts.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text.")
    args = parser.parse_args()

    # Load .env so ALPHA_LAB_DB_PATH (and friends) resolve exactly as the services do.
    load_dotenv()
    status = collect_status(args.db)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(_format_human(status))
    return 0 if status["db_exists"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
