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
class ReportWindow:
    day: date
    start_utc: datetime
    end_utc: datetime

    @property
    def sql_start(self) -> str:
        return self.start_utc.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def sql_end(self) -> str:
        return self.end_utc.strftime("%Y-%m-%d %H:%M:%S")


def window_for_day(day: date | None = None) -> ReportWindow:
    local_day = day or datetime.now(LOCAL_TZ).date()
    start_local = datetime.combine(local_day, time.min, tzinfo=LOCAL_TZ)
    end_local = datetime.combine(local_day, time.max, tzinfo=LOCAL_TZ)
    return ReportWindow(
        day=local_day,
        start_utc=start_local.astimezone(timezone.utc),
        end_utc=end_local.astimezone(timezone.utc),
    )


def build_report(db_path: str = DEFAULT_DB_PATH, day: date | None = None) -> dict[str, Any]:
    window = window_for_day(day)
    db_file = Path(db_path)
    if not db_file.exists():
        return _empty_report(window, f"database not found: {db_path}")

    with connect(db_path) as conn:
        ideas = _rows(conn, _IDEAS_SQL, window)
        trades = _rows(conn, _TRADES_SQL, window)
        orders = _rows(conn, _ORDERS_SQL, window)
        audits = _rows(conn, _AUDITS_SQL, window)
        decisions = _rows(conn, _DECISIONS_SQL, window)
        briefings = _rows(conn, _BRIEFINGS_SQL, window)
        evaluations_today = _rows(conn, _EVALUATIONS_TODAY_SQL, window)
        scanner_runs = _rows(conn, _SCANNER_RUNS_SQL, window)

    scanner_rows = [_scanner_row(row) for row in scanner_runs]
    warnings = _warnings(ideas, trades, orders, audits, scanner_rows)
    summary = _summary(ideas, trades, orders, audits, evaluations_today, briefings, scanner_rows, warnings)
    return {
        "day": window.day.isoformat(),
        "window": {"start_utc": window.start_utc.isoformat(), "end_utc": window.end_utc.isoformat()},
        "summary": summary,
        "ideas": [_idea_row(row) for row in ideas],
        "trades_orders": [_trade_order_row(row) for row in trades] + [_standalone_order_row(row) for row in orders if row.get("trade_id") is None],
        "execution_audit": [_audit_row(row) for row in audits],
        "decision_logs": [_decision_row(row) for row in decisions],
        "market_briefings": [_briefing_row(row) for row in briefings],
        "scanner_runs": scanner_rows,
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# AlphaLabs Daily Activity Report - {report['day']}",
        "",
        "## Summary",
        "",
        f"Ideas generated: {summary['ideas_generated_today']}",
        f"Signals evaluated: {summary['signals_evaluated_today']}",
        f"Signals provisional: {summary['signals_still_provisional']}",
        f"Signals price unavailable: {summary['signals_price_unavailable']}",
        f"Dry-runs: {summary['dry_run_tests_today']}",
        f"Paper orders: {summary['paper_orders_today']}",
        f"Live orders: {summary['live_orders_today']}",
        f"Trades opened: {summary['trades_opened_today']}",
        f"Trades closed: {summary['trades_closed_today']}",
        f"Orders placed: {summary['orders_placed_today']}",
        f"Execution audit events: {summary['execution_audit_events_today']}",
        f"Market briefings: {summary['market_briefings_today']}",
        f"Scanners ran: {summary['scanners_ran']}",
        f"Candidates found: {summary['candidates_found']}",
        "",
        "## Safety Status",
        "",
        _status_line("Live-money orders", summary["real_money_orders_today"], expected_zero=True),
        _status_line("Unlinked trades", summary["unlinked_trades_today"], expected_zero=True),
        _status_line("Missing audit records", summary["paper_orders_missing_audit"], expected_zero=True),
        _status_line("Signals without source tags", summary["signals_missing_source_tags"], expected_zero=True),
        _status_line("Signals without alert price", summary["signals_missing_alert_price"], expected_zero=True),
        _status_line("Ideas never evaluated", summary["ideas_never_evaluated"], expected_zero=True),
        "",
        "## Pipeline Health",
        "",
        f"- scanners_ran: {summary['scanners_ran']}",
        f"- candidates_found: {summary['candidates_found']}",
        f"- ideas_persisted: {summary['ideas_persisted']}",
        f"- evaluations_created: {summary['evaluations_created']}",
        f"- trades_linked: {summary['trades_linked']}",
        f"- missing_source_tags: {summary['signals_missing_source_tags']}",
        f"- ideas_without_evaluations: {summary['ideas_never_evaluated']}",
        "",
        "## Scanner Runs",
        "",
        "| Source | Ran | Candidates | Ideas | Rejected | Top Reason |",
        "| ------ | --- | ---------: | ----: | -------: | ---------- |",
    ]
    if report["scanner_runs"]:
        for row in report["scanner_runs"]:
            lines.append(
                "| {source} | yes | {candidates_found} | {ideas_persisted} | {rejected} | {top_reason} |".format(**row)
            )
    else:
        lines.append("| none | no | 0 | 0 | 0 | - |")

    lines.extend([
        "",
        "## Ideas / Signals",
        "",
        "| Time | Ticker | Direction | Grade | Source | Status | Move | Trade | Order Mode |",
        "| ---- | ------ | --------- | ----- | ------ | ------ | ---- | ----- | ---------- |",
    ])
    if report["ideas"]:
        for row in report["ideas"]:
            lines.append(
                "| {time} | {ticker} | {direction} | {grade} | {source} | {status} | {move} | {trade_id} | {order_mode} |".format(**row)
            )
    else:
        lines.append("| - | - | - | - | - | no ideas today | - | - | - |")

    lines.extend([
        "",
        "## Idea Detail",
        "",
    ])
    if report["ideas"]:
        for row in report["ideas"]:
            lines.extend([
                f"### {row['ticker']} - {row['time']}",
                "",
                f"- Direction: {row['direction']}",
                f"- Source tags: {row['source_tags']}",
                f"- Confidence / alpha score: {row['confidence_alpha']}",
                f"- Catalyst/thesis: {row['summary_text']}",
                f"- Evaluation: {row['status']} grade={row['grade']} alert={row['alert_price']} after={row['price_after']} move={row['move']}",
                f"- Linked trade ID: {row['trade_id']}",
                f"- Linked order ID: {row['order_id']}",
                f"- Order mode: {row['order_mode']}",
                "",
            ])
    else:
        lines.extend(["No ideas or signals were generated today.", ""])

    lines.extend([
        "## Trades / Orders",
        "",
        "| Time | Ticker | Mode | Trade ID | Order ID | Linked Idea | Status |",
        "| ---- | ------ | ---- | -------- | -------- | ----------- | ------ |",
    ])
    if report["trades_orders"]:
        for row in report["trades_orders"]:
            lines.append(
                "| {time} | {ticker} | {mode} | {trade_id} | {order_id} | {linked_idea} | {status} |".format(**row)
            )
    else:
        lines.append("| - | - | none | - | - | - | no trades or orders today |")

    lines.extend([
        "",
        "## Execution Audit",
        "",
        "| Time | Ticker | Mode | Status | Audit ID | Order ID | Idea |",
        "| ---- | ------ | ---- | ------ | -------- | -------- | ---- |",
    ])
    if report["execution_audit"]:
        for row in report["execution_audit"]:
            lines.append(
                "| {time} | {ticker} | {mode} | {status} | {audit_id} | {order_id} | {idea_id} |".format(**row)
            )
    else:
        lines.append("| - | - | none | - | - | - | no audit events today |")

    lines.extend([
        "",
        "## Market Briefings",
        "",
        f"Briefings recorded today: {len(report['market_briefings'])}",
        "",
        "## Warnings",
        "",
    ])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def save_markdown(report: dict[str, Any], report_root: str = "reports/daily_activity") -> Path:
    out_dir = Path(report_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report['day']}-alpha-activity.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def print_summary(report: dict[str, Any], path: Path | None = None) -> None:
    summary = report["summary"]
    print(f"AlphaLabs Daily Activity Report - {report['day']}")
    print("=" * 48)
    print(f"Ideas generated: {summary['ideas_generated_today']}")
    print(f"Signals evaluated: {summary['signals_evaluated_today']}")
    print(f"Signals provisional: {summary['signals_still_provisional']}")
    print(f"Signals price_unavailable: {summary['signals_price_unavailable']}")
    print(f"Dry-run tests: {summary['dry_run_tests_today']}")
    print(f"Paper orders: {summary['paper_orders_today']}")
    print(f"Live orders: {summary['live_orders_today']}")
    print(f"Trades opened/closed: {summary['trades_opened_today']}/{summary['trades_closed_today']}")
    print(f"Orders placed: {summary['orders_placed_today']}")
    print(f"Execution audit events: {summary['execution_audit_events_today']}")
    print(f"Scanners ran: {summary['scanners_ran']}")
    print(f"Candidates found: {summary['candidates_found']}")
    print(f"Warnings: {len(report['warnings'])}")
    if report["warnings"]:
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    if path:
        print(f"Saved report: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a read-only AlphaLabs daily activity report.")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--date", help="Local date to report, YYYY-MM-DD. Defaults to today in America/Los_Angeles.")
    parser.add_argument("--out", default="reports/daily_activity", help="Directory for Markdown reports.")
    args = parser.parse_args(argv)
    load_dotenv()
    db_path = resolve_db_path(args.db)
    day = None if not args.date or args.date.lower() == "today" else date.fromisoformat(args.date)
    report = build_report(db_path, day)
    path = save_markdown(report, args.out)
    print_summary(report, path)
    return 0


