"""Standard metric battery — every experiment reports the same statistics.

Pure functions over the frames produced by research.telemetry. Stdlib only.
Conventions:

- Hit rates carry a 95% Wilson interval; means carry a normal-approximation
  95% interval. Intervals are reported so promotion decisions compare
  interval bounds, never point estimates.
- Rows whose outcome label is still None (evaluation not yet filled) are
  excluded from outcome statistics but counted in ``coverage`` so thin label
  coverage is visible instead of silent.
"""
from __future__ import annotations

import math
from typing import Any, Callable

Z95 = 1.959964


# ── interval helpers ─────────────────────────────────────────────────────────

def wilson_interval(successes: int, n: int) -> dict[str, float] | None:
    """95% Wilson score interval for a binomial proportion."""
    if n <= 0:
        return None
    p = successes / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return {"rate": round(p, 4), "low": round(max(0.0, centre - half), 4),
            "high": round(min(1.0, centre + half), 4), "n": n}


def mean_interval(values: list[float]) -> dict[str, float] | None:
    """Mean with a normal-approximation 95% interval."""
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    if n == 1:
        return {"mean": round(mean, 4), "low": round(mean, 4), "high": round(mean, 4), "n": 1}
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    half = Z95 * math.sqrt(var / n)
    return {"mean": round(mean, 4), "low": round(mean - half, 4),
            "high": round(mean + half, 4), "n": n}


def _labeled(rows: list[dict[str, Any]], label_key: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r.get(label_key), (int, float))]


def outcome_summary(rows: list[dict[str, Any]], label_key: str = "excess_move_pct",
                    hit_key: str = "hit") -> dict[str, Any]:
    """Hit rate + mean label + label coverage for one population."""
    labeled = _labeled(rows, label_key)
    hits = [r for r in labeled if r.get(hit_key) == 1]
    return {
        "rows": len(rows),
        "labeled": len(labeled),
        "coverage": round(len(labeled) / len(rows), 4) if rows else None,
        "hit": wilson_interval(len(hits), len(labeled)),
        "label_mean": mean_interval([float(r[label_key]) for r in labeled]),
    }


# ── rank / monotonicity helpers ──────────────────────────────────────────────

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


# ── battery components ───────────────────────────────────────────────────────

def threshold_step(rows: list[dict[str, Any]], value_key: str, threshold: float,
                   near_margin_frac: float = 0.10, label_key: str = "excess_move_pct",
                   hit_key: str = "hit") -> dict[str, Any]:
    """Primary 'too strict vs correctly selective' test.

    Buckets the population into below / near-miss / above bands around the
    threshold and compares outcomes. A well-placed threshold shows a step in
    outcomes at the cutoff; a near-miss band performing like the above band is
    evidence the threshold is too strict (CALIBRATION_PLAN §4.1-4.2).
    """
    margin = near_margin_frac * abs(threshold) if threshold else near_margin_frac
    valued = [r for r in rows if isinstance(r.get(value_key), (int, float))]
    below = [r for r in valued if float(r[value_key]) < threshold - margin]
    near = [r for r in valued if threshold - margin <= float(r[value_key]) < threshold]
    above = [r for r in valued if float(r[value_key]) >= threshold]

    bands = {
        "below": outcome_summary(below, label_key, hit_key),
        "near_miss": outcome_summary(near, label_key, hit_key),
        "above": outcome_summary(above, label_key, hit_key),
    }
    near_hit, above_hit = bands["near_miss"]["hit"], bands["above"]["hit"]
    step_detected = None
    if near_hit and above_hit:
        # Distinguishable only when the intervals do not overlap.
        step_detected = near_hit["high"] < above_hit["low"]
    return {
        "value_key": value_key, "threshold": threshold, "near_margin": round(margin, 6),
        "bands": bands, "step_detected_vs_near_miss": step_detected,
        "pass_rate_at_threshold": round(len(above) / len(valued), 4) if valued else None,
    }


def simulated_pass_rate(rows: list[dict[str, Any]], value_key: str,
                        proposed_threshold: float) -> dict[str, Any]:
    """Offline what-if: pass rate if the threshold moved — computed from
    recorded observed values, never by editing the live threshold."""
    valued = [float(r[value_key]) for r in rows if isinstance(r.get(value_key), (int, float))]
    passing = sum(1 for v in valued if v >= proposed_threshold)
    return {"proposed_threshold": proposed_threshold, "n": len(valued),
            "pass_rate": round(passing / len(valued), 4) if valued else None}


