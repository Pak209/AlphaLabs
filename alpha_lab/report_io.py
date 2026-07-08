"""
alpha_lab/report_io.py — shared I/O for the diagnostics report CLIs.

Extracted in Phase 2 PR3 (health-audit debt D7) from the five report scripts
(replay_scenarios, feature_attribution, outcome_report, portfolio_report,
waterfall_snapshot), which each carried their own copy of the same
timestamped-JSON writer. One implementation, one filename convention, one
place to fix (the microsecond suffix that prevents same-second collisions
was already fixed once in one copy — exactly the drift this ends).

Stdlib-only; no imports from other alpha_lab modules.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_json_report(report: dict[str, Any], out_dir: Path, prefix: str) -> Path:
    """Write a report as pretty, key-sorted JSON under a collision-proof name.

    Filename: ``{prefix}-YYYYMMDD-HHMMSS-microseconds.json`` (UTC) — the exact
    convention every diagnostics CLI already used, so existing snapshot
    directories keep sorting chronologically.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = out_dir / f"{prefix}-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def format_number(value: Any, pattern: str = "{:.2f}") -> str:
    """Format a number for table output, or '-' when the value is missing.

    The shared body behind each CLI's local ``_fmt``; scripts keep their own
    default pattern (they genuinely differ: percentages vs signed correlations).
    """
    return pattern.format(value) if isinstance(value, (int, float)) else "-"
