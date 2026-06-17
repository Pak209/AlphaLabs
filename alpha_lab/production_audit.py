"""Read-only production audit of the live AlphaLabs DB + automation posture.

This module answers the data-side questions of a daily production audit:
did Polygon and SEC EDGAR gather alpha today, were ideas generated, were any
paper trades submitted, which ideas became trades, and is automation currently
dry-run or paper.

It is strictly read-only: it opens the SQLite DB with ``mode=ro`` and only reads
environment variables to report the scheduler mode (never their secret values).
Infrastructure checks (SSH reachability, LaunchAgent state, API health, DB-path
parity) live in the ``ops`` orchestrator, which combines them with this module's
output to produce the final GREEN/YELLOW/RED report.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from .daily_activity_report import window_for_day
from .database import resolve_db_path
from .env import load_dotenv

POLYGON_LIKE = "Polygon%"
SEC_LIKE = ("%EDGAR%", "%SEC%")


def _automation_state() -> dict[str, Any]:
    """Report scheduler trading posture from env (booleans only, no secrets)."""
    mode = (os.getenv("ALPHALAB_SCHEDULER_MODE", "dry_run") or "dry_run").strip().lower()
    if mode != "paper":
        mode = "dry_run"
    armed = (os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "") or "").strip().lower() == "true"
    return {
        "scheduler_mode": mode,
        "paper_trades_armed": armed,
        "paper_trades_can_trigger": mode == "paper" and armed,
    }


def _sanitize(value: Any) -> str:
    """Make a value safe for one-line ``key=value`` transport (no | or newlines)."""
    text = " ".join(str(value or "").split())
    return text.replace("|", "/")


def build_audit(db_path: str | None = None, day: date | None = None) -> dict[str, Any]:
    """Collect the read-only data-side audit for ``day`` (default: today, LA)."""
    resolved = resolve_db_path(db_path)
    db_file = Path(resolved).expanduser()
    window = window_for_day(day)
    audit: dict[str, Any] = {
        "day": window.day.isoformat(),
        "db_path": str(db_file),
        "db_exists": db_file.exists(),
        "automation": _automation_state(),
        "polygon": {"today": 0, "total": 0, "latest": ""},
        "sec": {"today": 0, "total": 0, "latest": ""},
        "ideas_today": 0,
        "paper_trades_today": 0,
        "dry_run_trades_today": 0,
        "paper_orders_today": 0,
        "paper_orders_with_broker_id": 0,
        "rejects_today": 0,
        "broker_unavailable_today": 0,
        "scanner_runs_today": 0,
        "catalyst_radar_runs_today": 0,
        "scanner_errors_today": 0,
        "ideas_to_trades": [],
    }
    if not db_file.exists():
        audit["error"] = f"database not found: {resolved}"
        audit["data_reasons"] = ["database file not found at resolved path"]
        return audit

    start, end = window.sql_start, window.sql_end
    conn = sqlite3.connect(f"file:{db_file.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:

        def count(sql: str, *params: Any) -> int:
            return int(conn.execute(sql, params).fetchone()[0])

        def scalar(sql: str, *params: Any) -> str:
            return str(conn.execute(sql, params).fetchone()[0] or "")

        audit["polygon"] = {
            "today": count(
                "SELECT COUNT(*) FROM catalyst_events WHERE source LIKE ? "
                "AND datetime(discovered_at) >= datetime(?) AND datetime(discovered_at) < datetime(?)",
                POLYGON_LIKE,
                start,
                end,
            ),
            "total": count("SELECT COUNT(*) FROM catalyst_events WHERE source LIKE ?", POLYGON_LIKE),
            "latest": scalar(
                "SELECT COALESCE(MAX(discovered_at), '') FROM catalyst_events WHERE source LIKE ?",
                POLYGON_LIKE,
            ),
        }
        audit["sec"] = {
            "today": count(
                "SELECT COUNT(*) FROM catalyst_events WHERE (source LIKE ? OR source LIKE ?) "
                "AND datetime(discovered_at) >= datetime(?) AND datetime(discovered_at) < datetime(?)",
                SEC_LIKE[0],
                SEC_LIKE[1],
                start,
                end,
            ),
            "total": count(
                "SELECT COUNT(*) FROM catalyst_events WHERE source LIKE ? OR source LIKE ?",
                SEC_LIKE[0],
                SEC_LIKE[1],
            ),
            "latest": scalar(
                "SELECT COALESCE(MAX(discovered_at), '') FROM catalyst_events WHERE source LIKE ? OR source LIKE ?",
                SEC_LIKE[0],
                SEC_LIKE[1],
            ),
        }
        audit["ideas_today"] = count(
            "SELECT COUNT(*) FROM alpha_ideas "
            "WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            start,
            end,
        )
        audit["paper_trades_today"] = count(
            "SELECT COUNT(*) FROM trades WHERE dry_run = 0 "
            "AND datetime(opened_at) >= datetime(?) AND datetime(opened_at) < datetime(?)",
            start,
            end,
        )
        audit["dry_run_trades_today"] = count(
            "SELECT COUNT(*) FROM trades WHERE dry_run = 1 "
            "AND datetime(opened_at) >= datetime(?) AND datetime(opened_at) < datetime(?)",
            start,
            end,
        )
        audit["paper_orders_today"] = count(
            "SELECT COUNT(*) FROM orders WHERE dry_run = 0 "
            "AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            start,
            end,
        )
        audit["paper_orders_with_broker_id"] = count(
            "SELECT COUNT(*) FROM orders WHERE dry_run = 0 "
            "AND alpaca_order_id IS NOT NULL AND alpaca_order_id <> '' "
            "AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            start,
            end,
        )
        audit["rejects_today"] = count(
            "SELECT COUNT(*) FROM execution_audit WHERE lower(status) LIKE ? "
            "AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            "reject%",
            start,
            end,
        )
        audit["broker_unavailable_today"] = count(
            "SELECT COUNT(*) FROM execution_audit WHERE lower(status) = ? "
            "AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            "broker_unavailable",
            start,
            end,
        )
        audit["catalyst_radar_runs_today"] = count(
            "SELECT COUNT(*) FROM scanner_runs WHERE source = ? "
            "AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            "catalyst_radar",
            start,
            end,
        )

        scanner_rows = conn.execute(
            "SELECT payload_json FROM scanner_runs "
            "WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)",
            (start, end),
        ).fetchall()
        audit["scanner_runs_today"] = len(scanner_rows)
        audit["scanner_errors_today"] = sum(1 for row in scanner_rows if _is_scanner_error(row["payload_json"]))

        trade_rows = conn.execute(
            "SELECT t.id, t.opened_at, t.ticker, t.dry_run, t.status, "
            "i.source AS idea_source, ce.source AS catalyst_source, MAX(o.alpaca_order_id) AS alpaca_order_id "
            "FROM trades t "
            "LEFT JOIN alpha_ideas i ON t.idea_id = i.id "
            "LEFT JOIN catalyst_events ce ON i.catalyst_event_id = ce.id "
            "LEFT JOIN orders o ON o.trade_id = t.id "
            "WHERE datetime(t.opened_at) >= datetime(?) AND datetime(t.opened_at) < datetime(?) "
            "GROUP BY t.id ORDER BY datetime(t.opened_at) ASC, t.id ASC",
            (start, end),
        ).fetchall()
        audit["ideas_to_trades"] = [
            {
                "ticker": _sanitize(row["ticker"]),
                "mode": "dry_run" if int(row["dry_run"] or 0) else "paper",
                "idea_source": _sanitize(row["idea_source"]) or "-",
                "catalyst_source": _sanitize(row["catalyst_source"]) or "-",
                "status": _sanitize(row["status"]) or "-",
                "broker_order": bool(row["alpaca_order_id"]),
            }
            for row in trade_rows
        ]
    finally:
        conn.close()

    audit["data_reasons"] = data_reasons(audit)
    return audit


def _is_scanner_error(payload_json: Any) -> bool:
    try:
        data = json.loads(payload_json or "{}")
    except (TypeError, ValueError):
        return True
    if not isinstance(data, dict):
        return True
    if str(data.get("status") or "").strip().lower() == "error":
        return True
    return bool(data.get("error") or data.get("error_message") or data.get("source_problems"))


def data_reasons(audit: dict[str, Any]) -> list[str]:
    """Yellow-level reasons derived purely from the data side of the audit."""
    reasons: list[str] = []
    if audit["polygon"]["today"] == 0:
        reasons.append("Polygon gathered no alpha today")
    if audit["sec"]["today"] == 0:
        reasons.append("SEC EDGAR gathered no alpha today")
    if audit["ideas_today"] == 0:
        reasons.append("no ideas generated today")
    if audit["scanner_errors_today"] > 0:
        reasons.append(f"{audit['scanner_errors_today']} scanner run(s) reported errors today")
    if audit["broker_unavailable_today"] > 0:
        reasons.append(f"{audit['broker_unavailable_today']} execution(s) hit broker_unavailable today")
    if audit["automation"]["scheduler_mode"] == "paper" and audit["paper_trades_today"] == 0:
        reasons.append("scheduler is in paper mode but no paper trades were submitted today")
    return reasons


def to_kv(audit: dict[str, Any]) -> list[str]:
    """Flatten the audit into ``key=value`` lines for the ops orchestrator."""
    auto = audit["automation"]
    lines = [
        f"audit_day={audit['day']}",
        f"db_path={audit['db_path']}",
        f"db_exists={str(audit['db_exists']).lower()}",
        f"polygon_today={audit['polygon']['today']}",
        f"polygon_total={audit['polygon']['total']}",
        f"polygon_latest={audit['polygon']['latest']}",
        f"sec_today={audit['sec']['today']}",
        f"sec_total={audit['sec']['total']}",
        f"sec_latest={audit['sec']['latest']}",
        f"ideas_today={audit['ideas_today']}",
        f"paper_trades_today={audit['paper_trades_today']}",
        f"dry_run_trades_today={audit['dry_run_trades_today']}",
        f"paper_orders_today={audit['paper_orders_today']}",
        f"paper_orders_with_broker_id={audit['paper_orders_with_broker_id']}",
        f"rejects_today={audit['rejects_today']}",
        f"broker_unavailable_today={audit['broker_unavailable_today']}",
        f"scanner_runs_today={audit['scanner_runs_today']}",
        f"catalyst_radar_runs_today={audit['catalyst_radar_runs_today']}",
        f"scanner_errors_today={audit['scanner_errors_today']}",
        f"scheduler_mode={auto['scheduler_mode']}",
        f"paper_trades_armed={str(auto['paper_trades_armed']).lower()}",
        f"paper_trades_can_trigger={str(auto['paper_trades_can_trigger']).lower()}",
    ]
    for trade in audit["ideas_to_trades"]:
        lines.append(
            "trade="
            + "|".join(
                [
                    trade["ticker"],
                    trade["mode"],
                    trade["idea_source"],
                    trade["catalyst_source"],
                    trade["status"],
                    "broker" if trade["broker_order"] else "no_broker",
                ]
            )
        )
    for reason in audit.get("data_reasons", []):
        lines.append(f"data_reason={reason}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only data-side production audit for AlphaLabs.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--date", help="Local date to audit, YYYY-MM-DD. Defaults to today in America/Los_Angeles.")
    parser.add_argument("--format", choices=["kv", "json"], default="kv", help="Output format (default: kv).")
    args = parser.parse_args(argv)
    load_dotenv()
    db_path = resolve_db_path(args.db)
    day = None if not args.date or args.date.lower() == "today" else date.fromisoformat(args.date)
    audit = build_audit(db_path, day)
    if args.format == "json":
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        for line in to_kv(audit):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
