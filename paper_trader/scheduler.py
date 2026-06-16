from __future__ import annotations

from pathlib import Path

from .alpaca_client import AlpacaClient, AlpacaSafetyError, load_credentials_from_env
from .inbox_processor import process_inbox
from .runner import process_file
from .simulated_broker import SimulatedPaperBroker


MARKET_RUNS = {
    "premarket": (6, 0),
    "market_open": (6, 30),
    "midday": (9, 30),
    "power_hour": (12, 0),
    "after_close": (13, 30),
}


def start_scheduler(config_path: str, log_path: str, signals_dir: str, dry_run: bool) -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as exc:
        raise RuntimeError("APScheduler is not installed. Run: pip install -r paper_trader/requirements.txt") from exc

    scheduler = BlockingScheduler(timezone="America/Los_Angeles")

    for run_name, (hour, minute) in MARKET_RUNS.items():
        scheduler.add_job(
            _run_scheduled_inbox_then_file,
            "cron",
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            args=[run_name, config_path, log_path, signals_dir, dry_run],
            id=f"paper_trader_{run_name}",
            replace_existing=True,
        )

    scheduler.start()


def _run_scheduled_inbox_then_file(
    run_name: str, config_path: str, log_path: str, signals_dir: str, dry_run: bool
) -> None:
    broker = _build_broker(dry_run)
    process_inbox(
        "paper_trader/inbox",
        "paper_trader/processed",
        "paper_trader/rejected",
        config_path,
        log_path,
        broker,
        dry_run=dry_run,
    )

    signal_file = Path(signals_dir) / f"{run_name}.json"
    if not signal_file.exists():
        return
    process_file(signal_file, config_path, log_path, broker, dry_run=dry_run)


def _build_broker(dry_run: bool):
    try:
        return AlpacaClient(load_credentials_from_env())
    except AlpacaSafetyError:
        if not dry_run:
            raise
        return SimulatedPaperBroker()
