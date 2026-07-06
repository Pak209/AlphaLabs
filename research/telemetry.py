"""Read-only loaders that turn recorded telemetry into analysis frames.

Two canonical frames feed every experiment:

- ``idea_outcomes``    — one row per alpha idea, joined to its forward-outcome
  labels in signal_evaluations. Rejected ideas keep their evaluations, so this
  frame is the denominator for regret analysis.
- ``decision_outcomes`` — one row per structured execution_audit attempt
  (rows carrying the ``_gates`` telemetry), with per-gate observed values,
  thresholds, near-miss flags, and the same outcome labels joined via idea_id.

Legacy audit rows (free-text rejection reasons, no observed values) are
excluded by design: distributional claims use structured rows only, per
docs/CALIBRATION_PLAN.md §3.

All connections are opened with SQLite's read-only URI mode; a write attempted
through them raises ``sqlite3.OperationalError``.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from alpha_lab.database import resolve_db_path

# Mirrors the near-miss margin used by AlphaLabService.rejection_waterfall():
# a failed numeric gate is a near miss when the observed value is within 10%
# of the threshold (absolute 0.1 when the threshold is zero).
NEAR_MISS_MARGIN_FRAC = 0.10

ACCEPTED_STATUSES = {"dry_run", "submitted"}


def connect_readonly(db_path: str | None = None) -> sqlite3.Connection:
    """Open the telemetry database read-only. Never creates the file."""
    resolved = Path(resolve_db_path(db_path))
    if not resolved.exists():
        raise FileNotFoundError(f"telemetry database not found: {resolved}")
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _session(timestamp: str | None) -> str:
    """Session key = the ISO date portion of a stored timestamp (UTC)."""
    return str(timestamp or "")[:10] or "unknown"


def _signed_moves(direction: str, move_after_pct: Any, benchmark_move_pct: Any) -> dict[str, Any]:
    """Direction-signed outcome labels.

    ``signed_move_pct``  — the idea's move credited in its called direction
                           (bearish ideas earn positive label on a drop).
    ``excess_move_pct``  — signed move minus the same-signed benchmark move,
                           so a bullish call that merely rode the market up
                           scores ~0.
    ``hit``              — 1 if the excess move is positive, else 0.
    All are None when the evaluation has not been filled yet.
    """
    if not isinstance(move_after_pct, (int, float)):
        return {"signed_move_pct": None, "excess_move_pct": None, "hit": None}
    sign = -1.0 if str(direction).lower() == "bearish" else 1.0
    signed_move = sign * float(move_after_pct)
    benchmark = float(benchmark_move_pct) if isinstance(benchmark_move_pct, (int, float)) else 0.0
    excess = signed_move - sign * benchmark
    return {
        "signed_move_pct": round(signed_move, 4),
        "excess_move_pct": round(excess, 4),
        "hit": 1 if excess > 0 else 0,
    }


def load_idea_outcomes(conn: sqlite3.Connection, since: str | None = None,
                       until: str | None = None) -> list[dict[str, Any]]:
    """One row per idea with evaluation labels. Includes rejected ideas."""
    clauses, params = [], []
    if since:
        clauses.append("datetime(i.timestamp) >= datetime(?)")
        params.append(since)
    if until:
        clauses.append("datetime(i.timestamp) < datetime(?)")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT i.id AS idea_id, i.ticker, i.asset_type, i.sector, i.theme,
               i.bias, i.confidence AS idea_confidence, i.timeframe,
               i.catalyst_type, i.catalyst_score, i.source, i.status,
               i.rejection_reason, i.timestamp AS idea_timestamp,
               e.source_tags, e.generated_at, e.evaluated_at, e.horizon,
               e.direction, e.confidence, e.market_regime, e.alert_price,
               e.price_after, e.move_after_pct, e.benchmark_move_pct,
               e.early_detection_score, e.provisional_grade, e.final_grade,
               e.status AS evaluation_status
        FROM alpha_ideas i
        LEFT JOIN signal_evaluations e ON e.idea_id = i.id
        {where}
        ORDER BY datetime(i.timestamp), i.id
        """,
        params,
    ).fetchall()

    frame: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        direction = record.get("direction") or record.get("bias") or ""
        record.update(_signed_moves(direction, record.get("move_after_pct"),
                                    record.get("benchmark_move_pct")))
        record["session"] = _session(record.get("generated_at") or record.get("idea_timestamp"))
        record["evaluated"] = record["signed_move_pct"] is not None
        record["grade"] = record.get("final_grade") or record.get("provisional_grade")
        frame.append(record)
    return frame


