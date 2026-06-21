from __future__ import annotations

import sqlite3

import pytest

from alpha_lab.database import init_db
from alpha_lab.paper_validation_evidence import (
    PASS,
    SCHEMA_INCOMPATIBLE,
    _approval_summary,
    evaluate,
    gather_evidence,
    main,
)

# Canonical check names (kept in one place so a rename only edits here).
C_SCHEMA = "schema compatible (required tables/views/columns present)"
C_IDEA = "idea exists"
C_ANALYST = "analyst_assisted (approval gate engaged)"
C_EQUITY = "asset class is equity (first validation only)"
C_REVIEWED = "approval reviewed_at present (human reviewed)"
C_APPROVED = "approval_status == approved"
C_TRADE_LINKED = "trade row linked to idea"
C_TRADE_PAPER = "trade is paper (not dry_run)"
C_IDEA_STATUS = "idea status == executed"
C_TRADE_FIELDS = "trade quantity and entry_price are present and positive"
C_ONE_TRADE = "exactly one paper trade for the idea"
C_ONE_ORDER = "exactly one qualifying order row (orders table)"
C_ONE_AUDIT = "exactly one submitted execution audit (idea)"
C_ORDER_PRESENT = "Alpaca order id present in orders and audit"
C_ORDER_MATCH = "order id matches (orders == submitted audit)"
C_ORDER_STATUS = "orders.status is a submitted paper-order status"
C_AUDIT_SUBMITTED = "execution audit entry exists (submitted)"
C_PERF = "performance linkage exists"


def _exec(db: str, sql: str, params: tuple = ()) -> int:
    conn = sqlite3.connect(db)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _seed_idea(
    db: str,
    ticker: str = "AAPL",
    asset_type: str = "equity",
    status: str = "executed",
) -> int:
    return _exec(
        db,
        "INSERT INTO alpha_ideas (ticker, asset_type, bias, confidence, timeframe, "
        "thesis, source, status, timestamp) "
        "VALUES (?, ?, 'long', 0.8, 'swing', 'thesis', 'manual', ?, ?)",
        (ticker, asset_type, status, "2026-06-19T10:00:00-07:00"),
    )


def _seed_explanation(db: str, idea_id: int, analyst_assisted: int = 1) -> int:
    return _exec(
        db,
        "INSERT INTO trade_explanations (idea_id, explanation_json, analyst_assisted) "
        "VALUES (?, '{}', ?)",
        (idea_id, analyst_assisted),
    )


def _seed_approval(
    db: str, idea_id: int, status: str = "approved", reviewed: bool = True
) -> int:
    return _exec(
        db,
        "INSERT INTO approval_queue (idea_id, status, created_at, reviewed_at) "
        "VALUES (?, ?, ?, ?)",
        (
            idea_id,
            status,
            "2026-06-19T10:01:00-07:00",
            "2026-06-19T10:05:00-07:00" if reviewed else None,
        ),
    )


def _seed_trade(
    db: str,
    idea_id: int,
    *,
    dry_run: int = 0,
    quantity: float | None = 10,
    entry_price: float | None = 195.5,
    asset_type: str = "equity",
) -> int:
    return _exec(
        db,
        "INSERT INTO trades (idea_id, ticker, side, quantity, entry_price, status, "
        "dry_run, asset_type) VALUES (?, 'AAPL', 'buy', ?, ?, 'open', ?, ?)",
        (idea_id, quantity, entry_price, dry_run, asset_type),
    )


def _seed_audit(
    db: str,
    idea_id: int,
    *,
    status: str = "submitted",
    dry_run: int = 0,
    order_id: str = "alpaca-paper-123",
) -> int:
    return _exec(
        db,
        "INSERT INTO execution_audit (idea_id, ticker, status, alpaca_order_id, dry_run) "
        "VALUES (?, 'AAPL', ?, ?, ?)",
        (idea_id, status, order_id, dry_run),
    )


