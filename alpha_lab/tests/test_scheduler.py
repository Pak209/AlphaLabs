"""Tests for the automation scheduler's mode switch (Pattern B vs C).

The safety property under test: the scheduler is dry-run by default and only
arms paper orders when ALPHALAB_SCHEDULER_MODE is explicitly 'paper'.
"""
from __future__ import annotations

import pytest

from alpha_lab import scheduler


def test_default_mode_is_dry_run(monkeypatch):
    monkeypatch.delenv("ALPHALAB_SCHEDULER_MODE", raising=False)
    assert scheduler.automation_mode() == "dry_run"
    assert scheduler._dry_run() is True


def test_paper_mode_when_explicitly_set(monkeypatch):
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "paper")
    assert scheduler.automation_mode() == "paper"
    assert scheduler._dry_run() is False


def test_paper_mode_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "  PAPER  ")
    assert scheduler.automation_mode() == "paper"


@pytest.mark.parametrize("value", ["dry_run", "", "dryrun", "live", "true", "1", "yes"])
def test_anything_but_paper_stays_dry_run(monkeypatch, value):
    # Only the exact token 'paper' arms orders; everything else is safe.
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", value)
    assert scheduler.automation_mode() == "dry_run"
    assert scheduler._dry_run() is True


def test_scheduler_safety_status_is_safe_by_default(monkeypatch):
    monkeypatch.delenv("ALPHALAB_SCHEDULER_MODE", raising=False)
    monkeypatch.delenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", raising=False)

    status = scheduler.scheduler_safety_status()

    assert status["scheduler_mode"] == "dry_run"
    assert status["automation_paper_trading_armed"] is False
    assert status["paper_trades_can_be_triggered_by_scheduler"] is False
    assert status["safe_stabilization_mode"] is True


def test_scheduler_safety_status_detects_fully_armed_paper_mode(monkeypatch):
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "paper")
    monkeypatch.setenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "true")

    status = scheduler.scheduler_safety_status()

    assert status["scheduler_mode"] == "paper"
    assert status["automation_paper_trading_armed"] is True
    assert status["scheduler_paper_jobs_enabled"] is True
    assert status["paper_trades_can_be_triggered_by_scheduler"] is True
    assert status["safe_stabilization_mode"] is False


def test_scheduler_safety_status_reports_half_armed_states(monkeypatch):
    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "paper")
    monkeypatch.delenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", raising=False)
    assert scheduler.scheduler_safety_status()["paper_trades_can_be_triggered_by_scheduler"] is False
    assert scheduler.scheduler_safety_status()["safe_stabilization_mode"] is False

    monkeypatch.setenv("ALPHALAB_SCHEDULER_MODE", "dry_run")
    monkeypatch.setenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "true")
    assert scheduler.scheduler_safety_status()["paper_trades_can_be_triggered_by_scheduler"] is False
    assert scheduler.scheduler_safety_status()["safe_stabilization_mode"] is False


def test_build_scheduler_registers_all_jobs(monkeypatch):
    monkeypatch.delenv("ALPHALAB_SCHEDULER_MODE", raising=False)
    # Jobs are stored as lambdas and not invoked at build time, so a sentinel
    # service is sufficient to introspect the wiring without a DB.
    sched = scheduler.build_scheduler(service=object())
    jobs = sched.get_jobs()
    # 1 heartbeat + 6 always-safe + 2 premarket context pulls
    # + 6 weekday idea/trade + 1 always-on crypto + 2 weekend read jobs = 18
    assert len(jobs) == 18
    assert all(job.trigger is not None for job in jobs)


def test_overnight_futures_pull_is_weekday_early_am():
    # The futures backtest fill runs mon-fri at 6:05am PT (before the cash open).
    # Jobs are lambda wrappers, so match on the distinctive trigger shape.
    sched = scheduler.build_scheduler(service=object())
    weekday_six_05 = [
        j for j in sched.get_jobs()
        if {f.name: str(f) for f in j.trigger.fields}.get("day_of_week") in {"mon-fri", "0-4"}
        and {f.name: str(f) for f in j.trigger.fields}.get("hour") == "6"
        and {f.name: str(f) for f in j.trigger.fields}.get("minute") == "5"
    ]
    assert len(weekday_six_05) == 1


def test_options_flow_preview_is_weekday_premarket():
    sched = scheduler.build_scheduler(service=object())
    weekday_six_12 = [
        j for j in sched.get_jobs()
        if {f.name: str(f) for f in j.trigger.fields}.get("day_of_week") in {"mon-fri", "0-4"}
        and {f.name: str(f) for f in j.trigger.fields}.get("hour") == "6"
        and {f.name: str(f) for f in j.trigger.fields}.get("minute") == "12"
    ]
    assert len(weekday_six_12) == 1


def test_crypto_dry_run_scanner_runs_24_7():
    sched = scheduler.build_scheduler(service=object())
    crypto_jobs = [j for j in sched.get_jobs() if j.id == "crypto_24_7_dry_run"]
    assert len(crypto_jobs) == 1
    fields = {f.name: str(f) for f in crypto_jobs[0].trigger.fields}
    assert fields["day_of_week"] in {"mon-sun", "0-6"}
    assert fields["hour"] == "0-23"
    assert fields["minute"] == "*/30"


def test_weekend_read_jobs_run_only_on_sat_sun():
    sched = scheduler.build_scheduler(service=object())
    weekend_jobs = [
        j for j in sched.get_jobs()
        if ("sat" in str(j.trigger) or "sun" in str(j.trigger)) and j.id != "crypto_24_7_dry_run"
    ]
    assert len(weekend_jobs) == 2
    for job in weekend_jobs:
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields["day_of_week"] in {"sat,sun", "5,6"}
