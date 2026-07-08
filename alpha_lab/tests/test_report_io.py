"""Focused tests for the shared report I/O (Phase 2 PR3).

Each CLI's own write/print behavior is already covered by its script test;
this pins the shared contract: filename convention, collision-proof naming,
JSON formatting, and the number formatter's missing-value fallback.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from alpha_lab.report_io import format_number, write_json_report

NAME_RE = re.compile(r"^replay-\d{8}-\d{6}-\d{6}\.json$")


def test_write_json_report_name_convention_and_content(tmp_path: Path):
    path = write_json_report({"b": 1, "a": {"z": None}}, tmp_path / "out", "replay")
    assert path.exists()
    assert NAME_RE.match(path.name), path.name
    # pretty, key-sorted JSON — the exact format the five CLIs always wrote
    assert path.read_text(encoding="utf-8") == '{\n  "a": {\n    "z": null\n  },\n  "b": 1\n}'
    assert json.loads(path.read_text())["b"] == 1


def test_write_json_report_collision_proof(tmp_path: Path):
    out = tmp_path / "out"
    paths = {write_json_report({}, out, "waterfall").name for _ in range(5)}
    assert len(paths) == 5                       # microsecond suffix: no overwrites


def test_format_number_patterns_and_fallback():
    assert format_number(0.7256) == "0.73"
    assert format_number(0.7256, "{:+.3f}") == "+0.726"
    assert format_number(None) == "-"
    assert format_number("n/a", "{:.2f}") == "-"
    assert format_number(True) == "1.00"          # bools are ints; documented quirk