def _empty_report(window: ReportWindow, warning: str) -> dict[str, Any]:
    return {
        "day": window.day.isoformat(),
        "window": {"start_utc": window.start_utc.isoformat(), "end_utc": window.end_utc.isoformat()},
        "summary": {
            "ideas_generated_today": 0,
            "signals_evaluated_today": 0,
            "signals_still_provisional": 0,
            "signals_price_unavailable": 0,
            "dry_run_tests_today": 0,
            "paper_orders_today": 0,
            "live_orders_today": 0,
            "real_money_orders_today": 0,
            "trades_opened_today": 0,
            "trades_closed_today": 0,
            "orders_placed_today": 0,
            "execution_audit_events_today": 0,
            "market_briefings_today": 0,
            "scanners_ran": 0,
            "candidates_found": 0,
            "ideas_persisted": 0,
            "evaluations_created": 0,
            "trades_linked": 0,
            "unlinked_trades_today": 0,
            "paper_orders_missing_audit": 0,
            "signals_missing_source_tags": 0,
            "signals_missing_alert_price": 0,
            "ideas_never_evaluated": 0,
            "live_order_path_present": False,
            "warning_count": 1,
        },
        "ideas": [],
        "trades_orders": [],
        "execution_audit": [],
        "decision_logs": [],
        "market_briefings": [],
        "scanner_runs": [],
        "warnings": [warning],
    }


