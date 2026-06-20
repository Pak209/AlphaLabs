"""Read-only evidence trace for a manual paper validation.

Checks the **machine-verifiable, DB-resident** portion of the manual-paper-validation
chain for a single manually-placed paper trade:

    idea -> analyst_assisted -> approval -> trade row -> orders row (Alpaca paper
         order id) -> submitted execution audit -> performance linkage

against the criteria in ``docs/MANUAL_PAPER_VALIDATION.md``. It accepts an
``--idea`` id or a ``--trade`` id, opens the SQLite DB **read-only**, and prints a
PASS / FAIL / SCHEMA_INCOMPATIBLE table plus a final ``db_evidence_passed`` boolean.

Scope and honest limits:
  * ``db_evidence_passed=true`` means ONLY that the machine-checkable, DB-resident
    evidence chain passed. It is deliberately NOT named ``validation_passed``: full
    manual-paper validation also requires external/environmental evidence that this
    module does not and cannot verify.
  * It opens the DB with ``mode=ro`` and never places, cancels, or modifies trades
    and performs no DB writes. It creates no files of its own.
  * Several documented criteria are **environmental**, not stored per-trade in this
    DB — e.g. that the Alpaca base URL is the paper endpoint (not live), that the
    scheduler stayed ``dry_run`` and placed nothing, and the same-DB / heartbeat
    proof. Those are NOT checked here; they are listed under "not machine-checked
    here" and must be confirmed with ``./ops paper-validation-status`` /
    ``./ops safety-status`` / ``./ops health``. A green table here is therefore a
    necessary, not sufficient, condition for full validation.
  * If a required table/view is missing or a required column is absent, the run
    reports ``SCHEMA_INCOMPATIBLE`` and ``db_evidence_passed=false`` — a schema
    problem is never silently treated as "data absent" and never raised as an
    unhandled exception.

Usage:
    python -m alpha_lab.paper_validation_evidence --idea 123
    python -m alpha_lab.paper_validation_evidence --trade 45 --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from alpha_lab.database import resolve_db_path

MISSING = "MISSING"

# Check result statuses.
PASS = "PASS"
FAIL = "FAIL"
SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"

# The idea status we expect after a manual paper order has executed (docs:
# "status transitioned to executed").
EXPECTED_IDEA_STATUS = "executed"

# Execution-audit statuses that represent an order actually sent to Alpaca.
SUBMITTED_STATUSES = {"submitted", "accepted", "filled", "partially_filled"}

# Required schema: object -> the columns this module actually reads. Validated up
# front so a missing table/view/column is an explicit SCHEMA_INCOMPATIBLE rather
# than a swallowed OperationalError or a misleading missing-data FAIL.
REQUIRED_SCHEMA: dict[str, set[str]] = {
    "alpha_ideas": {"id", "ticker", "asset_type", "status"},
    "trade_explanations": {"idea_id", "analyst_assisted", "created_at"},
    "approval_queue": {"idea_id", "status", "created_at", "reviewed_at"},
    "trades": {
        "id",
        "idea_id",
        "ticker",
        "asset_type",
        "side",
        "quantity",
        "entry_price",
        "status",
        "dry_run",
    },
    "orders": {"trade_id", "alpaca_order_id", "ticker", "side", "status", "dry_run"},
    "execution_audit": {
        "id",
        "idea_id",
        "status",
        "dry_run",
        "alpaca_order_id",
        "submitted_price",
        "rejection_reason",
        "created_at",
    },
    "training_rows": {
        "trade_id",
        "idea_id",
        "entry_price",
        "realized_return",
        "realized_pl",
        "unrealized_pl",
    },
}


def _connect_read_only(db_path: str) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _object_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    """Columns of a table OR view, or empty set if the object does not exist.

    ``name`` only ever comes from REQUIRED_SCHEMA keys (never user input), so the
    f-string is safe. PRAGMA table_info works for both tables and views.
    """
    try:
        rows = conn.execute(f"PRAGMA table_info({name})").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {r["name"] for r in rows}


def validate_schema(conn: sqlite3.Connection) -> list[str]:
    """Return a list of human-readable schema errors (empty when compatible)."""
    errors: list[str] = []
    for obj, required_cols in REQUIRED_SCHEMA.items():
        present = _object_columns(conn, obj)
        if not present:
            errors.append(f"missing required object: {obj}")
            continue
        missing = required_cols - present
        if missing:
            errors.append(f"{obj} missing columns: {', '.join(sorted(missing))}")
    return errors


def _row(conn: sqlite3.Connection, sql: str, params: tuple) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _rows(conn: sqlite3.Connection, sql: str, params: tuple) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def _norm_id(value: Any) -> str | None:
    """Normalize an order id: treat None/empty/whitespace as absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_positive(value: Any) -> bool:
    try:
        return value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def _is_submitted(audit: dict[str, Any]) -> bool:
    return str(audit.get("status", "")).lower() in SUBMITTED_STATUSES and not audit.get("dry_run")


