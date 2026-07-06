"""
alpha_lab/attribution.py — feature attribution over the replay dataset.

Measures which scoring inputs actually correlate with better recorded outcomes,
so composite weights and new features are chosen from evidence instead of
intuition. Builds on the replay layer (same dataset, same fingerprint, same
live-engine scoring) and on the structured gate traces in execution_audit.

Strictly read-only diagnostics: SELECTs only, no live scoring change, no ideas,
decisions, orders, trades, or approvals.

Methodology (dependency-free, honest at small N):
  1. Numeric features -> tie-aware Spearman rank correlation against the
     bias-signed forward move, plus a median-split comparison (top half vs
     bottom half hit rate / avg move) that stays meaningful when rank
     correlation is noisy.
  2. Near-constant features are flagged as dead inputs rather than reported
     with a meaningless correlation — a zero-variance feature cannot rank
     anything and usually indicates an unwired data source.
  3. Categorical features -> per-level outcome stats with a minimum group
     size, plus best/worst level spread.
  4. Selected vs rejected -> per-feature median gap between the populations
     the current bars select and reject. A feature with a large selection gap
     but weak outcome correlation is over-weighted; the reverse is under-used.
  5. Gate regret -> structured gate traces joined to outcomes: per first
     failed gate, how often the rejected idea would have been a directional
     winner. (Legacy free-text rows carry no per-gate values and are skipped.)

See docs/FEATURE_ATTRIBUTION.md.
"""
from __future__ import annotations

import json
from typing import Any

from .database import connect, resolve_db_path
from .replay import (
    BASELINE, build_replay_dataset, score_row, spearman_rank_correlation,
    _outcome_stats,
)

# Feature keys measured per row (populated by _attribution_rows).
NUMERIC_FEATURES = [
    "confidence",
    "idea_catalyst_score",
    "replay_composite",
    "component_catalyst",
    "component_narrative",
    "component_macro",
    "component_price_volume",
    "sub_catalyst_type",
    "sub_surprise",
    "sub_novelty",
    "sub_materiality",
    "stored_composite",
    "stored_price_volume_score",
]
CATEGORICAL_FEATURES = [
    "catalyst_type", "source", "market_regime", "bias", "timeframe",
    "replay_tier", "idea_status",
]
MIN_GROUP_SIZE = 3           # categorical levels below this are pooled, not judged
NEAR_ZERO_VARIANCE = 1e-9    # spread below this flags a dead input