def _rows(conn, sql: str, window: ReportWindow) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, (window.sql_start, window.sql_end)).fetchall()]


def _summary(
    ideas: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    evaluations_today: list[dict[str, Any]],
    briefings: list[dict[str, Any]],
    scanner_runs: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    paper_orders = [row for row in orders if int(row.get("dry_run") or 0) == 0]
    dry_audits = [row for row in audits if int(row.get("dry_run") or 0) == 1]
    env_base_url = os.getenv("ALPACA_PAPER_BASE_URL", "").strip()
    live_path_present = bool(env_base_url and env_base_url != "https://paper-api.alpaca.markets")
    return {
        "ideas_generated_today": len(ideas),
        "signals_evaluated_today": len([row for row in evaluations_today if row.get("evaluated_at")]),
        "signals_still_provisional": len([row for row in ideas if row.get("evaluation_status") == "provisional"]),
        "signals_price_unavailable": len([row for row in ideas if row.get("evaluation_status") == "price_unavailable"]),
        "dry_run_tests_today": len(dry_audits),
        "paper_orders_today": len(paper_orders),
        "live_orders_today": 0,
        "real_money_orders_today": 0,
        "trades_opened_today": len(trades),
        "trades_closed_today": len([row for row in trades if row.get("closed_at")]),
        "orders_placed_today": len(orders),
        "execution_audit_events_today": len(audits),
        "market_briefings_today": len(briefings),
        "scanners_ran": len(scanner_runs),
        "candidates_found": sum(row["candidates_found"] for row in scanner_runs),
        "ideas_persisted": sum(row["ideas_persisted"] for row in scanner_runs) or len(ideas),
        "evaluations_created": len([row for row in ideas if row.get("evaluation_id") is not None]),
        "trades_linked": len([row for row in trades if row.get("idea_id") is not None]),
        "unlinked_trades_today": len([row for row in trades if row.get("idea_id") is None]),
        "paper_orders_missing_audit": len(_paper_orders_missing_audit(paper_orders, audits)),
        "signals_missing_source_tags": len([row for row in ideas if not _source_tags(row)]),
        "signals_missing_alert_price": len([row for row in ideas if row.get("evaluation_id") and row.get("alert_price") is None]),
        "ideas_never_evaluated": len([row for row in ideas if row.get("evaluation_id") is None]),
        "live_order_path_present": live_path_present,
        "warning_count": len(warnings),
    }


def _warnings(
    ideas: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    scanner_runs: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    env_base_url = os.getenv("ALPACA_PAPER_BASE_URL", "").strip()
    if env_base_url and env_base_url != "https://paper-api.alpaca.markets":
        warnings.append("ALPACA_PAPER_BASE_URL is not the expected paper endpoint; live order path may be configured.")
    for row in trades:
        if row.get("idea_id") is None:
            warnings.append(f"trade {row.get('trade_id')} has no linked idea_id.")
    for row in orders:
        if row.get("trade_id") is None:
            warnings.append(f"order {row.get('order_row_id')} has no linked trade_id.")
    for row in _paper_orders_missing_audit([row for row in orders if int(row.get("dry_run") or 0) == 0], audits):
        warnings.append(f"paper order {row.get('alpaca_order_id') or row.get('order_row_id')} has no matching execution audit record.")
    for row in ideas:
        if not _source_tags(row):
            warnings.append(f"signal idea {row.get('idea_id')} ({row.get('ticker')}) has no source tags.")
        if row.get("evaluation_id") and row.get("alert_price") is None:
            warnings.append(f"signal idea {row.get('idea_id')} ({row.get('ticker')}) has no alert price due to provider failure or missing data.")
        if row.get("evaluation_id") is None:
            warnings.append(f"idea {row.get('idea_id')} ({row.get('ticker')}) was generated but never evaluated.")
    for row in scanner_runs:
        if row["candidates_found"] > 0 and row["ideas_persisted"] == 0:
            warnings.append(
                f"scanner {row['source']} ran with {row['candidates_found']} candidates but persisted zero ideas."
            )
    for row in trades:
        if row.get("idea_id") is not None:
            matching = [idea for idea in ideas if idea.get("idea_id") == row.get("idea_id")]
            if matching and matching[0].get("evaluation_id") is None:
                warnings.append(f"trade {row.get('trade_id')} is linked to idea {row.get('idea_id')} with no signal evaluation.")
    return warnings


def _paper_orders_missing_audit(orders: list[dict[str, Any]], audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit_order_ids = {str(row.get("alpaca_order_id")) for row in audits if row.get("alpaca_order_id")}
    audit_idea_tickers = {(row.get("idea_id"), row.get("ticker")) for row in audits}
    missing = []
    for order in orders:
        order_id = str(order.get("alpaca_order_id") or "")
        if order_id and order_id in audit_order_ids:
            continue
        if (order.get("idea_id"), order.get("ticker")) in audit_idea_tickers:
            continue
        missing.append(order)
    return missing


def _idea_row(row: dict[str, Any]) -> dict[str, str]:
    grade = row.get("final_grade") or row.get("provisional_grade") or "-"
    linked_order_id = row.get("alpaca_order_id") or "-"
    order_mode = _mode(row.get("order_dry_run"), row.get("order_status"), row.get("order_row_id"))
    return {
        "time": _local_time(row.get("idea_created_at")),
        "ticker": str(row.get("ticker") or "-"),
        "direction": str(row.get("bias") or row.get("direction") or "-"),
        "grade": str(grade),
        "source": _brief_source(row),
        "source_tags": ", ".join(_source_tags(row)) or "-",
        "status": str(row.get("evaluation_status") or "not_evaluated"),
        "move": _fmt_pct(row.get("move_after_pct")),
        "trade_id": _fmt_id(row.get("trade_id")),
        "order_id": str(linked_order_id),
        "order_mode": order_mode,
        "confidence_alpha": _confidence_alpha(row),
        "summary_text": _clean_text(row.get("catalyst") or row.get("thesis") or ""),
        "alert_price": _fmt_money(row.get("alert_price")),
        "price_after": _fmt_money(row.get("price_after")),
    }


def _trade_order_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "time": _local_time(row.get("opened_at")),
        "ticker": str(row.get("ticker") or "-"),
        "mode": "dry-run" if int(row.get("dry_run") or 0) else "paper",
        "trade_id": _fmt_id(row.get("trade_id")),
        "order_id": str(row.get("alpaca_order_id") or "-"),
        "linked_idea": _fmt_id(row.get("idea_id")),
        "status": str(row.get("trade_status") or row.get("order_status") or "-"),
    }


def _standalone_order_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "time": _local_time(row.get("order_created_at")),
        "ticker": str(row.get("ticker") or "-"),
        "mode": "dry-run" if int(row.get("dry_run") or 0) else "paper",
        "trade_id": "-",
        "order_id": str(row.get("alpaca_order_id") or row.get("order_row_id") or "-"),
        "linked_idea": "-",
        "status": str(row.get("order_status") or "-"),
    }


def _audit_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "time": _local_time(row.get("created_at")),
        "ticker": str(row.get("ticker") or "-"),
        "mode": "dry-run" if int(row.get("dry_run") or 0) else "paper",
        "status": str(row.get("status") or "-"),
        "audit_id": _fmt_id(row.get("id")),
        "order_id": str(row.get("alpaca_order_id") or "-"),
        "idea_id": _fmt_id(row.get("idea_id")),
    }