def _pick_submitted_audit(audits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The most recent execution-audit row that represents a real submission."""
    return next((a for a in audits if _is_submitted(a)), None)


def _resolve_idea_id(
    conn: sqlite3.Connection, idea_id: int | None, trade_id: int | None
) -> int | None:
    if idea_id is not None:
        return idea_id
    if trade_id is not None:
        row = _row(conn, "SELECT idea_id FROM trades WHERE id = ?", (trade_id,))
        if row and row["idea_id"] is not None:
            return int(row["idea_id"])
    return None


def gather_evidence(
    *,
    idea_id: int | None = None,
    trade_id: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Collect the evidence chain for an idea (or the idea behind a trade)."""
    resolved = resolve_db_path(db_path)
    conn = _connect_read_only(resolved)
    try:
        schema_errors = validate_schema(conn)
        evidence: dict[str, Any] = {
            "db_path": str(Path(resolved).expanduser().resolve()),
            "requested": {"idea_id": idea_id, "trade_id": trade_id},
            "schema_errors": schema_errors,
            "schema_compatible": not schema_errors,
        }
        # Fail closed before touching business data when the schema is incompatible.
        if schema_errors:
            evidence["idea_id"] = None
            evidence["idea"] = None
            return evidence

        target_idea = _resolve_idea_id(conn, idea_id, trade_id)
        evidence["idea_id"] = target_idea
        if target_idea is None:
            evidence["idea"] = None
            return evidence

        idea = _row(conn, "SELECT * FROM alpha_ideas WHERE id = ?", (target_idea,))
        evidence["idea"] = dict(idea) if idea else None

        explanation = _row(
            conn,
            "SELECT analyst_assisted, created_at FROM trade_explanations "
            "WHERE idea_id = ? ORDER BY id DESC LIMIT 1",
            (target_idea,),
        )
        evidence["analyst_assisted"] = bool(explanation["analyst_assisted"]) if explanation else None

        approval = _row(conn, "SELECT * FROM approval_queue WHERE idea_id = ?", (target_idea,))
        evidence["approval"] = dict(approval) if approval else None

        # Prefer the trade tied to the requested trade_id; otherwise the latest.
        if trade_id is not None:
            trade = _row(conn, "SELECT * FROM trades WHERE id = ?", (trade_id,))
        else:
            trade = _row(
                conn, "SELECT * FROM trades WHERE idea_id = ? ORDER BY id DESC LIMIT 1", (target_idea,)
            )
        evidence["trade"] = dict(trade) if trade else None
        resolved_trade_id = int(trade["id"]) if trade else None

        # Count paper (non-dry_run) trades for the idea so "exactly one" can be
        # asserted; more than one makes the manual trade ambiguous.
        paper_trades = _rows(
            conn,
            "SELECT id FROM trades WHERE idea_id = ? AND COALESCE(dry_run, 0) = 0",
            (target_idea,),
        )
        evidence["paper_trade_count"] = len(paper_trades)

        audits = [
            dict(r)
            for r in _rows(
                conn,
                "SELECT id, status, dry_run, alpaca_order_id, submitted_price, rejection_reason, "
                "created_at FROM execution_audit WHERE idea_id = ? ORDER BY id DESC",
                (target_idea,),
            )
        ]
        evidence["execution_audit"] = audits

        submitted_audit = _pick_submitted_audit(audits)
        evidence["submitted_audit"] = submitted_audit
        evidence["submitted_audit_count"] = sum(1 for a in audits if _is_submitted(a))

        # Orders row is REQUIRED — an audit id may never substitute for it. Count
        # qualifying (non-dry_run) order rows for the selected trade; the order id
        # is only meaningful when exactly one qualifies.
        order_rows: list[dict[str, Any]] = []
        if resolved_trade_id is not None:
            order_rows = [
                dict(r)
                for r in _rows(
                    conn,
                    "SELECT id, alpaca_order_id, status FROM orders "
                    "WHERE trade_id = ? AND COALESCE(dry_run, 0) = 0 ORDER BY id DESC",
                    (resolved_trade_id,),
                )
            ]
        evidence["qualifying_order_count"] = len(order_rows)
        order_id_from_orders = (
            _norm_id(order_rows[0]["alpaca_order_id"]) if len(order_rows) == 1 else None
        )
        # Status of the single qualifying order (only meaningful when exactly one
        # qualifies); a canceled/rejected/expired/blank status must not satisfy the
        # chain even if an order id is present.
        order_status = order_rows[0].get("status") if len(order_rows) == 1 else None
        evidence["order_status"] = order_status
        evidence["order_status_submitted"] = (
            str(order_status).strip().lower() in SUBMITTED_STATUSES
            if order_status is not None
            else False
        )
        order_id_from_audit = (
            _norm_id(submitted_audit.get("alpaca_order_id")) if submitted_audit else None
        )
        evidence["order_id_from_orders"] = order_id_from_orders
        evidence["order_id_from_audit"] = order_id_from_audit
        # Reported order id comes from the orders row only (no audit fallback).
        evidence["alpaca_order_id"] = order_id_from_orders

        # Performance linkage via the training_rows view. NOTE: training_rows does
        # not expose quantity, so quantity is asserted on the trades row instead.
        perf = None
        if resolved_trade_id is not None:
            perf = _row(
                conn,
                "SELECT trade_id, idea_id, entry_price, realized_return, realized_pl, unrealized_pl "
                "FROM training_rows WHERE trade_id = ?",
                (resolved_trade_id,),
            )
        evidence["performance"] = dict(perf) if perf else None

        return evidence
    finally:
        conn.close()


# Documented criteria that cannot be verified from this database alone. Surfaced
# so a green table here is never mistaken for full validation.
NOT_MACHINE_CHECKED = [
    "Alpaca base URL is the paper endpoint (not live) — ./ops paper-validation-status",
    "Scheduler stayed dry_run and placed nothing — ./ops safety-status",
    "Same-DB proof + fresh heartbeat (no split-brain) — ./ops health",
    "Stop/target populated from a live price (only entry_price is stored here) — dashboard",
    "training_rows does not expose quantity; quantity is asserted on the trades row only",
]


def evaluate(evidence: dict[str, Any]) -> dict[str, Any]:
    """Apply the docs/MANUAL_PAPER_VALIDATION.md machine-checkable criteria."""
    schema_compatible = bool(evidence.get("schema_compatible", True))
    schema_errors = evidence.get("schema_errors") or []
    idea = evidence.get("idea")
    approval = evidence.get("approval")
    trade = evidence.get("trade")
    analyst_assisted = evidence.get("analyst_assisted")
    submitted_audit = evidence.get("submitted_audit")
    approval_status = approval.get("status") if approval else None
    perf = evidence.get("performance")
    perf_linked = bool(perf and perf.get("entry_price") is not None)

    idea_asset = idea.get("asset_type") if idea else None
    trade_asset = trade.get("asset_type") if trade else None
    idea_status = idea.get("status") if idea else None
    trade_qty = trade.get("quantity") if trade else None
    trade_entry = trade.get("entry_price") if trade else None

    order_orders = evidence.get("order_id_from_orders")
    order_audit = evidence.get("order_id_from_audit")
    order_present = bool(order_orders) and bool(order_audit)
    order_match = bool(order_orders) and bool(order_audit) and order_orders == order_audit

    paper_trade_count = evidence.get("paper_trade_count")
    submitted_audit_count = evidence.get("submitted_audit_count")
    qualifying_order_count = evidence.get("qualifying_order_count")

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str, *, schema_dependent: bool = True) -> None:
        if schema_dependent and not schema_compatible:
            status = SCHEMA_INCOMPATIBLE
        else:
            status = PASS if passed else FAIL
        checks.append(
            {"check": name, "status": status, "passed": status == PASS, "detail": detail}
        )

    add(
        "schema compatible (required tables/views/columns present)",
        schema_compatible,
        "ok" if schema_compatible else "; ".join(schema_errors) or "incompatible",
        schema_dependent=False,
    )
    add("idea exists", idea is not None, f"idea_id={evidence.get('idea_id') or MISSING}")
    add(
        "analyst_assisted (approval gate engaged)",
        analyst_assisted is True,
        "analyst_assisted="
        + ("true" if analyst_assisted else "false" if analyst_assisted is False else MISSING),
    )
    add(
        "asset class is equity (first validation only)",
        idea_asset == "equity" and (trade is None or trade_asset == "equity"),
        f"idea={idea_asset or MISSING} trade={trade_asset or MISSING}",
    )
    add(
        "approval reviewed_at present (human reviewed)",
        bool(approval and approval.get("reviewed_at")),
        f"reviewed_at={approval.get('reviewed_at') if approval else MISSING}",
    )
    add(
        "approval_status == approved",
        approval_status == "approved",
        f"approval_status={approval_status or MISSING}",
    )
    add(
        "trade row linked to idea",
        bool(trade and trade.get("idea_id") == evidence.get("idea_id")),
        f"trade_id={trade.get('id') if trade else MISSING}",
    )
    add(
        "trade is paper (not dry_run)",
        bool(trade and not trade.get("dry_run")),
        f"dry_run={trade.get('dry_run') if trade else MISSING}",
    )
    add(
        f"idea status == {EXPECTED_IDEA_STATUS}",
        idea_status == EXPECTED_IDEA_STATUS,
        f"idea_status={idea_status or MISSING}",
    )
    add(
        "trade quantity and entry_price are present and positive",
        _is_positive(trade_qty) and _is_positive(trade_entry),
        f"quantity={trade_qty if trade_qty is not None else MISSING} "
        f"entry_price={trade_entry if trade_entry is not None else MISSING}",
    )
    add(
        "exactly one paper trade for the idea",
        paper_trade_count == 1,
        f"paper_trades={paper_trade_count if paper_trade_count is not None else MISSING}",
    )
    add(
        "exactly one qualifying order row (orders table)",
        qualifying_order_count == 1,
        f"qualifying_orders={qualifying_order_count if qualifying_order_count is not None else MISSING}",
    )
    add(
        "exactly one submitted execution audit (idea)",
        submitted_audit_count == 1,
        f"submitted_audits={submitted_audit_count if submitted_audit_count is not None else MISSING}",
    )
    add(
        "Alpaca order id present in orders and audit",
        order_present,
        f"orders={order_orders or MISSING} audit={order_audit or MISSING}",
    )
    add(
        "order id matches (orders == submitted audit)",
        order_match,
        f"orders={order_orders or MISSING} audit={order_audit or MISSING}",
    )
    order_status = evidence.get("order_status")
    add(
        "orders.status is a submitted paper-order status",
        bool(evidence.get("order_status_submitted")),
        f"orders.status={order_status if order_status not in (None, '') else MISSING}",
    )
    add(
        "execution audit entry exists (submitted)",
        submitted_audit is not None,
        f"submitted_audit_id={submitted_audit['id'] if submitted_audit else MISSING}",
    )
    add(
        "performance linkage exists",
        perf_linked,
        f"entry_price={perf.get('entry_price') if perf else MISSING}",
    )

    passed = schema_compatible and all(c["passed"] for c in checks)
    return {
        "checks": checks,
        "db_evidence_passed": passed,
        "schema_compatible": schema_compatible,
        "not_machine_checked": list(NOT_MACHINE_CHECKED),
    }