def _attribution_rows(db_path: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay dataset rows + baseline live-engine scores, flattened per feature."""
    dataset = build_replay_dataset(db_path)
    rows: list[dict[str, Any]] = []
    for row in dataset["rows"]:
        scored = score_row(row, BASELINE)
        rows.append({
            "idea_id": row["idea_id"],
            "directional_move_pct": row["directional_move_pct"],
            "hit": row["hit"],
            "selected": scored["selected"],
            # numeric features
            "confidence": _num(row.get("confidence")),
            "idea_catalyst_score": _num(row.get("catalyst_score")),
            "replay_composite": scored["composite_score"],
            "component_catalyst": scored["components"]["catalyst"],
            "component_narrative": scored["components"]["narrative"],
            "component_macro": scored["components"]["macro"],
            "component_price_volume": scored["components"]["price_volume"],
            "sub_catalyst_type": scored["catalyst_subsignals"].get("catalyst_type"),
            "sub_surprise": scored["catalyst_subsignals"].get("surprise"),
            "sub_novelty": scored["catalyst_subsignals"].get("novelty"),
            "sub_materiality": scored["catalyst_subsignals"].get("materiality"),
            "stored_composite": _num(row.get("stored_composite")),
            "stored_price_volume_score": _num(row.get("stored_price_volume_score")),
            # categorical features
            "catalyst_type": _cat(row.get("catalyst_type")),
            "source": _cat(row.get("source")),
            "market_regime": _cat(row.get("market_regime")),
            "bias": _cat(row.get("bias")),
            "timeframe": _cat(row.get("timeframe")),
            "replay_tier": scored["tier"],
            "idea_status": _cat(row.get("idea_status")),
        })
    return rows, dataset["fingerprint"]


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _cat(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


# ─── 1+2. Numeric features ────────────────────────────────────────────────────

def numeric_feature_report(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    pairs = [
        (r[feature], r["directional_move_pct"], r["hit"])
        for r in rows
        if r.get(feature) is not None and r["directional_move_pct"] is not None
    ]
    report: dict[str, Any] = {"feature": feature, "n_with_outcome": len(pairs)}
    if not pairs:
        report.update({"dead_input": None, "spearman": None, "median_split": None})
        return report

    values = [p[0] for p in pairs]
    spread = max(values) - min(values)
    if spread <= NEAR_ZERO_VARIANCE:
        # A constant feature cannot rank outcomes; usually an unwired input
        # (e.g. novelty while prior_count_30d is never queried).
        report.update({
            "dead_input": True, "constant_value": values[0],
            "spearman": None, "median_split": None,
        })
        return report

    moves = [p[1] for p in pairs]
    median = _median(values)
    top = [{"directional_move_pct": m, "hit": h} for v, m, h in pairs if v > median]
    bottom = [{"directional_move_pct": m, "hit": h} for v, m, h in pairs if v <= median]
    top_stats, bottom_stats = _outcome_stats(top), _outcome_stats(bottom)

    split = {
        "median": round(median, 4),
        "top_half": top_stats,
        "bottom_half": bottom_stats,
        "hit_rate_delta": (
            round(top_stats["hit_rate"] - bottom_stats["hit_rate"], 4)
            if top_stats["hit_rate"] is not None and bottom_stats["hit_rate"] is not None else None
        ),
        "avg_move_delta_pct": (
            round(top_stats["avg_move_pct"] - bottom_stats["avg_move_pct"], 4)
            if top_stats["avg_move_pct"] is not None and bottom_stats["avg_move_pct"] is not None else None
        ),
    }
    report.update({
        "dead_input": False,
        "spearman": spearman_rank_correlation(values, moves),
        "median_split": split,
    })
    return report


# ─── 3. Categorical features ──────────────────────────────────────────────────

def categorical_feature_report(rows: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["directional_move_pct"] is None:
            continue
        groups.setdefault(r[feature], []).append(r)

    levels = []
    pooled_small = 0
    for level, members in sorted(groups.items()):
        if len(members) < MIN_GROUP_SIZE:
            pooled_small += len(members)
            continue
        levels.append({"level": level, **_outcome_stats(members)})
    levels.sort(key=lambda l: (l["avg_move_pct"] is None, -(l["avg_move_pct"] or 0)))

    spread = None
    scored_levels = [l for l in levels if l["avg_move_pct"] is not None]
    if len(scored_levels) >= 2:
        spread = round(scored_levels[0]["avg_move_pct"] - scored_levels[-1]["avg_move_pct"], 4)

    return {
        "feature": feature,
        "levels": levels,
        "small_groups_pooled_n": pooled_small,
        "best_worst_avg_move_spread_pct": spread,
    }


# ─── 4. Selected vs rejected ──────────────────────────────────────────────────

def selected_vs_rejected_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [r for r in rows if r["selected"]]
    rejected = [r for r in rows if not r["selected"]]
    features = []
    for feature in NUMERIC_FEATURES:
        sel_vals = [r[feature] for r in selected if r.get(feature) is not None]
        rej_vals = [r[feature] for r in rejected if r.get(feature) is not None]
        if not sel_vals or not rej_vals:
            continue
        gap = round(_median(sel_vals) - _median(rej_vals), 4)
        features.append({
            "feature": feature,
            "median_selected": round(_median(sel_vals), 4),
            "median_rejected": round(_median(rej_vals), 4),
            "selection_gap": gap,
        })
    features.sort(key=lambda f: -abs(f["selection_gap"]))
    return {
        "n_selected": len(selected),
        "n_rejected": len(rejected),
        "selected_outcomes": _outcome_stats(selected),
        "rejected_outcomes": _outcome_stats(rejected),
        "feature_gaps": features,
    }


# ─── 5. Gate regret (structured traces only) ──────────────────────────────────

_GATE_SQL = """
SELECT a.idea_id, a.payload_json, e.move_after_pct, e.status AS eval_status, i.bias
FROM execution_audit a
JOIN alpha_ideas i ON i.id = a.idea_id
LEFT JOIN signal_evaluations e ON e.idea_id = a.idea_id
WHERE a.idea_id IS NOT NULL
ORDER BY a.id
"""


def gate_regret_report(db_path: str | None = None) -> dict[str, Any]:
    """Per first-failed gate: how often the blocked idea went on to be a winner.

    Uses the LATEST structured attempt per idea (one vote per idea). Legacy
    rows without `_gates` payloads are counted but not attributed.
    """
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        raw = [dict(r) for r in conn.execute(_GATE_SQL).fetchall()]

    latest: dict[int, dict[str, Any]] = {}
    legacy_rows = 0
    for row in raw:
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload.get("_gates"), list):
            legacy_rows += 1
            continue
        row["_first_failed"] = payload.get("_first_failed_gate")
        latest[int(row["idea_id"])] = row   # later rows overwrite: latest attempt wins

    gates: dict[str, dict[str, Any]] = {}
    for row in latest.values():
        gate = row.get("_first_failed")
        if not gate:
            continue   # accepted attempt — no rejection to attribute
        move = row.get("move_after_pct")
        bias = str(row.get("bias") or "").lower()
        directional = None
        if isinstance(move, (int, float)) and row.get("eval_status") == "evaluated":
            directional = float(move) if bias == "bullish" else -float(move) if bias == "bearish" else None
        b = gates.setdefault(gate, {"gate": gate, "n_rejected": 0, "n_with_outcome": 0,
                                    "regret_hits": 0, "moves": []})
        b["n_rejected"] += 1
        if directional is not None:
            b["n_with_outcome"] += 1
            b["moves"].append(directional)
            if directional > 0:
                b["regret_hits"] += 1

    results = []
    for b in gates.values():
        moves = b.pop("moves")
        b["regret_rate"] = round(b["regret_hits"] / b["n_with_outcome"], 4) if b["n_with_outcome"] else None
        b["avg_missed_move_pct"] = round(sum(moves) / len(moves), 4) if moves else None
        results.append(b)
    results.sort(key=lambda b: -(b["regret_rate"] or 0))
    return {
        "structured_ideas": len(latest),
        "legacy_rows_skipped": legacy_rows,
        "gates": results,
    }


# ─── Assembled report ─────────────────────────────────────────────────────────

def feature_attribution_report(db_path: str | None = None) -> dict[str, Any]:
    rows, fingerprint = _attribution_rows(db_path)
    numeric = [numeric_feature_report(rows, f) for f in NUMERIC_FEATURES]
    categorical = [categorical_feature_report(rows, f) for f in CATEGORICAL_FEATURES]

    def importance_key(r: dict[str, Any]):
        rho = r.get("spearman")
        split = r.get("median_split") or {}
        delta = split.get("avg_move_delta_pct")
        return (
            0 if isinstance(rho, (int, float)) else 1,
            -abs(rho) if isinstance(rho, (int, float)) else 0.0,
            -abs(delta) if isinstance(delta, (int, float)) else 0.0,
        )

    live_features = [r for r in numeric if r.get("dead_input") is False]
    dead_features = [r["feature"] for r in numeric if r.get("dead_input")]
    ranking = [
        {"feature": r["feature"], "spearman": r["spearman"],
         "split_avg_move_delta_pct": (r.get("median_split") or {}).get("avg_move_delta_pct"),
         "split_hit_rate_delta": (r.get("median_split") or {}).get("hit_rate_delta"),
         "n_with_outcome": r["n_with_outcome"]}
        for r in sorted(live_features, key=importance_key)
    ]

    return {
        "fingerprint": fingerprint,
        "importance_ranking": ranking,
        "dead_inputs": dead_features,
        "numeric_features": numeric,
        "categorical_features": categorical,
        "selected_vs_rejected": selected_vs_rejected_report(rows),
        "gate_regret": gate_regret_report(db_path),
        "caveats": [
            "Correlations over fewer than 30 outcomes are directional, not decisive.",
            "Dataset contains only emitted ideas (emission bias); radar-rejected candidates are invisible here.",
            "Dead inputs indicate unwired data sources, not worthless features.",
        ],
    }