def _seed_order(
    db: str,
    trade_id: int,
    order_id: str = "alpaca-paper-123",
    dry_run: int = 0,
    status: str = "submitted",
) -> int:
    return _exec(
        db,
        "INSERT INTO orders (trade_id, alpaca_order_id, ticker, side, payload_json, "
        "status, dry_run) VALUES (?, ?, 'AAPL', 'buy', '{}', ?, ?)",
        (trade_id, order_id, status, dry_run),
    )


@pytest.fixture
def db(tmp_path) -> str:
    path = str(tmp_path / "alpha_lab.sqlite3")
    init_db(path)
    return path


def _seed_full_pass(db: str) -> tuple[int, int]:
    idea_id = _seed_idea(db, status="executed")
    _seed_explanation(db, idea_id, analyst_assisted=1)
    _seed_approval(db, idea_id, status="approved", reviewed=True)
    trade_id = _seed_trade(db, idea_id, dry_run=0, entry_price=195.5)
    _seed_audit(db, idea_id, status="submitted", dry_run=0)
    _seed_order(db, trade_id)
    return idea_id, trade_id


def _check(verdict: dict, name: str) -> dict:
    for c in verdict["checks"]:
        if c["check"] == name:
            return c
    raise AssertionError(f"no such check: {name}")


def _passed(verdict: dict, name: str) -> bool:
    return _check(verdict, name)["passed"]


# --- happy path ------------------------------------------------------------


def test_full_chain_passes(db):
    idea_id, _ = _seed_full_pass(db)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is True, verdict["checks"]
    assert all(c["status"] == PASS for c in verdict["checks"])


def test_resolves_idea_from_trade(db):
    idea_id, trade_id = _seed_full_pass(db)
    evidence = gather_evidence(trade_id=trade_id, db_path=db)
    assert evidence["idea_id"] == idea_id
    assert evidence["trade"]["id"] == trade_id
    assert evaluate(evidence)["db_evidence_passed"] is True


def test_main_exits_zero_on_full_pass(db):
    idea_id, _ = _seed_full_pass(db)
    assert main(["--idea", str(idea_id), "--db", db]) == 0


def test_main_exits_zero_with_json(db):
    idea_id, _ = _seed_full_pass(db)
    assert main(["--idea", str(idea_id), "--db", db, "--json"]) == 0


def test_full_pass_still_lists_not_machine_checked(db):
    idea_id, _ = _seed_full_pass(db)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    # A green table must still advertise the environmental criteria it cannot prove.
    assert verdict["not_machine_checked"]
    assert any("paper endpoint" in s for s in verdict["not_machine_checked"])
    assert any("dry_run" in s for s in verdict["not_machine_checked"])


# --- missing business data --------------------------------------------------


def test_missing_idea_fails(db):
    assert main(["--idea", "999", "--db", db]) == 1
    evidence = gather_evidence(idea_id=999, db_path=db)
    assert evidence["idea"] is None
    assert evidence["schema_compatible"] is True


def test_not_analyst_assisted_fails(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id, analyst_assisted=0)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ANALYST)


def test_missing_approval_fails(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_APPROVED)


def test_unreviewed_approval_fails(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id, status="needs_review", reviewed=False)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_REVIEWED)


def test_idea_status_not_executed_fails(db):
    idea_id = _seed_idea(db, status="approved")
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_IDEA_STATUS)


def test_dry_run_trade_fails(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, dry_run=1)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id, dry_run=1)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_TRADE_PAPER)


def test_missing_entry_price_fails_fields_and_performance(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, entry_price=None)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_TRADE_FIELDS)
    assert not _passed(verdict, C_PERF)


def test_zero_quantity_fails_trade_fields(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, quantity=0)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_TRADE_FIELDS)


# --- equity-only gate -------------------------------------------------------


def test_non_equity_idea_fails(db):
    idea_id = _seed_idea(db, ticker="BTCUSD", asset_type="crypto")
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, asset_type="crypto")
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_EQUITY)


