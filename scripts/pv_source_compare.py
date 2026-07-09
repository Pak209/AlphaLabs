#!/usr/bin/env python3
"""Side-by-side comparison: Polygon vs Alpaca price/volume confirmation inputs.

Read-only diagnostics for the Polygon-renewal decision: pulls both snapshots
for the approved equity book, reports per-ticker gap%/relative-volume deltas
and whether the PV CONFIRMATION VERDICT (trend direction + rel-vol >= 1.0
usability) would differ. Run during market hours across several sessions;
JSON accumulates in alpha_lab/data/pv_compare/ for the renewal evidence pack.

    python3 scripts/pv_source_compare.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_lab.live_sources import fetch_alpaca_intraday, fetch_polygon_intraday
from alpha_lab.report_io import format_number, write_json_report
from paper_trader.config import load_config
from scripts.diagnose_trading_pipeline import load_local_env

REPORT_DIR = ROOT / "alpha_lab" / "data" / "pv_compare"
DEADBAND = 0.25   # mirrors service._PV_GAP_DEADBAND_PCT


def direction(gap):
    if not isinstance(gap, (int, float)) or abs(gap) < DEADBAND:
        return "neutral"
    return "up" if gap > 0 else "down"


def main() -> None:
    load_local_env()
    tickers = sorted(t for t in load_config(str(ROOT / "alpha_lab/config.example.json")).approved_tickers
                     if "/" not in t and not t.endswith("USD"))
    rows, agree_dir, usable_both = [], 0, 0
    print(f"{'ticker':7s} {'gap poly':>9s} {'gap alp':>9s} {'d_gap':>7s} {'rv poly':>8s} {'rv alp':>8s} {'verdict':>9s}")
    for ticker in tickers:
        poly = fetch_polygon_intraday(ticker)
        alp = fetch_alpaca_intraday(ticker)
        row = {"ticker": ticker,
               "polygon": {k: poly.get(k) for k in ("status", "gap_pct", "relative_volume")},
               "alpaca": {k: alp.get(k) for k in ("status", "gap_pct", "relative_volume")}}
        pg, ag = poly.get("gap_pct"), alp.get("gap_pct")
        same_dir = direction(pg) == direction(ag)
        row["direction_agrees"] = same_dir
        agree_dir += bool(same_dir and poly.get("status") == alp.get("status") == "ok")
        if isinstance(poly.get("relative_volume"), (int, float)) and isinstance(alp.get("relative_volume"), (int, float)):
            usable_both += 1
        rows.append(row)
        d_gap = (pg - ag) if isinstance(pg, (int, float)) and isinstance(ag, (int, float)) else None
        print(f"{ticker:7s} {format_number(pg, '{:+.2f}'):>9s} {format_number(ag, '{:+.2f}'):>9s} "
              f"{format_number(d_gap, '{:+.2f}'):>7s} {format_number(poly.get('relative_volume')):>8s} "
              f"{format_number(alp.get('relative_volume')):>8s} {'AGREE' if same_dir else 'DIFFER':>9s}")
    ok = [r for r in rows if r["polygon"]["status"] == r["alpaca"]["status"] == "ok"]
    summary = {"tickers": len(tickers), "both_ok": len(ok),
               "direction_agreement": agree_dir, "rel_volume_usable_both": usable_both}
    print(f"\nsummary: {summary}")
    path = write_json_report({"summary": summary, "rows": rows}, REPORT_DIR, "pv-compare")
    print(f"report: {path}")


if __name__ == "__main__":
    main()
