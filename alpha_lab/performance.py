"""Alpha Report Card analytics.

Pure functions that turn idea/trade performance rows into the Performance page
payload: an overall report card, a source-effectiveness leaderboard, a
market-regime breakdown, a recent-signals feed, and the composite "AlphaLabs IQ".

Everything here is derived from data the system already records: signal
evaluations (alert price, later price, early-detection score) plus source/regime
metadata, with trade P/L used only as a fallback for older rows. We never
fabricate numbers: when no signal has an evaluation or trade return, grades/IQ
come back as ``None`` and the caller renders an "accumulating" state.

Grading defaults (documented so they are easy to tune later):
  * Per-signal letter grade is taken straight from realized return:
    A >= +5%, B >= +2%, C > -2%, D > -5%, F <= -5%.
  * A group's 0-100 score blends win rate (60%) with a return factor (40%),
    where the return factor maps avg return via ``50 + avg_return*5`` clamped to
    [0, 100] (so flat = 50, +10% = 100, -10% = 0).
  * Letter grade from a 0-100 score: A >= 85, B >= 70, C >= 55, D >= 40, else F.
  * AlphaLabs IQ (0-100) = 0.35*accuracy + 0.25*consistency
    + 0.25*source_reliability + 0.15*regime_awareness.
"""

from __future__ import annotations

import json
from statistics import pstdev
from typing import Any, Callable


def grade_for_return(percent_return: Any) -> str | None:
    """Letter grade for a single signal from its realized/marked return (%)."""
    if not isinstance(percent_return, (int, float)):
        return None
    if percent_return >= 5:
        return "A"
    if percent_return >= 2:
        return "B"
    if percent_return > -2:
        return "C"
    if percent_return > -5:
        return "D"
    return "F"


def group_score(win_rate: float, avg_return: float) -> float:
    """0-100 quality score blending win rate (60%) and avg return (40%)."""
    return_factor = max(0.0, min(100.0, 50.0 + avg_return * 5.0))
    return round(0.6 * (win_rate * 100.0) + 0.4 * return_factor, 1)


def grade_for_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def grade_for_signal(row: dict[str, Any]) -> str | None:
    """Prefer validation grades, falling back to trade-return grades."""
    final_grade = row.get("final_grade")
    if isinstance(final_grade, str) and final_grade:
        return final_grade
    provisional_grade = row.get("provisional_grade")
    if isinstance(provisional_grade, str) and provisional_grade:
        return provisional_grade
    return grade_for_return(row.get("percent_return") if row.get("trade_id") else None)