def test_non_equity_trade_fails(db):
    idea_id = _seed_idea(db, asset_type="equity")
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, asset_type="option")
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_EQUITY)


# --- order-id integrity / orders-row requirement ----------------------------


def test_missing_orders_row_fails(db):
    # Submitted audit with an order id, but NO orders row at all. An audit id may
    # never substitute for a real orders row.
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="audit-only-99")
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    # No orders row -> no reported order id (no audit fallback).
    assert evidence["alpaca_order_id"] is None
    assert evidence["qualifying_order_count"] == 0
    verdict = evaluate(evidence)
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ONE_ORDER)
    assert not _passed(verdict, C_ORDER_PRESENT)


def test_empty_order_id_fails_present(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="")
    _seed_order(db, trade_id, order_id="")
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ORDER_PRESENT)


def test_mismatched_order_ids_fail_match(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="audit-AAA")
    _seed_order(db, trade_id, order_id="orders-BBB")
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ORDER_MATCH)


@pytest.mark.parametrize("bad_status", ["canceled", "cancelled", "rejected", "expired",
                                        "failed", "error", ""])
def test_non_submitted_order_status_fails(db, bad_status):
    # A real order id + matching audit, but the orders row never reached a
    # submitted/accepted/filled state -> the DB evidence chain must fail.
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="alpaca-paper-123")
    _seed_order(db, trade_id, order_id="alpaca-paper-123", status=bad_status)
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    assert evidence["order_status_submitted"] is False
    verdict = evaluate(evidence)
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ORDER_STATUS)


@pytest.mark.parametrize("ok_status", ["submitted", "accepted", "filled",
                                       "partially_filled", "FILLED"])
def test_submitted_order_status_passes(db, ok_status):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id, dry_run=0, entry_price=195.5)
    _seed_audit(db, idea_id, status="submitted", dry_run=0)
    _seed_order(db, trade_id, status=ok_status)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert _passed(verdict, C_ORDER_STATUS)
    assert verdict["db_evidence_passed"] is True, verdict["checks"]


def test_no_audit_fallback_for_order_id(db):
    # With a submitted audit but no orders row, the reported order id must stay
    # None and the qualifying-order check must fail (no fallback to the audit).
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="audit-order-99")
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    assert evidence["order_id_from_orders"] is None
    assert evidence["alpaca_order_id"] is None


def test_non_submitted_audit_order_id_does_not_satisfy_chain(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    # A rejected (non-submitted) audit carries an order id, but no submission exists.
    _seed_audit(db, idea_id, status="rejected", dry_run=0, order_id="ghost-123")
    _seed_order(db, trade_id, order_id="ghost-123")
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    assert evidence["order_id_from_audit"] is None
    verdict = evaluate(evidence)
    assert not _passed(verdict, C_ORDER_PRESENT)
    assert not _passed(verdict, C_AUDIT_SUBMITTED)


def test_dry_run_audit_not_counted_as_submitted(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, status="submitted", dry_run=1)
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_AUDIT_SUBMITTED)


def test_multiple_paper_trades_fail_single_trade(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    t1 = _seed_trade(db, idea_id)
    _seed_trade(db, idea_id)  # second paper trade for the same idea -> ambiguous
    _seed_audit(db, idea_id)
    _seed_order(db, t1)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ONE_TRADE)


def test_multiple_qualifying_orders_fail_single_order(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id)
    _seed_order(db, trade_id)
    _seed_order(db, trade_id)  # second non-dry_run order row for same trade
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    assert evidence["qualifying_order_count"] == 2
    verdict = evaluate(evidence)
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ONE_ORDER)


def test_multiple_submitted_audits_fail_single_audit(db):
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    trade_id = _seed_trade(db, idea_id)
    _seed_audit(db, idea_id, order_id="alpaca-paper-123")
    _seed_audit(db, idea_id, order_id="alpaca-paper-123")  # two submissions
    _seed_order(db, trade_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_ONE_AUDIT)