def _decision_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "time": _local_time(row.get("created_at")),
        "idea_id": _fmt_id(row.get("idea_id")),
        "action": str(row.get("action") or "-"),
    }


def _briefing_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "time": _local_time(row.get("created_at")),
        "type": str(row.get("briefing_type") or "-"),
        "generated_at": str(row.get("generated_at") or "-"),
    }


def _scanner_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _loads(row.get("payload_json"))
    top_reasons = payload.get("top_rejection_reasons") if isinstance(payload, dict) else []
    top_reason = "-"
    if isinstance(top_reasons, list) and top_reasons:
        first = top_reasons[0]
        if isinstance(first, dict):
            top_reason = f"{first.get('reason', '-')}: {first.get('count', 0)}"
    return {
        "time": _local_time(row.get("created_at")),
        "source": str(row.get("source") or "-"),
        "run_type": str(row.get("run_type") or "-"),
        "candidates_found": int((payload or {}).get("candidates_found") or 0),
        "ideas_persisted": int((payload or {}).get("ideas_persisted") or 0),
        "rejected": int((payload or {}).get("rejected") or 0),
        "skipped": int((payload or {}).get("skipped") or 0),
        "top_reason": top_reason,
        "note": str((payload or {}).get("note") or ""),
    }


def _status_line(label: str, value: int, expected_zero: bool) -> str:
    ok = value == 0 if expected_zero else True
    return f"{label}: {value} {'OK' if ok else 'WARNING'}"


