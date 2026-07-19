"""The options-validation candidate list rotates daily.

Regression for the PLTR monoculture: a fixed priority order meant the first
liquid name won every run, so the approval queue only ever showed one ticker.
"""
from __future__ import annotations

import datetime
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "validate_options_lifecycle",
    Path("scripts/validate_options_lifecycle.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_rotation_changes_leader_across_days(monkeypatch):
    monkeypatch.delenv("OPTIONS_VALIDATION_CANDIDATES", raising=False)
    leaders = {mod.candidates_for_today(datetime.date(2026, 7, d))[0]
               for d in range(1, 11)}
    assert len(leaders) == len(mod.DEFAULT_CANDIDATES)   # every name leads once
    # same day -> same order (reproducible reruns)
    assert (mod.candidates_for_today(datetime.date(2026, 7, 18))
            == mod.candidates_for_today(datetime.date(2026, 7, 18)))
    # rotation preserves the full set
    assert sorted(mod.candidates_for_today(datetime.date(2026, 7, 18))) \
        == sorted(mod.DEFAULT_CANDIDATES)


def test_env_override_replaces_list(monkeypatch):
    monkeypatch.setenv("OPTIONS_VALIDATION_CANDIDATES", "tsla, amd,COIN")
    order = mod.candidates_for_today(datetime.date(2026, 7, 18))
    assert sorted(order) == ["AMD", "COIN", "TSLA"]