def _near_miss(record: dict[str, Any]) -> bool:
    observed, threshold = record.get("observed"), record.get("threshold")
    comparator = str(record.get("comparator") or "")
    if not isinstance(observed, (int, float)) or not isinstance(threshold, (int, float)):
        return False
    margin = NEAR_MISS_MARGIN_FRAC * abs(threshold) if threshold else NEAR_MISS_MARGIN_FRAC
    if comparator in {">=", ">"}:
        return 0 <= threshold - observed <= margin
    if comparator in {"<", "<="}:
        return 0 <= observed - threshold <= margin
    return False


def load_decision_outcomes(conn: sqlite3.Connection, limit: int = 5000) -> list[dict[str, Any]]:
    """One row per structured execution_audit attempt, outcomes joined in.

    Rows without ``_gates`` telemetry (legacy attempts) are skipped so every
    returned row carries observed values and honest per-gate denominators.
    """
    audit_rows = conn.execute(
        """
        SELECT a.id AS audit_id, a.idea_id, a.ticker, a.status, a.dry_run,
               a.payload_json, a.created_at,
               e.direction, e.move_after_pct, e.benchmark_move_pct,
               e.early_detection_score, e.confidence AS eval_confidence,
               i.bias, i.source, i.asset_type
        FROM execution_audit a
        LEFT JOIN signal_evaluations e ON e.idea_id = a.idea_id
        LEFT JOIN alpha_ideas i ON i.id = a.idea_id
        ORDER BY datetime(a.created_at) DESC, a.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    frame: list[dict[str, Any]] = []
    for row in audit_rows:
        record = dict(row)
        try:
            payload = json.loads(record.pop("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        gates = payload.get("_gates")
        if not isinstance(gates, list) or not gates:
            continue  # legacy row — no structured telemetry
        for gate in gates:
            gate["near_miss"] = _near_miss(gate)
        first_failed = payload.get("_first_failed_gate") or next(
            (g.get("gate") for g in gates if not g.get("passed")), None
        )
        direction = record.get("direction") or record.get("bias") or ""
        record.update(_signed_moves(direction, record.get("move_after_pct"),
                                    record.get("benchmark_move_pct")))
        record["gates"] = gates
        record["first_failed_gate"] = first_failed
        record["accepted"] = record["status"] in ACCEPTED_STATUSES
        record["session"] = _session(record.get("created_at"))
        record["evaluated"] = record["signed_move_pct"] is not None
        record["gate_context"] = payload.get("gate_context") or payload.get("_gate_context")
        frame.append(record)
    frame.reverse()  # chronological
    return frame


def gate_records(decision_frame: list[dict[str, Any]], gate: str) -> list[dict[str, Any]]:
    """Flatten one gate's records across a decision frame (only attempts where
    the gate was actually evaluated, keeping denominators honest)."""
    out = []
    for row in decision_frame:
        for record in row["gates"]:
            if record.get("gate") == gate:
                merged = dict(record)
                merged["audit_id"] = row["audit_id"]
                merged["idea_id"] = row["idea_id"]
                merged["accepted"] = row["accepted"]
                merged["first_failed_gate"] = row["first_failed_gate"]
                merged["excess_move_pct"] = row["excess_move_pct"]
                merged["hit"] = row["hit"]
                merged["session"] = row["session"]
                merged["evaluated"] = row["evaluated"]
                out.append(merged)
    return out
