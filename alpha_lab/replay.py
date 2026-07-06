"""
alpha_lab/replay.py — offline replay of the scoring engine over stored history.

Re-scores historical ideas under a named ReplayScenario (candidate catalyst-type
weights, composite weights, confirmation thresholds, execution bars, or new
feature inputs via a hook) and evaluates each scenario against the outcomes the
platform already recorded (signal_evaluations forward moves, realized trade
P/L). Strictly read-only: it opens the DB with SELECTs only and never creates
ideas, decisions, orders, trades, or approvals.

Design rules:
  * The live scoring path is reused, not re-implemented: score_catalyst /
    composite accept optional overrides whose defaults reproduce the live
    constants, so a scenario with no overrides IS the live engine (the
    "baseline" scenario), and formulas cannot drift between live and replay.
  * Structural safety rules (confirmation gate, watchlist ceiling, floors) are
    not overridable — scenarios explore weights and thresholds, not the removal
    of safety structure.
  * Every report carries a dataset fingerprint. Two scenario results are only
    comparable when their fingerprints match.

See docs/REPLAY_FRAMEWORK.md for the workflow and metric definitions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .database import connect, resolve_db_path
from .scoring_engine import (
    composite, score_catalyst, score_narrative, score_macro, score_price_volume,
    catalyst_inputs_from_idea, narrative_inputs_for_ticker, tier_for,
)
from .scoring_models import ComponentScore, MacroInputs, PriceVolumeInputs

# Execution bars the replay simulates (mirrors _paper_order_eligibility_error
# and the decision engine's default min_confidence; kept as named constants so
# a drift in either live value shows up in the replay tests).
DEFAULT_PAPER_COMPOSITE_MIN = 70.0
DEFAULT_MIN_CONFIDENCE = 0.75

# Fixed composite bands for calibration reporting (stable across runs so
# reports remain comparable as data accrues).
CALIBRATION_BANDS: list[tuple[float, float]] = [
    (0.0, 45.0), (45.0, 60.0), (60.0, 70.0), (70.0, 80.0), (80.0, 100.01),
]


@dataclass
class ReplayScenario:
    """One named what-if configuration, evaluated over the same dataset.

    JSON-loadable fields cover weight/threshold overrides. ``feature_hook`` is
    Python-only: a callable(row) -> dict that may supply richer engine inputs
    for a row, keyed by any of:
        "catalyst_inputs"      (CatalystInputs)   — e.g. wire prior_count_30d
        "price_volume_inputs"  (PriceVolumeInputs) — e.g. event-anchored move
        "options"/"institutional" (ComponentScore) — e.g. backfilled flow data
    This is how a *future feature* is evaluated before it exists in live code.
    """
    name: str
    description: str = ""
    catalyst_type_weights: Optional[dict[str, float]] = None
    composite_weights: Optional[dict[str, float]] = None
    catalyst_confirm_min: Optional[float] = None
    price_volume_confirm_min: Optional[float] = None
    paper_composite_min: float = DEFAULT_PAPER_COMPOSITE_MIN
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    feature_hook: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = field(
        default=None, repr=False, compare=False,
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReplayScenario":
        allowed = {
            "name", "description", "catalyst_type_weights", "composite_weights",
            "catalyst_confirm_min", "price_volume_confirm_min",
            "paper_composite_min", "min_confidence",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown scenario fields: {', '.join(sorted(unknown))}")
        if not str(payload.get("name") or "").strip():
            raise ValueError("scenario requires a name")
        return cls(**{k: payload[k] for k in payload})

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "catalyst_type_weights": self.catalyst_type_weights,
            "composite_weights": self.composite_weights,
            "catalyst_confirm_min": self.catalyst_confirm_min,
            "price_volume_confirm_min": self.price_volume_confirm_min,
            "paper_composite_min": self.paper_composite_min,
            "min_confidence": self.min_confidence,
            "has_feature_hook": self.feature_hook is not None,
        }


BASELINE = ReplayScenario(
    name="baseline",
    description="Live engine, live thresholds — no overrides.",
)


# ─── Dataset ──────────────────────────────────────────────────────────────────

_DATASET_SQL = """
SELECT
  i.id            AS idea_id,
  i.ticker        AS ticker,
  i.bias          AS bias,
  i.confidence    AS confidence,
  i.timeframe     AS timeframe,
  i.source        AS source,
  i.market_regime AS market_regime,
  i.catalyst_type AS catalyst_type,
  i.catalyst_score AS catalyst_score,
  i.theme         AS theme,
  i.thesis        AS thesis,
  i.catalyst      AS catalyst,
  i.status        AS idea_status,
  i.timestamp     AS generated_at,
  e.move_after_pct         AS move_after_pct,
  e.early_detection_score  AS early_detection_score,
  e.status                 AS eval_status,
  t.price_volume_score     AS stored_price_volume_score,
  t.alpha_composite        AS stored_composite,
  t.realized_pl            AS realized_pl