def _approval_summary(evidence: dict[str, Any]) -> str:
    """Present approval state (NOT a proven historical transition).

    The approval_queue stores the current status plus timestamps; it does not
    retain a transition history, so this only reports present state.
    """
    idea = evidence.get("idea") or {}
    approval = evidence.get("approval") or {}
    queued = approval.get("created_at") or MISSING
    reviewed = approval.get("reviewed_at") or "not reviewed"
    approval_status = approval.get("status") or MISSING
    idea_status = idea.get("status") or MISSING
    return (
        f"status={approval_status}; created_at={queued}; reviewed_at={reviewed}; "
        f"idea.status={idea_status}"
    )


def render_text(evidence: dict[str, Any], verdict: dict[str, Any]) -> str:
    idea = evidence.get("idea")
    trade = evidence.get("trade")
    lines: list[str] = []
    lines.append("== Manual paper validation evidence (read-only) ==")
    lines.append("  (machine-checkable DB-resident evidence only; see disclaimers below)")
    lines.append("")
    if not verdict.get("schema_compatible", True):
        lines.append("  SCHEMA INCOMPATIBLE — required tables/views/columns missing:")
        for err in evidence.get("schema_errors") or []:
            lines.append(f"    - {err}")
        lines.append("  db_evidence_passed=false")
        return "\n".join(lines)
    if idea is None:
        req = evidence.get("requested", {})
        lines.append(
            f"  No idea found for idea_id={req.get('idea_id')} trade_id={req.get('trade_id')}."
        )
        lines.append("  db_evidence_passed=false")
        return "\n".join(lines)

    aa = evidence.get("analyst_assisted")
    lines.append(f"  idea id:            {idea.get('id')}")
    lines.append(f"  ticker:             {idea.get('ticker')}")
    lines.append(f"  asset class:        {idea.get('asset_type') or MISSING}")
    lines.append(
        "  analyst_assisted:   " + ("true" if aa else "false" if aa is False else MISSING)
    )
    approval = evidence.get("approval") or {}
    lines.append(f"  approval_status:    {approval.get('status') or MISSING}")
    lines.append(f"  approval state:     {_approval_summary(evidence)}")
    lines.append(f"  trade id:           {trade.get('id') if trade else MISSING}")
    lines.append(f"  alpaca order id:    {evidence.get('alpaca_order_id') or MISSING}")
    audits = evidence.get("execution_audit") or []
    lines.append("  execution audit:    " + (f"{len(audits)} entr(y/ies)" if audits else MISSING))
    perf = evidence.get("performance")
    lines.append(
        "  performance linkage: "
        + (f"entry_price={perf.get('entry_price')}" if perf else MISSING)
    )
    lines.append("")
    lines.append(f"  {'Check':52} {'Result':20} Detail")
    lines.append(f"  {'-' * 52} {'-' * 20} {'-' * 12}")
    for c in verdict["checks"]:
        lines.append(f"  {c['check']:52} {c['status']:20} {c['detail']}")
    lines.append("")
    lines.append("  Not machine-checked here (confirm via ./ops):")
    for item in verdict.get("not_machine_checked", []):
        lines.append(f"    - {item}")
    lines.append("")
    lines.append(f"  db_evidence_passed={'true' if verdict['db_evidence_passed'] else 'false'}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--idea", type=int, help="idea id to trace")
    group.add_argument("--trade", type=int, help="trade id to trace (resolves its idea)")
    parser.add_argument("--db", default=None, help="explicit DB path (defaults to resolver)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = gather_evidence(idea_id=args.idea, trade_id=args.trade, db_path=args.db)
    if evidence.get("idea") is not None or not evidence.get("schema_compatible", True):
        verdict = evaluate(evidence)
    else:
        verdict = {
            "checks": [],
            "db_evidence_passed": False,
            "schema_compatible": True,
            "not_machine_checked": list(NOT_MACHINE_CHECKED),
        }
    if args.json:
        print(json.dumps({**evidence, **verdict}, indent=2, sort_keys=True, default=str))
    else:
        print(render_text(evidence, verdict))
    return 0 if verdict["db_evidence_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