def _mode(dry_run: Any, status: Any, row_id: Any) -> str:
    if row_id is None and not status:
        return "none"
    return "dry-run" if int(dry_run or 0) else "paper"


def _source_tags(row: dict[str, Any]) -> list[str]:
    for key in ("eval_source_tags", "idea_source_tags"):
        value = row.get(key)
        if isinstance(value, list):
            return [str(tag) for tag in value if str(tag).strip()]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                parsed = [value]
            if isinstance(parsed, list):
                return [str(tag) for tag in parsed if str(tag).strip()]
    return []


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _brief_source(row: dict[str, Any]) -> str:
    tags = _source_tags(row)
    if tags:
        return ", ".join(tags[:3])
    return str(row.get("source") or "-")


def _confidence_alpha(row: dict[str, Any]) -> str:
    confidence = row.get("confidence")
    alpha = row.get("alpha_composite")
    parts = []
    if isinstance(confidence, (int, float)):
        parts.append(f"confidence {confidence:.2f}")
    if isinstance(alpha, (int, float)):
        parts.append(f"alpha {alpha:.1f}")
    return " / ".join(parts) or "-"


def _fmt_pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}%"
    return "-"


def _fmt_money(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return "-"


def _fmt_id(value: Any) -> str:
    return str(value) if value is not None else "-"


def _local_time(value: Any) -> str:
    if not value:
        return "-"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TZ).strftime("%H:%M:%S")


