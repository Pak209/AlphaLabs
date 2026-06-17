from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from .database import resolve_db_path
from .env import find_dotenv, load_dotenv


def _connect_read_only(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sample_missing(conn: sqlite3.Connection, table: str, limit: int) -> list[dict[str, Any]]:
    if table == "alpha_ideas":
        rows = conn.execute(
            """
            SELECT i.id, i.ticker, i.source, i.status, i.created_at
            FROM alpha_ideas i
            LEFT JOIN idea_strategies ix ON ix.idea_id = i.id
            WHERE ix.strategy_id IS NULL
            ORDER BY i.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    elif table == "trades":
        rows = conn.execute(
            """
            SELECT t.id, t.idea_id, t.ticker, t.status, t.dry_run, t.opened_at
            FROM trades t
            LEFT JOIN idea_strategies ix ON ix.idea_id = t.idea_id
            WHERE ix.strategy_id IS NULL
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        raise ValueError(f"unknown table: {table}")
    return [dict(row) for row in rows]


def audit_strategy_attribution(db_path: str | None = None, sample_limit: int = 10) -> dict[str, Any]:
    """Read-only audit that every idea/trade has at least one strategy label."""
    resolved = str(Path(resolve_db_path(db_path)).expanduser().resolve())
    with _connect_read_only(resolved) as conn:
        total_ideas = int(conn.execute("SELECT COUNT(*) FROM alpha_ideas").fetchone()[0])
        total_trades = int(conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0])
        total_strategies = int(conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0])
        ideas_missing = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM alpha_ideas i
                LEFT JOIN idea_strategies ix ON ix.idea_id = i.id
                WHERE ix.strategy_id IS NULL
                """
            ).fetchone()[0]
        )
        trades_missing = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM trades t
                LEFT JOIN idea_strategies ix ON ix.idea_id = t.idea_id
                WHERE ix.strategy_id IS NULL
                """
            ).fetchone()[0]
        )
        distinct_tagged_ideas = int(
            conn.execute("SELECT COUNT(DISTINCT idea_id) FROM idea_strategies").fetchone()[0]
        )
        orphan_strategy_links = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM idea_strategies ix
                LEFT JOIN alpha_ideas i ON i.id = ix.idea_id
                LEFT JOIN strategies s ON s.id = ix.strategy_id
                WHERE i.id IS NULL OR s.id IS NULL
                """
            ).fetchone()[0]
        )
        samples = {
            "ideas_missing_strategy_labels": _sample_missing(conn, "alpha_ideas", sample_limit),
            "trades_missing_strategy_labels": _sample_missing(conn, "trades", sample_limit),
        }
    ok = ideas_missing == 0 and trades_missing == 0 and orphan_strategy_links == 0
    return {
        "status": "ok" if ok else "needs_attention",
        "read_only": True,
        "db_path": resolved,
        "total_ideas": total_ideas,
        "total_trades": total_trades,
        "total_strategies": total_strategies,
        "distinct_tagged_ideas": distinct_tagged_ideas,
        "ideas_missing_strategy_labels": ideas_missing,
        "trades_missing_strategy_labels": trades_missing,
        "orphan_strategy_links": orphan_strategy_links,
        "samples": samples,
    }


def _print_human(report: dict[str, Any]) -> None:
    print("AlphaLab strategy attribution audit (read-only)")
    print(f"  status:                         {report['status']}")
    print(f"  db path:                        {report['db_path']}")
    print(f"  total ideas:                    {report['total_ideas']}")
    print(f"  total trades:                   {report['total_trades']}")
    print(f"  total strategies:               {report['total_strategies']}")
    print(f"  distinct tagged ideas:          {report['distinct_tagged_ideas']}")
    print(f"  ideas missing strategy labels:  {report['ideas_missing_strategy_labels']}")
    print(f"  trades missing strategy labels: {report['trades_missing_strategy_labels']}")
    print(f"  orphan strategy links:          {report['orphan_strategy_links']}")
    for label, rows in report["samples"].items():
        if rows:
            print(f"  sample {label}:")
            for row in rows:
                print(f"    {row}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only AlphaLab strategy attribution audit.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the human summary.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any attribution gaps are found.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Rows to sample for each missing-label group.")
    args = parser.parse_args(argv)

    dotenv = find_dotenv(Path(__file__).resolve())
    load_dotenv(dotenv)
    report = audit_strategy_attribution(args.db, sample_limit=max(0, args.sample_limit))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 1 if args.strict and report["status"] != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
