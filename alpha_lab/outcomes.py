"""
alpha_lab/outcomes.py — outcome reporting: how ideas performed after generation.

Where attribution asks "which inputs predict outcomes?" and replay asks "what
would a different configuration have selected?", this layer reports what the
pipeline ACTUALLY did and what happened next: performance grouped by source,
catalyst type, bias, score band, gate result, and accepted/rejected status,
plus the near-miss population the calibration plan's regret analysis needs.

Strictly read-only diagnostics: SELECTs only; no ideas, decisions, orders,
trades, approvals, or scoring changes.

Definitions:
  outcome      — bias-signed forward move from signal_evaluations (evaluated
                 rows only), same as the replay/attribution layers.
  accepted     — idea_status in {accepted, tested, traded}: the decision engine
                 accepted it (dry-run or paper).
  rejected     — idea_status == rejected.
  near-miss    — latest structured attempt failed a numeric ">=" gate by no
                 more than NEAR_MISS_MARGIN (10%) of its threshold — the same
                 rule the rejection waterfall uses.

See docs/OUTCOME_REPORTING.md.
"""
from __future__ import annotations

import json
from typing import Any

from .database import connect, resolve_db_path
from .replay import (
    BASELINE, CALIBRATION_BANDS, build_replay_dataset, score_row, _outcome_stats,
)

NEAR_MISS_MARGIN = 0.10   # mirrors the rejection waterfall's near-miss rule
CONFIDENCE_BANDS: list[tuple[float, float]] = [
    (0.0, 0.60), (0.60, 0.70), (0.70, 0.75), (0.75, 0.85), (0.85, 1.01),
]
ACCEPTED_STATUSES = {"accepted", "tested", "traded"}


# ─── Gate traces (latest structured attempt per idea) ─────────────────────────

_AUDIT_SQL = """
SELECT idea_id, payload_json
FROM execution_audit
WHERE idea_id IS NOT NULL
ORDER BY id
"""


def _latest_gate_info(db_path: str) -> dict[int, dict[str, Any]]:
    """idea_id -> {first_failed_gate, near_missed_gates:[...]} from the latest
    structured attempt. Legacy rows (no _gates payload) are skipped."""
    with connect(db_path) as conn:
        raw = [dict(r) for r in conn.execute(_AUDIT_SQL).fetchall()]

    info: dict[int, dict[str, Any]] = {}
    for row in raw:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        records = payload.get("_gates")
        if not isinstance(records, list):
            continue
        near_missed = []
        for record in records:
            observed, threshold = record.get("observed"), record.get("threshold")
            if (
                not record.get("passed")
                and record.get("comparator") == ">="
                and isinstance(observed, (int, float))
                and isinstance(threshold, (int, float))
                and threshold > 0
                and 0 <= threshold - observed <= NEAR_MISS_MARGIN * threshold
            ):
                near_missed.append({
                    "gate": record.get("gate"),
                    "observed": observed,
                    "threshold": threshold,
                    "shortfall": round(threshold - observed, 4),
                })
        info[int(row["idea_id"])] = {   # later rows overwrite: latest attempt wins
            "first_failed_gate": payload.get("_first_failed_gate"),
            "near_missed_gates": near_missed,
        }
    return info


# ─── Outcome rows ─────────────────────────────────────────────────────────────

def build_outcome_rows(db_path: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = resolve_db_path(db_path)
    dataset = build_replay_dataset(path)
    gate_info = _latest_gate_info(path)

    rows = []
    for row in dataset["rows"]:
        scored = score_row(row, BASELINE)
        status = str(row.get("idea_status") or "").strip().lower()
        gates = gate_info.get(row["idea_id"], {})
        rows.append({
            "idea_id": row["idea_id"],
            "ticker": row.get("ticker"),
            "source": str(row.get("source") or "unknown").lower(),
            "catalyst_type": str(row.get("catalyst_type") or "unknown").lower(),
            "bias": str(row.get("bias") or "unknown").lower(),
            "confidence": row.get("confidence"),
            "idea_status": status or "unknown",
            "accepted": status in ACCEPTED_STATUSES,
            "rejected": status == "rejected",
            "replay_composite": scored["composite_score"],
            "first_failed_gate": gates.get("first_failed_gate"),
            "near_missed_gates": gates.get("near_missed_gates") or [],
            "directional_move_pct": row["directional_move_pct"],
            "hit": row["hit"],
        })
    return rows, dataset["fingerprint"]


# ─── Groupers ─────────────────────────────────────────────────────────────────

def _grouped(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key) or "unknown"), []).append(r)
    out = [{"group": level, "n_ideas": len(members), **_outcome_stats(members)}
           for level, members in sorted(groups.items())]
    out.sort(key=lambda g: (g["avg_move_pct"] is None, -(g["avg_move_pct"] or 0)))
    return out