def _signal_scores(items: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for item in items:
        value = item.get("early_detection_score")
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def _returns(items: list[dict[str, Any]]) -> list[float]:
    """Realized/marked returns for executed signals (those that became trades)."""
    out: list[float] = []
    for item in items:
        if not item.get("trade_id"):
            continue
        value = item.get("percent_return")
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def _contributions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-signal breakdown that explains how a group's grade was earned.

    Executed (graded) signals come first, highest return to lowest, followed by
    signals that never opened a paper trade (and so do not affect the grade).
    """
    out: list[dict[str, Any]] = []
    for item in items:
        score = item.get("early_detection_score")
        evaluated = isinstance(score, (int, float))
        value = item.get("percent_return")
        executed = bool(item.get("trade_id")) and isinstance(value, (int, float))
        out.append(
            {
                "ticker": item.get("ticker"),
                "evaluated": evaluated,
                "early_detection_score": round(float(score), 1) if evaluated else None,
                "move_after_pct": item.get("signal_move_after_pct"),
                "executed": executed,
                "percent_return": round(float(value), 4) if executed else None,
                "grade": grade_for_signal(item),
            }
        )
    out.sort(
        key=lambda c: (
            c["evaluated"],
            c["early_detection_score"] if c["early_detection_score"] is not None else -1e9,
            c["executed"],
            c["percent_return"] if c["percent_return"] is not None else -1e9,
        ),
        reverse=True,
    )
    return out


def _aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    scores = _signal_scores(items)
    if scores:
        moves = [
            float(item["signal_move_after_pct"])
            for item in items
            if isinstance(item.get("signal_move_after_pct"), (int, float))
        ]
        wins = [
            item for item in items
            if isinstance(item.get("signal_move_after_pct"), (int, float))
            and (
                (str(item.get("bias") or "").lower() == "bearish" and float(item["signal_move_after_pct"]) < 0)
                or (str(item.get("bias") or "").lower() != "bearish" and float(item["signal_move_after_pct"]) > 0)
            )
        ]
        avg_score = sum(scores) / len(scores)
        win_rate = len(wins) / len(scores)
        return {
            "signals": len({item.get("id") for item in items}),
            "executed": len(_returns(items)),
            "evaluated_signals": len(scores),
            "wins": len(wins),
            "win_rate": round(win_rate, 4),
            "avg_return": round(sum(moves) / len(moves), 4) if moves else 0.0,
            "avg_move_after_alert": round(sum(moves) / len(moves), 4) if moves else None,
            "best": round(max(moves), 4) if moves else 0.0,
            "worst": round(min(moves), 4) if moves else 0.0,
            "score": round(avg_score, 1),
            "grade": grade_for_score(avg_score),
            "score_math": {
                "win_rate_pct": round(win_rate * 100.0, 1),
                "win_component": None,
                "return_factor": None,
                "return_component": None,
                "early_detection_avg": round(avg_score, 1),
            },
            "contributions": _contributions(items),
        }
    returns = _returns(items)
    wins = [value for value in returns if value > 0]
    win_rate = (len(wins) / len(returns)) if returns else 0.0
    avg_return = (sum(returns) / len(returns)) if returns else 0.0
    return_factor = max(0.0, min(100.0, 50.0 + avg_return * 5.0)) if returns else None
    score = group_score(win_rate, avg_return) if returns else None
    return {
        "signals": len({item.get("id") for item in items}),
        "executed": len(returns),
        "evaluated_signals": 0,
        "wins": len(wins),
        "win_rate": round(win_rate, 4),
        "avg_return": round(avg_return, 4),
        "avg_move_after_alert": None,
        "best": round(max(returns), 4) if returns else 0.0,
        "worst": round(min(returns), 4) if returns else 0.0,
        "score": score,
        "grade": grade_for_score(score),
        # Exact math behind ``score`` so the UI can show the breakdown verbatim.
        "score_math": {
            "win_rate_pct": round(win_rate * 100.0, 1) if returns else None,
            "win_component": round(0.6 * win_rate * 100.0, 1) if returns else None,
            "return_factor": round(return_factor, 1) if return_factor is not None else None,
            "return_component": round(0.4 * return_factor, 1) if return_factor is not None else None,
        },
        "contributions": _contributions(items),
    }


def _leaderboard(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(key_fn(row) or "unknown"), []).append(row)
    output = []
    for name, items in groups.items():
        entry = {"name": name, **_aggregate(items)}
        output.append(entry)
    # Rank graded groups first (most evaluated, then score), ungraded last.
    output.sort(key=lambda g: (g.get("evaluated_signals", 0), g["executed"], g["score"] or -1), reverse=True)
    return output


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(tag) for tag in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(tag) for tag in parsed]
        except (ValueError, TypeError):
            return [value]
    return []


def _context_explainability(context: dict[str, Any] | None, regime_awareness: float | None) -> dict[str, Any]:
    context = context or {}
    futures = context.get("futures") or {}
    options = context.get("options") or {}
    return {
        "futures": {
            "available": bool(futures.get("available")),
            "affected_component": "regime_awareness" if futures.get("available") else None,
            "effect": "context only; regime-aware ideas can improve regime_awareness"
            if futures.get("available") else "no effect; futures data unavailable",
            "latest_regime": futures.get("regime") or "unknown",
            "latest_at": futures.get("latest_at") or "",
        },
        "options": {
            "available": bool(options.get("available")),
            "affected_component": "source_reliability" if options.get("available") and options.get("samples", 0) >= 10 else None,
            "effect": "context only; not enough samples to affect IQ"
            if options.get("available") and options.get("samples", 0) < 10
            else "no effect; options data unavailable"
            if not options.get("available")
            else "context only; source reliability eligible after sample threshold",
            "samples": int(options.get("samples") or 0),
            "latest_at": options.get("latest_at") or "",
        },
        "regime_awareness_score": regime_awareness,
    }


def _alpha_iq(rows: list[dict[str, Any]], source_board: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    scores = _signal_scores(rows)
    if scores:
        accuracy = (len([score for score in scores if score >= 55]) / len(scores)) * 100.0
        consistency = max(0.0, min(100.0, 100.0 - pstdev(scores))) if len(scores) > 1 else 100.0
        graded_sources = [g for g in source_board if g.get("evaluated_signals") and g["score"] is not None]
        total_eval = sum(g["evaluated_signals"] for g in graded_sources)
        source_reliability = (
            sum(g["score"] * g["evaluated_signals"] for g in graded_sources) / total_eval if total_eval else 0.0
        )
        evaluated_rows = [row for row in rows if isinstance(row.get("early_detection_score"), (int, float))]
        known_regime = [
            row for row in evaluated_rows
            if str(row.get("market_regime") or "unknown").lower() not in {"", "unknown"}
        ]
        regime_awareness = (len(known_regime) / len(evaluated_rows)) * 100.0 if evaluated_rows else 0.0
        score = round(
            0.35 * accuracy + 0.25 * consistency + 0.25 * source_reliability + 0.15 * regime_awareness
        )
        return {
            "score": score,
            "label": _iq_label(score),
            "components": {
                "signal_accuracy": round(accuracy, 1),
                "signal_consistency": round(consistency, 1),
                "source_reliability": round(source_reliability, 1),
                "regime_awareness": round(regime_awareness, 1),
            },
            "explainability": _context_explainability(context, round(regime_awareness, 1)),
        }
    returns = _returns(rows)
    if not returns:
        return {
            "score": None,
            "label": "Accumulating",
            "components": {
                "signal_accuracy": None,
                "signal_consistency": None,
                "source_reliability": None,
                "regime_awareness": None,
            },
            "explainability": _context_explainability(context, None),
        }
    wins = [value for value in returns if value > 0]
    accuracy = (len(wins) / len(returns)) * 100.0
    # Lower return spread = more consistent. pstdev in % points, clamped to 0-100.
    consistency = max(0.0, min(100.0, 100.0 - pstdev(returns))) if len(returns) > 1 else 100.0
    graded_sources = [g for g in source_board if g["executed"] and g["score"] is not None]
    total_exec = sum(g["executed"] for g in graded_sources)
    source_reliability = (
        sum(g["score"] * g["executed"] for g in graded_sources) / total_exec if total_exec else 0.0
    )
    executed_rows = [row for row in rows if row.get("trade_id") and isinstance(row.get("percent_return"), (int, float))]
    known_regime = [
        row for row in executed_rows
        if str(row.get("market_regime") or "unknown").lower() not in {"", "unknown"}
    ]
    regime_awareness = (len(known_regime) / len(executed_rows)) * 100.0 if executed_rows else 0.0
    score = round(
        0.35 * accuracy + 0.25 * consistency + 0.25 * source_reliability + 0.15 * regime_awareness
    )
    return {
        "score": score,
        "label": _iq_label(score),
        "components": {
            "signal_accuracy": round(accuracy, 1),
            "signal_consistency": round(consistency, 1),
            "source_reliability": round(source_reliability, 1),
            "regime_awareness": round(regime_awareness, 1),
        },
        "explainability": _context_explainability(context, round(regime_awareness, 1)),
    }


def _iq_label(score: int) -> str:
    if score >= 85:
        return "Sharp"
    if score >= 70:
        return "Solid"
    if score >= 55:
        return "Developing"
    if score >= 40:
        return "Inconsistent"
    return "Needs work"


def build_performance_report(rows: list[dict[str, Any]], recent_limit: int = 12, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the full Performance page payload from marked performance rows.

    ``rows`` are idea-performance rows already enriched with ``percent_return``
    (see ``AlphaLabService._with_performance_marks``), most-recent first.
    """
    overall = _aggregate(rows)
    source_board = _leaderboard(rows, lambda row: row.get("source") or "manual")
    regime_board = _leaderboard(rows, lambda row: str(row.get("market_regime") or "unknown").lower())

    recent = []
    for row in rows[:recent_limit]:
        explanation = row.get("trade_explanation") or {}
        percent_return = row.get("percent_return") if row.get("trade_id") else None
        move_after_pct = row.get("signal_move_after_pct")
        recent.append(
            {
                "id": row.get("id"),
                "ticker": row.get("ticker"),
                "bias": row.get("bias"),
                "source": row.get("source") or "manual",
                "source_tags": _parse_tags(row.get("source_tags")),
                "market_regime": str(row.get("market_regime") or "unknown").lower(),
                "status": row.get("status"),
                "trade_status": row.get("trade_status"),
                "executed": bool(row.get("trade_id")),
                "evaluated": isinstance(row.get("early_detection_score"), (int, float)),
                "evaluation_status": row.get("evaluation_status"),
                "early_detection_score": row.get("early_detection_score"),
                "alert_price": row.get("signal_alert_price"),
                "price_after": row.get("signal_price_after"),
                "move_after_pct": move_after_pct,
                "benchmark_move_pct": row.get("signal_benchmark_move_pct"),
                "percent_return": percent_return,
                "grade": grade_for_signal(row),
                "thesis_summary": explanation.get("thesis_summary") or row.get("thesis", ""),
                "opened_at": row.get("opened_at"),
                "created_at": row.get("created_at"),
            }
        )

    return {
        "report_card": {
            "overall_grade": overall["grade"],
            "overall_score": overall["score"],
            "total_signals": overall["signals"],
            "executed_signals": overall["executed"],
            "evaluated_signals": overall["evaluated_signals"],
            "win_rate": overall["win_rate"],
            "avg_return": overall["avg_return"],
            "avg_move_after_alert": overall["avg_move_after_alert"],
            "best_trade": overall["best"],
            "worst_trade": overall["worst"],
        },
        "source_leaderboard": source_board,
        "regime_dashboard": regime_board,
        "recent_signals": recent,
        "alpha_iq": _alpha_iq(rows, source_board, context=context),
    }