def bucket_lift(rows: list[dict[str, Any]], value_key: str, buckets: int = 10,
                label_key: str = "excess_move_pct", hit_key: str = "hit") -> dict[str, Any]:
    """Outcome by score bucket + Spearman monotonicity of value vs label."""
    valued = [r for r in _labeled(rows, label_key) if isinstance(r.get(value_key), (int, float))]
    valued.sort(key=lambda r: float(r[value_key]))
    n = len(valued)
    out: list[dict[str, Any]] = []
    for b in range(buckets):
        chunk = valued[(b * n) // buckets:((b + 1) * n) // buckets]
        if not chunk:
            continue
        summary = outcome_summary(chunk, label_key, hit_key)
        summary["bucket"] = b + 1
        summary["value_min"] = round(float(chunk[0][value_key]), 4)
        summary["value_max"] = round(float(chunk[-1][value_key]), 4)
        out.append(summary)
    rho = spearman([float(r[value_key]) for r in valued],
                   [float(r[label_key]) for r in valued])
    return {"value_key": value_key, "buckets": out, "spearman_value_vs_label": rho}


def calibration_table(rows: list[dict[str, Any]], confidence_key: str = "confidence",
                      buckets: int = 5, hit_key: str = "hit",
                      label_key: str = "excess_move_pct") -> list[dict[str, Any]]:
    """Stated confidence vs realized hit rate, in equal-width confidence bins."""
    valued = [r for r in _labeled(rows, label_key)
              if isinstance(r.get(confidence_key), (int, float))]
    if not valued:
        return []
    lo = min(float(r[confidence_key]) for r in valued)
    hi = max(float(r[confidence_key]) for r in valued)
    width = (hi - lo) / buckets if hi > lo else 1.0
    table = []
    for b in range(buckets):
        left = lo + b * width
        right = hi if b == buckets - 1 else left + width
        chunk = [r for r in valued
                 if left <= float(r[confidence_key]) <= (right if b == buckets - 1 else right - 1e-12)]
        if not chunk:
            continue
        hits = sum(1 for r in chunk if r.get(hit_key) == 1)
        table.append({
            "confidence_low": round(left, 4), "confidence_high": round(right, 4),
            "stated_mean": round(sum(float(r[confidence_key]) for r in chunk) / len(chunk), 4),
            "realized_hit": wilson_interval(hits, len(chunk)),
        })
    return table


def session_stability(rows: list[dict[str, Any]], label_key: str = "excess_move_pct",
                      hit_key: str = "hit", min_rows_per_session: int = 3) -> dict[str, Any]:
    """Per-session outcome consistency. A real edge should not come from one
    lucky session; sign consistency is the share of qualifying sessions with a
    positive mean label."""
    sessions: dict[str, list[dict[str, Any]]] = {}
    for r in _labeled(rows, label_key):
        sessions.setdefault(str(r.get("session") or "unknown"), []).append(r)
    per_session = []
    positive = qualifying = 0
    for name in sorted(sessions):
        chunk = sessions[name]
        summary = outcome_summary(chunk, label_key, hit_key)
        summary["session"] = name
        per_session.append(summary)
        if len(chunk) >= min_rows_per_session and summary["label_mean"]:
            qualifying += 1
            if summary["label_mean"]["mean"] > 0:
                positive += 1
    return {
        "sessions": per_session,
        "session_count": len(per_session),
        "qualifying_sessions": qualifying,
        "positive_session_share": round(positive / qualifying, 4) if qualifying else None,
    }


def regret_analysis(decision_frame: list[dict[str, Any]], gate: str,
                    label_key: str = "excess_move_pct", hit_key: str = "hit") -> dict[str, Any]:
    """Forward outcome of a gate's near-miss rejections vs accepted decisions.

    High regret (near-miss band performing like the accepted band) marks the
    gate as a calibration candidate; low regret means correctly selective.
    Uses first-failed attribution so an attempt rejected earlier in the chain
    does not pollute this gate's rejected bands.
    """
    accepted = [r for r in decision_frame if r["accepted"]]
    rejected_here = [r for r in decision_frame
                     if not r["accepted"] and r.get("first_failed_gate") == gate]

    def failed_near(row: dict[str, Any]) -> bool:
        return any(g.get("gate") == gate and not g.get("passed") and g.get("near_miss")
                   for g in row["gates"])

    near = [r for r in rejected_here if failed_near(r)]
    far = [r for r in rejected_here if not failed_near(r)]

    result = {
        "gate": gate,
        "accepted": outcome_summary(accepted, label_key, hit_key),
        "rejected_near_miss": outcome_summary(near, label_key, hit_key),
        "rejected_far": outcome_summary(far, label_key, hit_key),
    }
    near_hit = result["rejected_near_miss"]["hit"]
    acc_hit = result["accepted"]["hit"]
    # Regret is flagged when the near-miss interval overlaps or exceeds the
    # accepted interval — the rejections were not distinguishably worse.
    result["regret_flag"] = (bool(near_hit and acc_hit and near_hit["high"] >= acc_hit["low"])
                             if (near_hit and acc_hit) else None)
    return result


# ── sample gates ─────────────────────────────────────────────────────────────

def sample_gates(checks: dict[str, tuple[int, int]]) -> dict[str, Any]:
    """Minimum-sample verdicts. ``checks`` maps a name to (observed, required).
    The experiment's evidence is not interpretable until every gate passes."""
    detail = {name: {"observed": obs, "required": req, "passed": obs >= req}
              for name, (obs, req) in checks.items()}
    return {"passed": all(d["passed"] for d in detail.values()), "detail": detail}