def _banded(rows: list[dict[str, Any]], key: str,
            bands: list[tuple[float, float]]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in bands:
        members = [
            r for r in rows
            if isinstance(r.get(key), (int, float)) and lo <= float(r[key]) < hi
        ]
        label = f"{lo:g}-{hi:g}" if hi <= 100 else f"{lo:g}+"
        out.append({"band": label, "n_ideas": len(members), **_outcome_stats(members)})
    return out


# ─── Report sections ──────────────────────────────────────────────────────────

def accepted_vs_rejected_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [r for r in rows if r["accepted"]]
    rejected = [r for r in rows if r["rejected"]]
    other = [r for r in rows if not r["accepted"] and not r["rejected"]]
    accepted_stats = _outcome_stats(accepted)
    rejected_stats = _outcome_stats(rejected)
    edge = None
    if accepted_stats["avg_move_pct"] is not None and rejected_stats["avg_move_pct"] is not None:
        edge = round(accepted_stats["avg_move_pct"] - rejected_stats["avg_move_pct"], 4)
    return {
        "accepted": {"n_ideas": len(accepted), **accepted_stats},
        "rejected": {"n_ideas": len(rejected), **rejected_stats},
        "other": {"n_ideas": len(other), "statuses": sorted({r["idea_status"] for r in other})},
        "acceptance_edge_pct": edge,
    }


def gate_result_report(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Outcome stats per first-failed gate (rejections with structured traces),
    with an 'accepted' row on top for comparison."""
    accepted = [r for r in rows if r["accepted"]]
    out = [{"group": "accepted (no failed gate)", "n_ideas": len(accepted),
            **_outcome_stats(accepted)}]
    blocked = [r for r in rows if r["first_failed_gate"]]
    out.extend(_grouped(
        [{**r, "gate": r["first_failed_gate"]} for r in blocked], "gate",
    ))
    return out


def near_miss_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Performance of ideas that failed a numeric gate by <= 10% of threshold.

    The calibration plan's regret analysis: if near-misses perform like
    accepted ideas, the gate is too strict at the margin; if they perform
    clearly worse, the gate is placed well.
    """
    accepted = [r for r in rows if r["accepted"]]
    accepted_stats = _outcome_stats(accepted)

    per_gate: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        for miss in r["near_missed_gates"]:
            per_gate.setdefault(str(miss["gate"]), []).append(r)

    gates = []
    for gate, members in sorted(per_gate.items()):
        stats = _outcome_stats(members)
        verdict = None
        if stats["avg_move_pct"] is not None and accepted_stats["avg_move_pct"] is not None:
            verdict = (
                "near-misses matched accepted performance — gate may be strict at the margin"
                if stats["avg_move_pct"] >= accepted_stats["avg_move_pct"]
                else "near-misses underperformed accepted — gate placement looks right"
            )
        gates.append({
            "gate": gate,
            "n_near_miss": len(members),
            **stats,
            "examples": [
                {"idea_id": r["idea_id"], "ticker": r["ticker"],
                 "shortfalls": r["near_missed_gates"],
                 "directional_move_pct": r["directional_move_pct"]}
                for r in members[:5]
            ],
            "verdict_vs_accepted": verdict,
        })
    return {
        "margin": NEAR_MISS_MARGIN,
        "accepted_reference": {"n_ideas": len(accepted), **accepted_stats},
        "gates": gates,
    }


def outcome_report(db_path: str | None = None) -> dict[str, Any]:
    rows, fingerprint = build_outcome_rows(db_path)
    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r["idea_status"]] = status_counts.get(r["idea_status"], 0) + 1

    return {
        "fingerprint": fingerprint,
        "overall": {
            "n_ideas": len(rows),
            **_outcome_stats(rows),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "score_bands": {
            "replay_composite": _banded(rows, "replay_composite", CALIBRATION_BANDS),
            "confidence": _banded(rows, "confidence", CONFIDENCE_BANDS),
        },
        "by_source": _grouped(rows, "source"),
        "by_catalyst_type": _grouped(rows, "catalyst_type"),
        "by_bias": _grouped(rows, "bias"),
        "accepted_vs_rejected": accepted_vs_rejected_report(rows),
        "by_gate_result": gate_result_report(rows),
        "near_miss": near_miss_report(rows),
        "caveats": [
            "Outcomes exist only for evaluated ideas; groups without outcomes show n_with_outcome=0.",
            "Fewer than 30 outcomes overall -> every comparison is directional, not decisive.",
            "Gate results and near-misses cover structured-trace ideas only (post-telemetry).",
        ],
    }