# --- approval wording (no claimed historical transition) --------------------


def test_approval_summary_does_not_claim_historical_transition(db):
    idea_id, _ = _seed_full_pass(db)
    evidence = gather_evidence(idea_id=idea_id, db_path=db)
    summary = _approval_summary(evidence)
    # Reports present state only; must not assert a proven needs_review -> approved
    # transition that the schema cannot prove.
    assert "needs_review" not in summary
    assert "->" not in summary
    verdict = evaluate(evidence)
    assert not any("needs_review" in c["check"] for c in verdict["checks"])
    assert not any("->" in c["check"] for c in verdict["checks"])


# --- schema incompatibility -------------------------------------------------


def test_missing_table_reports_schema_incompatible(tmp_path):
    # A DB that is missing the required tables/views entirely.
    path = str(tmp_path / "bare.sqlite3")
    _exec(
        path,
        "CREATE TABLE alpha_ideas (id INTEGER PRIMARY KEY, ticker TEXT, "
        "asset_type TEXT, status TEXT)",
    )
    _exec(path, "INSERT INTO alpha_ideas (id, ticker, asset_type, status) "
                "VALUES (1, 'AAPL', 'equity', 'executed')")
    evidence = gather_evidence(idea_id=1, db_path=path)
    assert evidence["schema_compatible"] is False
    assert evidence["schema_errors"]
    verdict = evaluate(evidence)
    assert verdict["db_evidence_passed"] is False
    # Schema-dependent checks surface SCHEMA_INCOMPATIBLE, not a quiet FAIL/PASS.
    assert _check(verdict, C_PERF)["status"] == SCHEMA_INCOMPATIBLE
    assert not _passed(verdict, C_SCHEMA)


def test_missing_column_reports_schema_incompatible(db):
    # All required objects exist, but one is missing a required column.
    _exec(db, "ALTER TABLE execution_audit DROP COLUMN submitted_price")
    evidence = gather_evidence(idea_id=1, db_path=db)
    assert evidence["schema_compatible"] is False
    assert any("execution_audit" in e and "submitted_price" in e
               for e in evidence["schema_errors"])
    verdict = evaluate(evidence)
    assert verdict["db_evidence_passed"] is False
    assert not _passed(verdict, C_SCHEMA)


def test_schema_incompatible_main_exits_one(tmp_path):
    path = str(tmp_path / "bare2.sqlite3")
    _exec(
        path,
        "CREATE TABLE alpha_ideas (id INTEGER PRIMARY KEY, ticker TEXT, "
        "asset_type TEXT, status TEXT)",
    )
    _exec(path, "INSERT INTO alpha_ideas (id, ticker, asset_type, status) "
                "VALUES (1, 'AAPL', 'equity', 'executed')")
    assert main(["--idea", "1", "--db", path]) == 1


def test_missing_db_raises(tmp_path):
    missing = str(tmp_path / "nope.sqlite3")
    with pytest.raises(FileNotFoundError):
        gather_evidence(idea_id=1, db_path=missing)


# --- incomplete documented criteria ----------------------------------------


def test_incomplete_chain_cannot_claim_full_validation(db):
    # Idea + approval only: no trade, audit, order, or performance. The module
    # must report many explicit FAILs and a false overall result rather than
    # silently passing on the partial evidence it does have.
    idea_id = _seed_idea(db)
    _seed_explanation(db, idea_id)
    _seed_approval(db, idea_id)
    verdict = evaluate(gather_evidence(idea_id=idea_id, db_path=db))
    assert verdict["db_evidence_passed"] is False
    for name in (
        C_TRADE_LINKED,
        C_TRADE_PAPER,
        C_ONE_TRADE,
        C_ONE_ORDER,
        C_ORDER_PRESENT,
        C_ORDER_STATUS,
        C_AUDIT_SUBMITTED,
        C_PERF,
    ):
        assert not _passed(verdict, name), name
