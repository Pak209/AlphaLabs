"""
alpha_lab/portfolio.py — read-only portfolio intelligence snapshot.

Measures the CURRENT portfolio posture — exposure, concentration, theme
tilt, heat under the configured stops, cap utilization, and a
conviction-weighted sizing what-if — without changing any sizing, gate, or
order behavior. This is the diagnostics layer for the portfolio roadmap in
docs/PORTFOLIO_INTELLIGENCE_AUDIT.md: every metric here is the "before"
picture that a future (approval-gated) sizing change would be judged against.

Strictly read-only: SELECTs on the local DB plus the risk-config JSON. It
never calls the broker, never sizes a live order, never touches gates.

Notes on inputs:
  * `positions` table — the last Alpaca paper sync (market_value, qty).
  * `trades` — open paper trades preferred; when none exist (stabilization
    runs everything dry-run) the conviction what-if falls back to the most
    recent accepted dry-run trades and says so via `cohort`.
  * theme mapping — scoring_engine.TICKER_THEME via narrative_inputs_for_ticker
    (the same map the narrative component uses), so "sector" here means the
    platform's own theme taxonomy. Theme overlap is a CORRELATION PROXY only;
    real pairwise return correlation needs bar history (roadmap item).
"""
from __future__ import annotations

from typing import Any

from paper_trader.config import load_config

from .database import connect, resolve_db_path
from .scoring_engine import narrative_inputs_for_ticker

DEFAULT_RISK_CONFIG = "alpha_lab/config.example.json"
WHATIF_COHORT_LIMIT = 12   # recent trades used for the conviction what-if


def _theme(ticker: str) -> str:
    return narrative_inputs_for_ticker(ticker).theme


def _positions(conn) -> list[dict[str, Any]]:
    rows = [dict(r) for r in conn.execute(
        "SELECT ticker, qty, market_value, unrealized_pl, synced_at FROM positions WHERE qty != 0"
    ).fetchall()]
    for row in rows:
        row["theme"] = _theme(str(row["ticker"]))
    return rows


def _whatif_cohort(conn) -> tuple[list[dict[str, Any]], str]:
    """Open paper trades if any; else recent accepted dry-run trades."""
    open_paper = [dict(r) for r in conn.execute(
        "SELECT ticker, notional, alpha_composite FROM trades "
        "WHERE status = 'paper_open' AND notional IS NOT NULL ORDER BY id DESC"
    ).fetchall()]
    if open_paper:
        return open_paper, "open_paper_trades"
    dry = [dict(r) for r in conn.execute(
        "SELECT ticker, notional, alpha_composite FROM trades "
        "WHERE dry_run = 1 AND notional IS NOT NULL ORDER BY id DESC LIMIT ?",
        (WHATIF_COHORT_LIMIT,),
    ).fetchall()]
    return dry, "recent_dry_run_trades"


# ─── Metrics ──────────────────────────────────────────────────────────────────

def concentration(positions: list[dict[str, Any]]) -> dict[str, Any]:
    values = [abs(float(p.get("market_value") or 0)) for p in positions]
    gross = sum(values)
    if gross <= 0:
        return {"gross_exposure_usd": 0.0, "largest_position_share": None,
                "hhi": None, "effective_positions": None}
    shares = [v / gross for v in values]
    hhi = sum(s * s for s in shares)
    return {
        "gross_exposure_usd": round(gross, 2),
        "largest_position_share": round(max(shares), 4),
        # HHI in (0,1]; 1/HHI = "effective number of equally-sized positions".
        "hhi": round(hhi, 4),
        "effective_positions": round(1 / hhi, 2),
    }


def theme_exposure(positions: list[dict[str, Any]]) -> dict[str, Any]:
    gross = sum(abs(float(p.get("market_value") or 0)) for p in positions)
    by_theme: dict[str, float] = {}
    for p in positions:
        by_theme[p["theme"]] = by_theme.get(p["theme"], 0.0) + abs(float(p.get("market_value") or 0))
    breakdown = [
        {"theme": theme, "exposure_usd": round(value, 2),
         "share": round(value / gross, 4) if gross > 0 else None}
        for theme, value in sorted(by_theme.items(), key=lambda kv: -kv[1])
    ]
    top_share = breakdown[0]["share"] if breakdown else None
    # Theme-overlap correlation proxy: share of gross exposure that sits in a
    # theme alongside at least one OTHER position (names that tend to move
    # together in a theme shock). Not a return correlation — see module doc.
    clustered = sum(
        b["exposure_usd"] for b in breakdown
        if sum(1 for p in positions if p["theme"] == b["theme"]) >= 2
    )
    return {
        "breakdown": breakdown,
        "top_theme_share": top_share,
        "clustered_exposure_share": round(clustered / gross, 4) if gross > 0 else None,
    }


