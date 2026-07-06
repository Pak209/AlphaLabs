#!/usr/bin/env python3
"""Snapshot the rejection waterfall and diff it against the previous snapshot.

Read-only diagnostics: aggregates existing telemetry (execution_audit,
scanner_runs, alpha_ideas, trades) via AlphaLabService.rejection_waterfall()
and writes a timestamped JSON file to alpha_lab/data/waterfall/. It never
creates ideas, decisions, orders, or trades.

Run once after each trading session (e.g. ~14:15 PT, after the 13:50 PT
signal-evaluation job) so the calibration protocol has one comparable sample
per session:

    python3 scripts/waterfall_snapshot.py

The delta report shows, per gate, how many NEW failures accrued since the
previous snapshot — the number that should trend toward zero for gates fixed
at the source (crypto_long_only, market_open) and the number that feeds
near-miss analysis for calibration candidates (confidence, alpha gate).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_lab.service import AlphaLabService
from scripts.diagnose_trading_pipeline import load_local_env

SNAPSHOT_DIR = ROOT / "alpha_lab" / "data" / "waterfall"


def take_snapshot(service: AlphaLabService, out_dir: Path = SNAPSHOT_DIR) -> Path:
    """Write one timestamped waterfall snapshot; return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report = service.rejection_waterfall()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"waterfall-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def previous_snapshot(out_dir: Path, current: Path) -> Path | None:
    snapshots = sorted(p for p in out_dir.glob("waterfall-*.json") if p != current)
    return snapshots[-1] if snapshots else None


def print_delta(current_path: Path, previous_path: Path | None) -> None:
    current = json.loads(current_path.read_text(encoding="utf-8"))
    print(f"snapshot: {current_path}")
    window = current["window"]
    print(f"  attempts analyzed: {window['audit_rows_analyzed']} "
          f"({window['structured_rows']} structured, {window['legacy_rows']} legacy)")

    if previous_path is None:
        print("  no previous snapshot to compare against (first sample)")
        return

    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    print(f"  compared to: {previous_path.name}")

    def by_gate(report: dict) -> dict[str, dict]:
        return {b["gate"]: b for b in report.get("gate_failures", [])}

    current_gates, previous_gates = by_gate(current), by_gate(previous)
    print(f"  {'gate':26s} {'failures':>9s} {'new':>5s} {'near-miss new':>14s}")
    for name in sorted(set(current_gates) | set(previous_gates)):
        now = current_gates.get(name, {})
        before = previous_gates.get(name, {})
        new_failures = int(now.get("failures", 0)) - int(before.get("failures", 0))
        new_near = int(now.get("near_misses", 0)) - int(before.get("near_misses", 0))
        if now.get("failures", 0) or new_failures:
            print(f"  {name:26s} {now.get('failures', 0):9d} {new_failures:+5d} {new_near:+14d}")

    current_stages = {row["stage"]: row["count"] for row in current.get("stage_funnel", [])}
    previous_stages = {row["stage"]: row["count"] for row in previous.get("stage_funnel", [])}
    print(f"  {'stage':26s} {'count':>9s} {'new':>5s}")
    for name, count in current_stages.items():
        print(f"  {name:26s} {count:9d} {count - previous_stages.get(name, 0):+5d}")


def main() -> None:
    load_local_env()
    service = AlphaLabService()
    current = take_snapshot(service)
    print_delta(current, previous_snapshot(SNAPSHOT_DIR, current))


if __name__ == "__main__":
    main()
