#!/usr/bin/env python3
"""Feature-attribution report: which scoring inputs correlate with outcomes.

Read-only diagnostics over the replay dataset, signal evaluations, and
structured gate traces. Never creates ideas, decisions, orders, or trades.
See docs/FEATURE_ATTRIBUTION.md for methodology and interpretation.

    python3 scripts/feature_attribution.py

Writes a timestamped JSON report to alpha_lab/data/attribution/ and prints the
importance ranking, dead inputs, selected-vs-rejected gaps, and gate regret.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_lab.attribution import feature_attribution_report
from scripts.diagnose_trading_pipeline import load_local_env

REPORT_DIR = ROOT / "alpha_lab" / "data" / "attribution"


def write_report(report: dict, out_dir: Path = REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"attribution-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fmt(value, pattern="{:+.3f}") -> str:
    return pattern.format(value) if isinstance(value, (int, float)) else "-"


def print_report(report: dict) -> None:
    fp = report["fingerprint"]
    print(f"dataset: {fp['row_count']} ideas, {fp['evaluated_count']} with outcomes, "
          f"id-hash {fp['ids_sha256']}")
    if fp["evaluated_count"] < 30:
        print(f"  WARNING: {fp['evaluated_count']} outcomes < 30 — treat rankings as directional only.")

    print("\nfeature importance (outcome correlation):")
    print(f"  {'feature':28s} {'spearman':>9s} {'split_move_d%':>13s} {'split_hit_d':>11s} {'n':>4s}")
    for row in report["importance_ranking"]:
        print(f"  {row['feature']:28s} {_fmt(row['spearman']):>9s} "
              f"{_fmt(row['split_avg_move_delta_pct'], '{:+.2f}'):>13s} "
              f"{_fmt(row['split_hit_rate_delta'], '{:+.2f}'):>11s} {row['n_with_outcome']:4d}")

    if report["dead_inputs"]:
        print(f"\ndead inputs (no variance — unwired data sources): {', '.join(report['dead_inputs'])}")

    svr = report["selected_vs_rejected"]
    print(f"\nselected vs rejected (baseline bars): {svr['n_selected']} selected / {svr['n_rejected']} rejected")
    sel, rej = svr["selected_outcomes"], svr["rejected_outcomes"]
    print(f"  outcomes: selected hit_rate={sel['hit_rate']} avg={sel['avg_move_pct']}% | "
          f"rejected hit_rate={rej['hit_rate']} avg={rej['avg_move_pct']}%")
    for gap in svr["feature_gaps"][:6]:
        print(f"  {gap['feature']:28s} sel_median={gap['median_selected']:>9.3f} "
              f"rej_median={gap['median_rejected']:>9.3f} gap={gap['selection_gap']:+.3f}")

    regret = report["gate_regret"]
    print(f"\ngate regret ({regret['structured_ideas']} structured ideas, "
          f"{regret['legacy_rows_skipped']} legacy rows skipped):")
    for gate in regret["gates"]:
        print(f"  {gate['gate']:26s} rejected={gate['n_rejected']:<4d} "
              f"with_outcome={gate['n_with_outcome']:<4d} regret_rate={gate['regret_rate']} "
              f"avg_missed_move={gate['avg_missed_move_pct']}%")

    print("\ncategorical spreads (best-vs-worst avg move, groups >= 3):")
    for cat in report["categorical_features"]:
        if cat["best_worst_avg_move_spread_pct"] is not None:
            best = cat["levels"][0]
            worst = cat["levels"][-1]
            print(f"  {cat['feature']:16s} spread={cat['best_worst_avg_move_spread_pct']:+.2f}% "
                  f"(best '{best['level']}' {best['avg_move_pct']}%, worst '{worst['level']}' {worst['avg_move_pct']}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", help="override DB path (defaults to env-resolved)")
    args = parser.parse_args()

    load_local_env()
    report = feature_attribution_report(db_path=args.db_path)
    path = write_report(report)
    print_report(report)
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