def portfolio_heat(positions: list[dict[str, Any]], stop_loss_pct: float) -> dict[str, Any]:
    """Risk-to-stop under the configured flat stop: Σ |market_value| × stop%.

    With flat percentage stops the heat is uniform per dollar — which is
    itself the finding: identical stops on names with different volatility
    means UNEQUAL real risk. The per-position table exists so a future
    volatility-aware stop proposal has a baseline to compare against.
    """
    per_position = [
        {"ticker": p["ticker"],
         "risk_to_stop_usd": round(abs(float(p.get("market_value") or 0)) * stop_loss_pct, 2)}
        for p in positions
    ]
    total = round(sum(row["risk_to_stop_usd"] for row in per_position), 2)
    gross = sum(abs(float(p.get("market_value") or 0)) for p in positions)
    return {
        "stop_loss_pct": stop_loss_pct,
        "total_heat_usd": total,
        "heat_share_of_gross": round(total / gross, 4) if gross > 0 else None,
        "per_position": per_position,
    }


def cap_utilization(positions: list[dict[str, Any]], config) -> dict[str, Any]:
    values = [abs(float(p.get("market_value") or 0)) for p in positions]
    return {
        "open_positions": len(positions),
        "max_open_positions": config.max_open_positions,
        "position_slots_used": round(len(positions) / config.max_open_positions, 4),
        "largest_position_usd": round(max(values), 2) if values else 0.0,
        "max_position_size_usd": config.max_position_size_usd,
        "note": "count-based caps only; no aggregate notional, theme, or heat cap exists today",
    }


def conviction_sizing_whatif(cohort: list[dict[str, Any]], cohort_name: str) -> dict[str, Any]:
    """Flat sizing (today) vs composite-proportional sizing of the SAME total.

    Reallocates the cohort's existing total notional in proportion to each
    trade's stored alpha_composite. Same capital, same trades, no cap change —
    purely what conviction-weighting would have shifted. Trades without a
    stored composite score keep their flat allocation and are excluded from
    the reallocation pool.
    """
    scored = [t for t in cohort if isinstance(t.get("alpha_composite"), (int, float))]
    if len(scored) < 2:
        return {"cohort": cohort_name, "n_trades": len(cohort), "n_scored": len(scored),
                "note": "need >= 2 trades with stored alpha_composite for a reallocation",
                "rows": []}
    pool = sum(float(t["notional"]) for t in scored)
    total_score = sum(float(t["alpha_composite"]) for t in scored)
    rows = []
    for t in scored:
        flat = float(t["notional"])
        weighted = pool * float(t["alpha_composite"]) / total_score if total_score > 0 else flat
        rows.append({
            "ticker": t["ticker"],
            "alpha_composite": float(t["alpha_composite"]),
            "flat_notional_usd": round(flat, 2),
            "conviction_notional_usd": round(weighted, 2),
            "delta_usd": round(weighted - flat, 2),
        })
    rows.sort(key=lambda r: -r["alpha_composite"])
    max_shift = max((abs(r["delta_usd"]) for r in rows), default=0.0)
    return {
        "cohort": cohort_name,
        "n_trades": len(cohort),
        "n_scored": len(scored),
        "reallocated_pool_usd": round(pool, 2),
        "max_single_shift_usd": round(max_shift, 2),
        "rows": rows,
    }


def build_portfolio_snapshot(db_path: str | None = None,
                             risk_config_path: str = DEFAULT_RISK_CONFIG) -> dict[str, Any]:
    config = load_config(risk_config_path)
    path = resolve_db_path(db_path)
    with connect(path) as conn:
        positions = _positions(conn)
        cohort, cohort_name = _whatif_cohort(conn)
        last_sync = conn.execute("SELECT MAX(synced_at) FROM positions").fetchone()[0]

    return {
        "positions_synced_at": last_sync,
        "n_positions": len(positions),
        "concentration": concentration(positions),
        "theme_exposure": theme_exposure(positions),
        "portfolio_heat": portfolio_heat(positions, config.stop_loss_pct),
        "cap_utilization": cap_utilization(positions, config),
        "conviction_sizing_whatif": conviction_sizing_whatif(cohort, cohort_name),
        "caveats": [
            "Theme overlap is a correlation proxy; real pairwise return correlation needs bar history (roadmap).",
            "Heat assumes the flat configured stop on every equity position; options excluded.",
            "Positions reflect the last Alpaca paper sync, not a live query.",
        ],
    }
