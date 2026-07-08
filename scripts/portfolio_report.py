#!/usr/bin/env python3
"""Portfolio intelligence snapshot: exposure, concentration, theme tilt, heat,
cap utilization, and the conviction-sizing what-if.

Read-only diagnostics (local DB + risk config; no broker calls, no orders).
See docs/PORTFOLIO_INTELLIGENCE_AUDIT.md.

    python3 scripts/portfolio_report.py

Writes a timestamped JSON report to alpha_lab/data/portfolio/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_lab.portfolio import build_portfolio_snapshot
from alpha_lab.report_io import write_json_report
from scripts.diagnose_trading_pipeline import load_local_env

REPORT_DIR = ROOT / "alpha_lab" / "data" / "portfolio"


def write_report(report: dict, out_dir: Path = REPORT_DIR) -> Path:
    return write_json_report(report, out_dir, "portfolio")


def print_report(report: dict) -> None:
    conc = report["concentration"]
    print(f"positions: {report['n_positions']} (last sync {report['positions_synced_at']})")
    print(f"  gross exposure: ${conc['gross_exposure_usd']}")
    if conc["hhi"] is not None:
        print(f"  concentration: HHI={conc['hhi']} -> {conc['effective_positions']} effective positions; "
              f"largest position {conc['largest_position_share']:.0%} of gross")

    themes = report["theme_exposure"]
    if themes["breakdown"]:
        print("  theme exposure:")
        for row in themes["breakdown"]:
            share = f"{row['share']:.0%}" if row["share"] is not None else "-"
            print(f"    {row['theme']:16s} ${row['exposure_usd']:>12,.2f}  {share}")
        print(f"  top theme share: {themes['top_theme_share']:.0%}; "
              f"clustered (>=2 names same theme): {themes['clustered_exposure_share']:.0%}")

    heat = report["portfolio_heat"]
    print(f"  portfolio heat @ {heat['stop_loss_pct']:.0%} stops: ${heat['total_heat_usd']}")

    caps = report["cap_utilization"]
    print(f"  slots: {caps['open_positions']}/{caps['max_open_positions']} "
          f"({caps['position_slots_used']:.0%}); largest ${caps['largest_position_usd']} "
          f"vs per-trade cap ${caps['max_position_size_usd']}")

    whatif = report["conviction_sizing_whatif"]
    print(f"\nconviction-sizing what-if ({whatif['cohort']}, {whatif['n_scored']} scored trades):")
    if not whatif["rows"]:
        print(f"  {whatif.get('note', 'insufficient data')}")
    for row in whatif["rows"]:
        print(f"  {row['ticker']:10s} composite={row['alpha_composite']:<6g} "
              f"flat=${row['flat_notional_usd']:<9,.2f} "
              f"conviction=${row['conviction_notional_usd']:<9,.2f} "
              f"delta={row['delta_usd']:+,.2f}")
    if whatif["rows"]:
        print(f"  max single shift: ${whatif['max_single_shift_usd']} "
              f"of ${whatif['reallocated_pool_usd']} pool (caps unchanged)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", help="override DB path (defaults to env-resolved)")
    args = parser.parse_args()

    load_local_env()
    report = build_portfolio_snapshot(db_path=args.db_path)
    path = write_report(report)
    print_report(report)
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
