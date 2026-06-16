from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .database import DEFAULT_DB_PATH, connect, resolve_db_path
from .env import load_dotenv


LOCAL_TZ = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    scanner_sources: tuple[str, ...]
    env_vars: tuple[str, ...] = ()
    always_enabled: bool = False
    note: str = ""


SOURCES = [
    SourceSpec("Polygon News", (), ("POLYGON_API_KEY",), note="Provider inside Catalyst Radar; provider-level accounting starts with new catalyst_radar runs."),
    SourceSpec("Polygon Ticker/Market Data", (), ("POLYGON_API_KEY",), note="Used by price/volume reads and validation quotes; not a standalone scanner."),
    SourceSpec("SEC EDGAR", (), ("SEC_USER_AGENT",), note="Provider inside Catalyst Radar; provider-level accounting starts with new catalyst_radar runs."),
    SourceSpec("Insider Activity", (), ("BENZINGA_API_KEY",), note="Provider inside Catalyst Radar; provider-level accounting starts with new catalyst_radar runs."),
    SourceSpec("Daily Market Brief", ("daily_market_brief",), always_enabled=True),
    SourceSpec("Catalyst Radar", ("catalyst_radar",), always_enabled=True),
    SourceSpec("Futures Pulse", ("overnight_futures_pulse", "futures_pulse"), ("POLYGON_API_KEY",)),
    SourceSpec("Options Flow", ("options_flow",), ("POLYGON_API_KEY",), note="Read-only preview; scheduled premarket."),
    SourceSpec("Macro", (), always_enabled=True, note="Score-only neutral/default component; not a standalone scanner."),
    SourceSpec("BTC/Crypto", ("after_hours_btc",), always_enabled=True),
]


def build_report(db_path: str = DEFAULT_DB_PATH, day: date | None = None) -> dict[str, Any]:
    window_day = day or datetime.now(LOCAL_TZ).date()
    start = datetime.combine(window_day, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    end = datetime.combine(window_day, time.max, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    runs = []
    if Path(db_path).exists():
        with connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT source, run_type, payload_json, created_at
                FROM scanner_runs
                WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
                ORDER BY datetime(created_at) ASC, id ASC
                """,
                (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
            ).fetchall()
            runs = [dict(row) for row in rows]
    rows = [_source_row(spec, runs) for spec in SOURCES]
    return {"day": window_day.isoformat(), "rows": rows, "recommendations": _recommendations(rows)}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# AlphaLabs Source Coverage Report - {report['day']}",
        "",
        "## Source Coverage",
        "",
        "| Source | Enabled | Requests | Raw Items | Candidates | Ideas | Rejected | Top Reason |",
        "| ------ | ------- | -------: | --------: | ---------: | ----: | -------: | ---------- |",
    ]
    for row in report["rows"]:
        lines.append(
            "| {source} | {enabled} | {requests} | {raw_items} | {candidates} | {ideas} | {rejected} | {top_reason} |".format(**row)
        )
    lines.extend(["", "## Source Problems", ""])
    problems = [row for row in report["rows"] if row["problem"]]
    if problems:
        lines.extend(f"- {row['source']}: {row['problem']}" for row in problems)
    else:
        lines.append("None.")
    lines.extend(["", "## Recommended Fixes", ""])
    for item in report["recommendations"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def save_markdown(report: dict[str, Any], report_root: str = "reports/source_coverage") -> Path:
    out_dir = Path(report_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['day']}-source-coverage.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report AlphaLabs source coverage and candidate funnel accounting.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--date", help="Local date YYYY-MM-DD; defaults to today in America/Los_Angeles.")
    parser.add_argument("--out", default="reports/source_coverage")
    args = parser.parse_args(argv)
    load_dotenv()
    db_path = resolve_db_path(args.db)
    day = None if not args.date or args.date.lower() == "today" else date.fromisoformat(args.date)
    report = build_report(db_path, day)
    path = save_markdown(report, args.out)
    print(f"AlphaLabs Source Coverage Report - {report['day']}")
    for row in report["rows"]:
        print(
            f"{row['source']}: enabled={row['enabled']} requests={row['requests']} "
            f"raw={row['raw_items']} candidates={row['candidates']} ideas={row['ideas']} rejected={row['rejected']}"
        )
    print(f"Saved report: {path}")
    return 0


def _source_row(spec: SourceSpec, runs: list[dict[str, Any]]) -> dict[str, Any]:
    matching = [run for run in runs if run.get("source") in spec.scanner_sources]
    payloads = [_loads(run.get("payload_json")) for run in matching]
    enabled = spec.always_enabled or any(os.getenv(name, "").strip() for name in spec.env_vars)
    requests = sum(int(payload.get("requests_attempted") or 0) for payload in payloads)
    raw_items = sum(int(payload.get("raw_items") or payload.get("candidates_found") or 0) for payload in payloads)
    candidates = sum(int(payload.get("candidates_found") or 0) for payload in payloads)
    ideas = sum(int(payload.get("ideas_persisted") or 0) for payload in payloads)
    rejected = sum(int(payload.get("rejected") or 0) for payload in payloads)
    top_reason = _top_reason(payloads)
    problem = _problem(spec, enabled, matching, payloads)
    return {
        "source": spec.name,
        "enabled": "yes" if enabled else "no",
        "requests": requests,
        "raw_items": raw_items,
        "candidates": candidates,
        "ideas": ideas,
        "rejected": rejected,
        "top_reason": top_reason,
        "problem": problem,
        "note": spec.note,
    }


def _problem(spec: SourceSpec, enabled: bool, runs: list[dict[str, Any]], payloads: list[dict[str, Any]]) -> str:
    if not enabled:
        return f"missing env var(s): {', '.join(spec.env_vars)}" if spec.env_vars else "not enabled"
    if not spec.scanner_sources:
        return spec.note or "source is score-only, not scanner"
    if not runs:
        return "not scheduled or did not run today"
    problems = []
    for payload in payloads:
        problems.extend(str(item) for item in payload.get("source_problems") or [])
    if problems:
        return "; ".join(dict.fromkeys(problems))
    if sum(int(payload.get("candidates_found") or 0) for payload in payloads) == 0:
        return "ran but produced zero candidates"
    return ""


def _top_reason(payloads: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for payload in payloads:
        for item in payload.get("top_rejection_reasons") or []:
            if isinstance(item, dict):
                reason = str(item.get("reason") or "")
                counts[reason] = counts.get(reason, 0) + int(item.get("count") or 0)
    if not counts:
        return "-"
    reason, count = max(counts.items(), key=lambda item: item[1])
    return f"{reason}: {count}"


def _recommendations(rows: list[dict[str, Any]]) -> list[str]:
    output = []
    for row in rows:
        if row["enabled"] == "no":
            output.append(f"High - Enable {row['source']} configuration if this source should contribute.")
        elif row["problem"] == "not scheduled or did not run today":
            output.append(f"Medium - Confirm scheduler coverage for {row['source']}.")
        elif row["problem"]:
            output.append(f"Medium - Investigate {row['source']}: {row['problem']}.")
    return output or ["Low - Source accounting is present; continue collecting samples before loosening filters."]


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
