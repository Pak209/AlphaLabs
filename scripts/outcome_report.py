#!/usr/bin/env python3
"""Outcome report: how AlphaLabs ideas performed after they were generated.

Read-only diagnostics grouped by source, catalyst type, bias, score band,
gate result, and accepted/rejected status, plus the near-miss regret table.
Never creates ideas, decisions, orders, or trades.
See docs/OUTCOME_REPORTING.md.

    python3 scripts/outcome_report.py

Writes a timestamped JSON report to alpha_lab/data/outcomes/.
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

from alpha_lab.outcomes import outcome_report
from scripts.diagnose_trading_pipeline import load_local_env

REPORT_DIR = ROOT / "alpha_lab" / "data" / "outcomes"


def write_report(report: dict, out_dir: Path = REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"outcomes-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _fmt(value, pattern="{:.2f}") -> str:
    return pattern.format(value) if isinstance(value, (int, float)) else "-"


def _print_table(title: str, rows: list[dict], label_key: str) -> None:
    print(f"\n{title}:")
    print(f"  {'group':30s} {'ideas':>6s} {'w/outc':>7s} {'hit%':>6s} {'avg%':>7s} {'med%':>7s}")
    for row in rows:
        label = str(row.get(label_key, "?"))[:30]
        hit = row.get("hit_rate")
        print(f"  {label:30s} {row.get('n_ideas', 0):6d} {row['n_with_outcome']:7d} "
              f"{_fmt(hit * 100 if isinstance(hit, (int, float)) else None):>6s} "
              f"{_fmt(row['avg_move_pct']):>7s} {_fmt(row['median_move_pct']):>7s}")


def print_report(report: dict) -> None:
    fp = report["fingerprint"]
    overall = report["overall"]
    print(f"dataset: {overall['n_ideas']} ideas, {fp['evaluated_count']} with outcomes, "
          f"{fp['first_generated_at']} .. {fp['last_generated_at']}")
    if fp["evaluated_count"] < 30:
        print(f"  WARNING: {fp['evaluated_count']} outcomes < 30 — directional only.")
    print(f"  statuses: {overall['status_counts']}")
    print(f"  overall: hit_rate={overall['hit_rate']} avg_move={overall['avg_move_pct']}% "
          f"median={overall['median_move_pct']}%")

    _print_table("composite score bands (replayed baseline)",
                 report["score_bands"]["replay_composite"], "band")
    _print_table("confidence bands", report["score_bands"]["confidence"], "band")
    _print_table("by source", report["by_source"], "group")
    _print_table("by catalyst type", report["by_catalyst_type"], "group")
    _print_table("by bias", report["by_bias"], "group")
    _print_table("by gate result (first failed gate)", report["by_gate_result"], "group")

    avr = report["accepted_vs_rejected"]
    print("\naccepted vs rejected (pipeline status):")
    for name in ("accepted", "rejected"):
        stats = avr[name]
        print(f"  {name:9s} n={stats['n_ideas']:<4d} with_outcome={stats['n_with_outcome']:<4d} "
              f"hit_rate={stats['hit_rate']} avg_move={stats['avg_move_pct']}%")
    print(f"  other: {avr['other']['n_ideas']} ({', '.join(avr['other']['statuses']) or 'none'})")
    print(f"  acceptance edge: {avr['acceptance_edge_pct']}%")

    near = report["near_miss"]
    ref = near["accepted_reference"]
    print(f"\nnear-miss performance (failed a gate by <= {near['margin']:.0%} of threshold):")
    print(f"  accepted reference: n={ref['n_ideas']} hit_rate={ref['hit_rate']} avg={ref['avg_move_pct']}%")
    if not near["gates"]:
        print("  no near-misses recorded yet (structured traces accrue with each session)")
    for gate in near["gates"]:
        print(f"  {gate['gate']:26s} n={gate['n_near_miss']:<4d} with_outcome={gate['n_with_outcome']:<4d} "
              f"hit_rate={gate['hit_rate']} avg={gate['avg_move_pct']}%")
        if gate["verdict_vs_accepted"]:
            print(f"    -> {gate['verdict_vs_accepted']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", help="override DB path (defaults to env-resolved)")
    args = parser.parse_args()

    load_local_env()
    report = outcome_report(db_path=args.db_path)
    path = write_report(report)
    print_report(report)
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