def _clean_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text or "-"
    return text[: limit - 3] + "..."


_IDEAS_SQL = """
SELECT
  i.id AS idea_id,
  i.ticker,
  i.bias,
  i.confidence,
  i.thesis,
  i.catalyst,
  i.source,
  i.source_tags AS idea_source_tags,
  i.created_at AS idea_created_at,
  se.id AS evaluation_id,
  se.source_tags AS eval_source_tags,
  se.status AS evaluation_status,
  se.alert_price,
  se.price_after,
  se.move_after_pct,
  se.early_detection_score,
  se.provisional_grade,
  se.final_grade,
  t.id AS trade_id,
  t.alpha_composite,
  o.id AS order_row_id,
  o.alpaca_order_id,
  o.dry_run AS order_dry_run,
  o.status AS order_status
FROM alpha_ideas i
LEFT JOIN signal_evaluations se ON se.idea_id = i.id
LEFT JOIN trades t ON t.idea_id = i.id
LEFT JOIN orders o ON o.trade_id = t.id
WHERE datetime(i.created_at) >= datetime(?) AND datetime(i.created_at) < datetime(?)
ORDER BY datetime(i.created_at) ASC, i.id ASC
"""

_EVALUATIONS_TODAY_SQL = """
SELECT * FROM signal_evaluations
WHERE datetime(COALESCE(evaluated_at, created_at)) >= datetime(?)
  AND datetime(COALESCE(evaluated_at, created_at)) < datetime(?)
ORDER BY datetime(COALESCE(evaluated_at, created_at)) ASC, id ASC
"""

_TRADES_SQL = """
SELECT
  t.id AS trade_id,
  t.idea_id,
  t.ticker,
  t.status AS trade_status,
  t.dry_run,
  t.opened_at,
  t.closed_at,
  o.id AS order_row_id,
  o.alpaca_order_id,
  o.status AS order_status
FROM trades t
LEFT JOIN orders o ON o.trade_id = t.id
WHERE datetime(t.opened_at) >= datetime(?) AND datetime(t.opened_at) < datetime(?)
ORDER BY datetime(t.opened_at) ASC, t.id ASC
"""

_ORDERS_SQL = """
SELECT
  o.id AS order_row_id,
  o.trade_id,
  t.idea_id,
  o.ticker,
  o.status AS order_status,
  o.dry_run,
  o.alpaca_order_id,
  o.created_at AS order_created_at
FROM orders o
LEFT JOIN trades t ON t.id = o.trade_id
WHERE datetime(o.created_at) >= datetime(?) AND datetime(o.created_at) < datetime(?)
ORDER BY datetime(o.created_at) ASC, o.id ASC
"""

_AUDITS_SQL = """
SELECT * FROM execution_audit
WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
ORDER BY datetime(created_at) ASC, id ASC
"""

_DECISIONS_SQL = """
SELECT id, idea_id, action, created_at FROM decision_logs
WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
ORDER BY datetime(created_at) ASC, id ASC
"""

_BRIEFINGS_SQL = """
SELECT id, briefing_type, generated_at, created_at FROM market_briefings
WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
ORDER BY datetime(created_at) ASC, id ASC
"""

_SCANNER_RUNS_SQL = """
SELECT id, source, run_type, payload_json, created_at FROM scanner_runs
WHERE datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
ORDER BY datetime(created_at) ASC, id ASC
"""


if __name__ == "__main__":
    raise SystemExit(main())
