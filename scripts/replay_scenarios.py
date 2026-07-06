#!/usr/bin/env python3
"""Run offline scoring-replay scenarios against stored history.

Read-only diagnostics: re-scores historical ideas under candidate scoring
configurations and evaluates them against recorded outcomes. Never creates
ideas, decisions, orders, or trades. See docs/REPLAY_FRAMEWORK.md.

Usage:
    python3 scripts/replay_scenarios.py                      # baseline only
    python3 scripts/replay_scenarios.py --scenarios my.json  # baseline + candidates

Scenario file (JSON list, or {"scenarios": [...]}):
    [{"name": "financing-45",
      "description": "What if financing catalysts scored 45 instead of 35?",
      "catalyst_type_weights": {"financing": 45}}]

Reports are written to alpha_lab/data/replay/ as timestamped JSON; the console
shows the comparison table.
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

from alpha_lab.replay import load_scenarios_file, run_replay
from scripts.diagnose_trading_pipeline import load_local_env

REPORT_DIR = ROOT / "alpha_lab" / "data" / "replay"


def write_report(report: dict, out_dir: Path = REPORT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"replay-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_report(report: dict) -> None:
    fp = report["fingerprint"]
    print(f"dataset: {fp['row_count']} ideas ({fp['evaluated_count']} with outcomes), "
          f"{fp['first_generated_at']} .. {fp['last_generated_at']}, id-hash {fp['ids_sha256']}")
    if fp["evaluated_count"] < 30:
        print(f"  WARNING: only {fp['evaluated_count']} evaluated outcomes — treat every "
              "metric below as directional, not decisive (calibration plan wants >= 30).")

    header = (f"  {'scenario':22s} {'selected':>8s} {'sel%':>6s} {'hit%':>6s} "
              f"{'avg_move%':>9s} {'edge%':>7s} {'rank_corr':>9s}")
    print(header)
    for result in report["results"]:
        m = result["metrics"]
        sel = m["selected"]

        def fmt(value, pattern="{:.2f}") -> str:
            return pattern.format(value) if isinstance(value, (int, float)) else "-"

        print(f"  {result['scenario']['name'][:22]:22s} {m['n_selected']:8d} "
              f"{fmt((m['selection_rate'] or 0) * 100):>6s} "
              f"{fmt((sel['hit_rate'] or 0) * 100 if sel['hit_rate'] is not None else None):>6s} "
              f"{fmt(sel['avg_move_pct']):>9s} {fmt(m['selection_edge_pct']):>7s} "
              f"{fmt(m['rank_correlation_composite_vs_move'], '{:.3f}'):>9s}")

    for comparison in report["comparisons"]:
        print(f"  {comparison['candidate']} vs baseline: "
              f"+{comparison['newly_selected']['count']} newly selected "
              f"(hit% {comparison['newly_selected']['outcomes']['hit_rate']}), "
              f"-{comparison['newly_dropped']['count']} dropped "
              f"(hit% {comparison['newly_dropped']['outcomes']['hit_rate']}), "
              f"{comparison['unchanged']} unchanged")

    baseline = report["results"][0]["metrics"]
    print("  baseline calibration bands (composite -> outcome):")
    for band in baseline["calibration_bands"]:
        if band["n_with_outcome"]:
            print(f"    {band['band']:>7s}: n={band['n_with_outcome']:<4d} "
                  f"hit_rate={band['hit_rate']} avg_move={band['avg_move_pct']}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", help="JSON file of candidate scenarios")
    parser.add_argument("--db-path", help="override DB path (defaults to env-resolved)")
    args = parser.parse_args()

    load_local_env()
    scenarios = load_scenarios_file(args.scenarios) if args.scenarios else []
    report = run_replay(scenarios, db_path=args.db_path)
    path = write_report(report)
    print_report(report)
    print(f"report: {path}")


if __name__ == "__main__":
    main()
