"""
alpha_lab/waterfall.py — the rejection-waterfall aggregation (read-only).

Extracted verbatim from AlphaLabService.rejection_waterfall (Phase 2 PR1) and
decomposed into load / parse / aggregate / finalize / format helpers (PR2, see
docs/PHASE2_PLAN.md). Same inputs, same output shape, same gate names — the
output contract is pinned by alpha_lab/tests/test_waterfall_golden.py, and the
service keeps a delegating method so every caller is unchanged.

Like the sibling diagnostics modules (replay/attribution/outcomes/portfolio):
SELECTs only; never creates ideas, decisions, orders, trades, or approvals.

All helpers are module-private: build_rejection_waterfall(db_path, limit) is
the only public surface, and only _load_inputs touches the database — every
helper after it is a pure function of already-loaded rows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .database import connect

# Canonical gate names for legacy free-text rejection clauses, so the
# waterfall can aggregate history recorded before structured gate telemetry
# existed. Matched by substring against each ';'-separated clause.
LEGACY_CLAUSE_GATES: tuple[tuple[str, str], ...] = (
    ("confidence ", "confidence"),
    ("bias is not actionable", "bias_actionable"),
    ("bearish short entries are disabled", "short_allowed"),
    ("does not support shorting crypto", "crypto_long_only"),
    ("not in approved watchlist", "watchlist"),
    ("market is closed", "market_open"),
    ("max open positions", "max_open_positions"),
    ("duplicate position", "duplicate_position"),
    ("max trades per day", "max_trades_per_day"),
    ("max daily drawdown", "daily_drawdown"),
    ("alpha gate:", "alpha_composite_tier"),
    ("alpha_tier must", "alpha_composite_tier"),
    ("alpha_composite must", "alpha_composite_tier"),
    ("human approval", "human_approval"),
    ("llm-assisted signal was", "human_approval"),
    ("latest price is required for paper short sizing", "short_sizing_price"),
    ("option signal is missing a selected contract", "option_contract_selected"),
    ("no tradeable option contract", "option_contract_selected"),
    ("option contract cost is unavailable", "option_cost_known"),
    ("exceeds per-trade budget", "option_cost_within_budget"),
    ("paper account equity is unavailable", "equity_available"),
)

# Risk-engine outcomes that mean the attempt was NOT a rejection.
_ACCEPTED_STATUSES = frozenset({"dry_run", "submitted"})


# ─── Load (the only DB access) ────────────────────────────────────────────────

@dataclass(frozen=True)
class _WaterfallInputs:
    audit_rows: list[dict[str, Any]]
    audit_total: int
    ideas_total: int
    trades_paper: int
    scanner_rows: list[dict[str, Any]]


def _load_inputs(db_path: str, limit: int) -> _WaterfallInputs:
    with connect(db_path) as conn:
        audit_rows = [dict(r) for r in conn.execute(
            """
            SELECT status, dry_run, rejection_reason, payload_json
            FROM execution_audit ORDER BY datetime(created_at) DESC, id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()]
        audit_total = int(conn.execute("SELECT COUNT(*) FROM execution_audit").fetchone()[0])
        ideas_total = int(conn.execute("SELECT COUNT(*) FROM alpha_ideas").fetchone()[0])
        trades_paper = int(conn.execute("SELECT COUNT(*) FROM trades WHERE dry_run = 0").fetchone()[0])
        scanner_rows = [dict(r) for r in conn.execute(
            "SELECT payload_json FROM scanner_runs ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()]
    return _WaterfallInputs(audit_rows, audit_total, ideas_total, trades_paper, scanner_rows)


# ─── Parse (pre-idea scanner accounting) ──────────────────────────────────────

def _parse_scanner_runs(scanner_rows: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
    candidates_scanned = 0
    pre_idea_skips: dict[str, int] = {}
    for row in scanner_rows:
        try:
            summary = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        candidates_scanned += int(summary.get("candidates_found") or 0)
        for item in summary.get("top_rejection_reasons") or []:
            reason = str(item.get("reason") or "").strip()
            if reason:
                pre_idea_skips[reason] = pre_idea_skips.get(reason, 0) + int(item.get("count") or 0)
    return candidates_scanned, pre_idea_skips


# ─── Aggregate (per-gate buckets over audit rows) ─────────────────────────────

def _near_miss(record: dict[str, Any]) -> bool:
    observed, threshold = record.get("observed"), record.get("threshold")
    comparator = str(record.get("comparator") or "")
    if not isinstance(observed, (int, float)) or not isinstance(threshold, (int, float)):
        return False
    margin = 0.1 * abs(threshold) if threshold else 0.1
    if comparator in {">=", ">"}:
        return 0 <= threshold - observed <= margin
    if comparator in {"<", "<="}:
        return 0 <= observed - threshold <= margin
    return False


def _bucket(gates: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return gates.setdefault(name, {
        "gate": name, "evaluated": 0, "failures": 0, "enforced_failures": 0,
        "advisory_failures": 0, "legacy_failures": 0, "near_misses": 0,
        "example": "", "_observed": [],
    })


@dataclass
class _GateAggregation:
    gates: dict[str, dict[str, Any]] = field(default_factory=dict)
    first_failed: dict[str, int] = field(default_factory=dict)
    structured_rows: int = 0
    accepted: int = 0
    submitted: int = 0
    alpha_gate_seen: int = 0
    alpha_gate_passed: int = 0


def _apply_structured_records(records: list[dict[str, Any]], payload: dict[str, Any],
                              agg: _GateAggregation) -> None:
    for record in records:
        b = _bucket(agg.gates, str(record.get("gate") or "unknown"))
        b["evaluated"] += 1
        if isinstance(record.get("observed"), (int, float)) and isinstance(record.get("threshold"), (int, float)):
            b["_observed"].append(float(record["observed"]))
        if record.get("gate") == "alpha_composite_tier":
            agg.alpha_gate_seen += 1
            if record.get("passed"):
                agg.alpha_gate_passed += 1
        if not record.get("passed"):
            b["failures"] += 1
            if record.get("enforced", True):
                b["enforced_failures"] += 1
            else:
                b["advisory_failures"] += 1
            if _near_miss(record):
                b["near_misses"] += 1
            if not b["example"] and record.get("detail"):
                b["example"] = str(record["detail"])[:160]
    ffg = payload.get("_first_failed_gate")
    if ffg:
        agg.first_failed[str(ffg)] = agg.first_failed.get(str(ffg), 0) + 1


def _apply_legacy_clauses(row: dict[str, Any], agg: _GateAggregation) -> None:
    # Legacy rejected row: map free-text clauses onto canonical gate
    # names, counting each gate at most once per attempt (the old
    # alpha gate emitted two clauses for one gate). Accepted rows
    # are skipped — their reason text is an acceptance note, not a
    # failure.
    clauses = [c.strip() for c in str(row.get("rejection_reason") or "").split(";") if c.strip()]
    seen: set[str] = set()
    for index, clause in enumerate(clauses):
        lowered = clause.lower()
        name = next((g for token, g in LEGACY_CLAUSE_GATES if token in lowered), "other")
        if index == 0:
            agg.first_failed[name] = agg.first_failed.get(name, 0) + 1
        if name in seen:
            continue
        seen.add(name)
        b = _bucket(agg.gates, name)
        b["failures"] += 1
        b["enforced_failures"] += 1
        b["legacy_failures"] += 1
        if not b["example"]:
            b["example"] = clause[:160]


def _aggregate_gates(audit_rows: list[dict[str, Any]]) -> _GateAggregation:
    agg = _GateAggregation()
    agg.accepted = sum(1 for row in audit_rows if row["status"] in _ACCEPTED_STATUSES)
    agg.submitted = sum(1 for row in audit_rows if row["status"] == "submitted")
    for row in audit_rows:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        records = payload.get("_gates")
        if isinstance(records, list) and records:
            agg.structured_rows += 1
            _apply_structured_records(records, payload, agg)
        elif row["status"] not in _ACCEPTED_STATUSES:
            _apply_legacy_clauses(row, agg)
    return agg


# ─── Finalize + format (report sections) ──────────────────────────────────────

def _quantiles(values: list[float]) -> dict[str, float] | None:
    """min/p25/p50/p75/max over all structured evaluations of a numeric
    gate (passed AND failed) — the distribution needed to judge where a
    threshold sits relative to the candidate population."""
    if not values:
        return None
    ordered = sorted(values)

    def pct(p: float) -> float:
        index = min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))
        return round(ordered[index], 4)

    return {"count": len(ordered), "min": round(ordered[0], 4), "p25": pct(0.25),
            "p50": pct(0.50), "p75": pct(0.75), "max": round(ordered[-1], 4)}


def _finalize_gate_failures(gates: dict[str, dict[str, Any]], n_audit_rows: int) -> list[dict[str, Any]]:
    gate_failures = sorted(gates.values(), key=lambda b: b["failures"], reverse=True)
    for b in gate_failures:
        b["share_of_attempts"] = round(b["failures"] / n_audit_rows, 4) if n_audit_rows else 0.0
        b["observed_stats"] = _quantiles(b.pop("_observed"))
    return gate_failures


def _build_stage_funnel(inputs: _WaterfallInputs, candidates_scanned: int,
                        agg: _GateAggregation) -> list[dict[str, Any]]:
    def stage(name: str, count: int, previous: int | None, basis: str) -> dict[str, Any]:
        return {
            "stage": name,
            "count": count,
            "pct_of_previous": round(count / previous, 4) if previous else None,
            "basis": basis,
        }

    funnel = [stage("candidates_scanned", candidates_scanned, None, f"scanner_runs (last {len(inputs.scanner_rows)} runs)")]
    funnel.append(stage("ideas_created", inputs.ideas_total, candidates_scanned or None, "alpha_ideas (all time)"))
    funnel.append(stage("decision_attempts", len(inputs.audit_rows), inputs.ideas_total or None,
                        f"execution_audit (last {len(inputs.audit_rows)} of {inputs.audit_total}; ideas can be attempted more than once)"))
    funnel.append(stage("accepted_decisions", agg.accepted, len(inputs.audit_rows) or None, "risk-engine accepted (dry_run or submitted)"))
    funnel.append(stage("alpha_gate_passed", agg.alpha_gate_passed, agg.alpha_gate_seen or None,
                        f"structured traces only ({agg.alpha_gate_seen} accepted attempts carried the alpha gate)"))
    funnel.append(stage("paper_orders_submitted", agg.submitted, agg.accepted or None, "execution_audit status=submitted"))
    funnel.append(stage("paper_trades", inputs.trades_paper, agg.submitted or None, "trades with dry_run=0 (all time)"))
    return funnel


def _build_threshold_impact(gates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "gate": b["gate"],
            "enforced_failures": b["enforced_failures"],
            "advisory_failures": b["advisory_failures"],
            "near_misses": b["near_misses"],
            "example": b["example"],
        }
        for b in sorted(gates.values(), key=lambda b: (b["enforced_failures"], b["near_misses"]), reverse=True)
        if b["failures"]
    ][:12]


# ─── Public entry point ───────────────────────────────────────────────────────

def build_rejection_waterfall(db_path: str, limit: int = 5000) -> dict[str, Any]:
    """Read-only rejection waterfall across the whole pipeline.

    Answers: where are candidates rejected, which gates fire most, what
    share of candidates reaches each stage, and which thresholds cost the
    most near-miss opportunities. Sources: scanner_runs summaries (pre-idea
    stage), alpha_ideas / trades counts, and execution_audit rows — using
    the structured ``_gates`` telemetry where present and falling back to
    parsing legacy free-text rejection clauses. Never mutates anything.
    """
    inputs = _load_inputs(db_path, limit)
    candidates_scanned, pre_idea_skips = _parse_scanner_runs(inputs.scanner_rows)
    agg = _aggregate_gates(inputs.audit_rows)
    gate_failures = _finalize_gate_failures(agg.gates, len(inputs.audit_rows))

    return {
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "audit_rows_analyzed": len(inputs.audit_rows),
            "audit_rows_total": inputs.audit_total,
            "structured_rows": agg.structured_rows,
            "legacy_rows": len(inputs.audit_rows) - agg.structured_rows,
            "scanner_runs_analyzed": len(inputs.scanner_rows),
        },
        "stage_funnel": _build_stage_funnel(inputs, candidates_scanned, agg),
        "gate_failures": gate_failures,
        "first_failed_gates": sorted(
            ({"gate": name, "count": count} for name, count in agg.first_failed.items()),
            key=lambda item: item["count"], reverse=True,
        ),
        "threshold_impact": _build_threshold_impact(agg.gates),
        "pre_idea_skips": sorted(
            ({"reason": reason, "count": count} for reason, count in pre_idea_skips.items()),
            key=lambda item: item["count"], reverse=True,
        )[:12],
    }