FROM alpha_ideas i
LEFT JOIN signal_evaluations e ON e.idea_id = i.id
LEFT JOIN (
  SELECT idea_id,
         MAX(price_volume_score) AS price_volume_score,
         MAX(alpha_composite)    AS alpha_composite,
         SUM(realized_pl)        AS realized_pl
  FROM trades
  GROUP BY idea_id
) t ON t.idea_id = i.id
ORDER BY i.id
"""


def build_replay_dataset(db_path: str | None = None) -> dict[str, Any]:
    """Load the historical idea population plus recorded outcomes (read-only).

    Returns {"rows": [...], "fingerprint": {...}}. A row's outcome fields:
      directional_move_pct — move_after_pct signed toward the idea's bias
                             (None for neutral bias or unevaluated ideas)
      hit                  — directional_move_pct > 0 (None when no outcome)
    """
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        rows = [dict(r) for r in conn.execute(_DATASET_SQL).fetchall()]

    for row in rows:
        move = row.get("move_after_pct")
        bias = str(row.get("bias") or "").lower()
        directional: float | None = None
        if isinstance(move, (int, float)) and row.get("eval_status") == "evaluated":
            if bias == "bullish":
                directional = float(move)
            elif bias == "bearish":
                directional = -float(move)
        row["directional_move_pct"] = directional
        row["hit"] = (directional > 0) if directional is not None else None

    ids = ",".join(str(r["idea_id"]) for r in rows)
    stamps = [str(r.get("generated_at") or "") for r in rows]
    fingerprint = {
        "row_count": len(rows),
        "evaluated_count": sum(1 for r in rows if r["directional_move_pct"] is not None),
        "first_generated_at": min(stamps) if stamps else None,
        "last_generated_at": max(stamps) if stamps else None,
        "ids_sha256": hashlib.sha256(ids.encode()).hexdigest()[:16],
    }
    return {"rows": rows, "fingerprint": fingerprint}


# ─── Scoring one row under a scenario ─────────────────────────────────────────

def _pv_component(row: dict[str, Any], hook_out: dict[str, Any]) -> ComponentScore:
    """Price/volume component for a historical row.

    Preference order: feature-hook inputs (a candidate feature under test) →
    the PV score stored on the trade at entry (what the live engine saw) →
    neutral. Historical rows without either genuinely had no PV read, so
    neutral is the honest reconstruction, and the limitation is reported via
    metrics.pv_source_counts.
    """
    if isinstance(hook_out.get("price_volume_inputs"), PriceVolumeInputs):
        return score_price_volume(hook_out["price_volume_inputs"])
    stored = row.get("stored_price_volume_score")
    if isinstance(stored, (int, float)):
        return ComponentScore(
            score=float(stored), signals=[],
            explanation="stored price_volume_score from trade entry",
        )
    return score_price_volume(PriceVolumeInputs(bias=str(row.get("bias") or "neutral")))


def _pv_source(row: dict[str, Any], hook_out: dict[str, Any]) -> str:
    if isinstance(hook_out.get("price_volume_inputs"), PriceVolumeInputs):
        return "feature_hook"
    if isinstance(row.get("stored_price_volume_score"), (int, float)):
        return "stored_trade_entry"
    return "neutral_reconstruction"


def score_row(row: dict[str, Any], scenario: ReplayScenario) -> dict[str, Any]:
    """Deterministically re-score one historical row under the scenario."""
    hook_out = scenario.feature_hook(row) if scenario.feature_hook else {}
    catalyst_inputs = hook_out.get("catalyst_inputs") or catalyst_inputs_from_idea(row)
    catalyst_component = score_catalyst(catalyst_inputs, type_weights=scenario.catalyst_type_weights)
    narrative_component = score_narrative(narrative_inputs_for_ticker(row.get("ticker")))
    macro_component = score_macro(MacroInputs())
    pv_component = _pv_component(row, hook_out)
    alpha = composite(
        catalyst=catalyst_component,
        narrative=narrative_component,
        macro=macro_component,
        price_volume=pv_component,
        options=hook_out.get("options"),
        institutional=hook_out.get("institutional"),
        weights=scenario.composite_weights,
        catalyst_confirm_min=scenario.catalyst_confirm_min,
        price_volume_confirm_min=scenario.price_volume_confirm_min,
    )
    confidence = float(row.get("confidence") or 0.0)
    selected = (
        alpha.composite_score >= scenario.paper_composite_min
        and confidence >= scenario.min_confidence
    )
    return {
        "idea_id": row["idea_id"],
        "composite_score": alpha.composite_score,
        "tier": tier_for(alpha.composite_score),
        "confirmed": alpha.confirmed,
        "selected": selected,
        "pv_source": _pv_source(row, hook_out),
        "directional_move_pct": row["directional_move_pct"],
        "hit": row["hit"],
        # Component and sub-signal values, exposed for the feature-attribution
        # layer (which measures each one against recorded outcomes).
        "components": {
            "catalyst": catalyst_component.score,
            "narrative": narrative_component.score,
            "macro": macro_component.score,
            "price_volume": pv_component.score,
        },
        "catalyst_subsignals": {s.name: s.value for s in catalyst_component.signals},
    }


# ─── Metrics ──────────────────────────────────────────────────────────────────

def spearman_rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rho with average ranks for ties. None when undefined (n < 3
    or a constant series)."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                result[order[k]] = avg_rank
            i = j + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mean = (n + 1) / 2
    cov = sum((a - mean) * (b - mean) for a, b in zip(rx, ry))
    var_x = sum((a - mean) ** 2 for a in rx)
    var_y = sum((b - mean) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return round(cov / (var_x * var_y) ** 0.5, 4)


def _outcome_stats(scored: list[dict[str, Any]]) -> dict[str, Any]:
    moves = sorted(r["directional_move_pct"] for r in scored if r["directional_move_pct"] is not None)
    hits = [r["hit"] for r in scored if r["hit"] is not None]
    if not moves:
        return {"n_with_outcome": 0, "hit_rate": None, "avg_move_pct": None,
                "median_move_pct": None, "p25_move_pct": None, "p75_move_pct": None}

    def pct(p: float) -> float:
        return round(moves[min(len(moves) - 1, max(0, round(p * (len(moves) - 1))))], 4)

    return {
        "n_with_outcome": len(moves),
        "hit_rate": round(sum(hits) / len(hits), 4),
        "avg_move_pct": round(sum(moves) / len(moves), 4),
        "median_move_pct": pct(0.50),
        "p25_move_pct": pct(0.25),
        "p75_move_pct": pct(0.75),
    }


def scenario_metrics(scored: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [r for r in scored if r["selected"]]
    rejected = [r for r in scored if not r["selected"]]
    with_outcome = [r for r in scored if r["directional_move_pct"] is not None]

    bands = []
    for lo, hi in CALIBRATION_BANDS:
        rows = [r for r in with_outcome if lo <= r["composite_score"] < hi]
        bands.append({"band": f"{lo:g}-{hi:g}" if hi <= 100 else f"{lo:g}+",
                      **_outcome_stats(rows)})

    selected_stats = _outcome_stats(selected)
    rejected_stats = _outcome_stats(rejected)
    edge = None
    if selected_stats["avg_move_pct"] is not None and rejected_stats["avg_move_pct"] is not None:
        edge = round(selected_stats["avg_move_pct"] - rejected_stats["avg_move_pct"], 4)

    pv_sources: dict[str, int] = {}
    for r in scored:
        pv_sources[r["pv_source"]] = pv_sources.get(r["pv_source"], 0) + 1

    return {
        "n_rows": len(scored),
        "n_selected": len(selected),
        "selection_rate": round(len(selected) / len(scored), 4) if scored else None,
        "selected": selected_stats,
        "rejected": rejected_stats,
        "selection_edge_pct": edge,
        "rank_correlation_composite_vs_move": spearman_rank_correlation(
            [r["composite_score"] for r in with_outcome],
            [r["directional_move_pct"] for r in with_outcome],
        ),
        "calibration_bands": bands,
        "pv_source_counts": pv_sources,
    }


# ─── Running and comparing scenarios ──────────────────────────────────────────

def run_scenario(dataset: dict[str, Any], scenario: ReplayScenario) -> dict[str, Any]:
    scored = [score_row(row, scenario) for row in dataset["rows"]]
    return {
        "scenario": scenario.describe(),
        "fingerprint": dataset["fingerprint"],
        "metrics": scenario_metrics(scored),
        "scored_rows": scored,
    }


def compare_to_baseline(baseline: dict[str, Any], candidate: dict[str, Any],
                        example_limit: int = 10) -> dict[str, Any]:
    if baseline["fingerprint"] != candidate["fingerprint"]:
        raise ValueError("results are not comparable: dataset fingerprints differ")
    base_sel = {r["idea_id"] for r in baseline["scored_rows"] if r["selected"]}
    cand_by_id = {r["idea_id"]: r for r in candidate["scored_rows"]}
    cand_sel = {r["idea_id"] for r in candidate["scored_rows"] if r["selected"]}

    def summarize(ids: set[int]) -> dict[str, Any]:
        rows = [cand_by_id[i] for i in sorted(ids)]
        return {
            "count": len(rows),
            "outcomes": _outcome_stats(rows),
            "examples": [
                {"idea_id": r["idea_id"], "composite_score": r["composite_score"],
                 "directional_move_pct": r["directional_move_pct"]}
                for r in rows[:example_limit]
            ],
        }

    return {
        "baseline": baseline["scenario"]["name"],
        "candidate": candidate["scenario"]["name"],
        "selected_baseline": len(base_sel),
        "selected_candidate": len(cand_sel),
        "unchanged": len(base_sel & cand_sel),
        "newly_selected": summarize(cand_sel - base_sel),
        "newly_dropped": summarize(base_sel - cand_sel),
    }


def run_replay(scenarios: list[ReplayScenario], db_path: str | None = None) -> dict[str, Any]:
    """Run baseline + scenarios over one dataset; strip per-row detail from the
    report (kept in-memory for comparisons) so reports stay diff-friendly."""
    dataset = build_replay_dataset(db_path)
    baseline_result = run_scenario(dataset, BASELINE)
    results = [baseline_result]
    comparisons = []
    for scenario in scenarios:
        if scenario.name == BASELINE.name:
            continue
        result = run_scenario(dataset, scenario)
        results.append(result)
        comparisons.append(compare_to_baseline(baseline_result, result))
    return {
        "fingerprint": dataset["fingerprint"],
        "results": [
            {k: v for k, v in result.items() if k != "scored_rows"}
            for result in results
        ],
        "comparisons": comparisons,
    }


def load_scenarios_file(path: str) -> list[ReplayScenario]:
    payload = json.loads(open(path, encoding="utf-8").read())
    items = payload if isinstance(payload, list) else payload.get("scenarios") or []
    if not items:
        raise ValueError("scenario file contains no scenarios")
    return [ReplayScenario.from_dict(item) for item in items]
