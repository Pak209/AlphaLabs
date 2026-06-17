from __future__ import annotations

import os

from apscheduler.schedulers.blocking import BlockingScheduler

from paper_trader.inbox_processor import process_inbox

from .env import load_dotenv
from .service import AlphaLabService

# --------------------------------------------------------------------------- #
# Execution mode
# --------------------------------------------------------------------------- #
# The scheduler runs the same job set in two modes, switched by ONE env var:
#
#   ALPHALAB_SCHEDULER_MODE=dry_run   (default)  -> Pattern B: generate + score
#       ideas all day, place NO orders. Safe to run unattended for review.
#   ALPHALAB_SCHEDULER_MODE=paper                -> Pattern C: the idea-testing
#       jobs place Alpaca *paper* orders.
#
# Going B -> C is a one-line .env change + an agent reload; no code edit needed.
# Paper orders additionally require ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true
# (enforced in AlphaLabService.import_and_test) — defense in depth, so flipping
# this flag alone cannot place real paper orders unless automation is also armed.


def automation_mode() -> str:
    """Return 'paper' or 'dry_run' (default) from ALPHALAB_SCHEDULER_MODE."""
    mode = os.getenv("ALPHALAB_SCHEDULER_MODE", "dry_run").strip().lower()
    return "paper" if mode == "paper" else "dry_run"


def automation_paper_trading_armed() -> bool:
    """Return whether the second automation-paper-trade guard is armed."""
    return os.getenv("ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES", "").strip().lower() == "true"


def scheduler_safety_status() -> dict[str, object]:
    """Read-only summary of whether scheduler jobs can place paper orders."""
    mode = automation_mode()
    paper_guard_armed = automation_paper_trading_armed()
    scheduler_paper_jobs_enabled = mode == "paper"
    paper_trades_can_be_triggered_by_scheduler = scheduler_paper_jobs_enabled and paper_guard_armed
    safe_stabilization_mode = mode == "dry_run" and not paper_guard_armed
    if safe_stabilization_mode:
        recommendation = "safe for stabilization: scheduler dry_run and automation paper-trade guard disarmed"
    elif paper_trades_can_be_triggered_by_scheduler:
        recommendation = (
            "paper orders are armed: switch ALPHALAB_SCHEDULER_MODE=dry_run "
            "for stabilization unless this is intentional"
        )
    elif mode == "paper":
        recommendation = (
            "scheduler is paper but automation paper-trade guard is disarmed; "
            "switch ALPHALAB_SCHEDULER_MODE=dry_run for stabilization clarity"
        )
    else:
        recommendation = (
            "scheduler is dry_run but automation paper-trade guard is armed; "
            "unset ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES for stabilization"
        )
    return {
        "scheduler_mode": mode,
        "automation_paper_trading_armed": paper_guard_armed,
        "scheduler_paper_jobs_enabled": scheduler_paper_jobs_enabled,
        "paper_trades_can_be_triggered_by_scheduler": paper_trades_can_be_triggered_by_scheduler,
        "safe_stabilization_mode": safe_stabilization_mode,
        "recommendation": recommendation,
    }


def _dry_run() -> bool:
    """True unless the scheduler is explicitly in paper mode. Evaluated per run."""
    return automation_mode() != "paper"


def build_scheduler(service: AlphaLabService | None = None) -> BlockingScheduler:
    """Build (but do not start) the configured scheduler.

    Split for testability: the trade-placing jobs read _dry_run() at execution
    time, so the same scheduler honors whatever ALPHALAB_SCHEDULER_MODE was set
    when the process launched.
    """
    service = service or AlphaLabService()
    scheduler = BlockingScheduler(timezone="America/Los_Angeles")

    # --- Liveness heartbeat: prove the writer is alive AND on the shared DB --- #
    # Every 5 minutes the scheduler stamps app_config.scheduler_heartbeat (with its
    # resolved db_path) on the SAME database it writes ideas/trades to. The status
    # command and dashboard read this to confirm the always-on writer is healthy
    # and pointed at the same DB the API reads. Read/write of one row; harmless.
    scheduler.add_job(lambda: service.record_scheduler_heartbeat("scheduler"), "cron", minute="*/5", id="scheduler_heartbeat")

    # --- Always-safe jobs: state sync, inbox, read-only briefings ----------- #
    scheduler.add_job(lambda: service.sync_alpaca(dry_run=True), "cron", day_of_week="mon-fri", hour="6-13", minute="*/30")
    scheduler.add_job(_process_inbox, "cron", day_of_week="mon-fri", hour="5-14", minute="*/5")
    scheduler.add_job(lambda: service.generate_and_save_market_briefing(live_catalysts=True), "cron", day_of_week="mon-fri", hour=5, minute=45)
    scheduler.add_job(lambda: service.generate_and_save_market_briefing(live_catalysts=True), "cron", day_of_week="mon-fri", hour=9, minute=25)
    scheduler.add_job(lambda: service.generate_and_save_market_briefing(live_catalysts=True), "cron", day_of_week="mon-fri", hour=11, minute=55)
    # Daily signal validation is read-only: it scores stored ideas against
    # configured quote providers and never places or approves orders.
    scheduler.add_job(lambda: service.evaluate_pending_signals(limit=500), "cron", day_of_week="mon-fri", hour=13, minute=50)

    # --- Overnight Futures Pulse: nightly backtest fill (read-only) ---------- #
    # Early-AM weekday pull of the completed overnight session (6pm->9:30am ET) so
    # the SQLite backtest tables fill automatically before the cash open. Runs at
    # 6:05am PT (9:05am ET) — most of the overnight has landed and the throttled
    # 12-contract pull (~2.5 min) finishes well before the 6:30am PT / 9:30am ET
    # open. Read-only: it never places or approves a trade.
    scheduler.add_job(lambda: service.run_overnight_futures_pull(), "cron", day_of_week="mon-fri", hour=6, minute=5)
    # Read-only options-flow context preview for a tiny watchlist. It writes
    # scanner_runs accounting only; it never creates ideas/trades/orders.
    scheduler.add_job(lambda: service.run_options_flow_preview(), "cron", day_of_week="mon-fri", hour=6, minute=12)

    # --- Idea-generating + trade-placing jobs (dry_run controlled by mode) --- #
    scheduler.add_job(lambda: service.poll_live_catalysts(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour="5-14", minute="*/3")
    scheduler.add_job(lambda: service.import_daily_brief_and_test(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour=5, minute=50)
    scheduler.add_job(lambda: service.import_daily_brief_and_test(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour=6, minute=35)
    scheduler.add_job(lambda: service.import_daily_brief_and_test(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour=9, minute=30)
    scheduler.add_job(lambda: service.import_daily_brief_and_test(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour=12, minute=0)
    scheduler.add_job(lambda: service.import_daily_brief_and_test(dry_run=_dry_run()), "cron", day_of_week="mon-fri", hour=13, minute=35)

    # --- Weekend crypto-only jobs (equities are closed sat/sun) ------------- #
    # Crypto trades 24/7, so a weekend geopolitical/macro move (e.g. a shock that
    # hits BTC) should still get caught. poll_weekend_crypto is crypto-only and
    # dedupes, so it won't spam ideas or touch equities. Runs every 30m all
    # weekend; the dashboard's read-only briefing refresh runs alongside it.
    scheduler.add_job(lambda: service.poll_weekend_crypto(dry_run=_dry_run()), "cron", day_of_week="sat,sun", hour="0-23", minute="*/30")
    scheduler.add_job(lambda: service.generate_and_save_market_briefing(live_catalysts=True), "cron", day_of_week="sat,sun", hour="6,12,18", minute=0)
    scheduler.add_job(lambda: service.evaluate_pending_signals(limit=500), "cron", day_of_week="sat,sun", hour=18, minute=10)

    return scheduler


def start() -> None:
    # Load .env at the entry point (the scheduler launches independently of the
    # web server) so POLYGON_API_KEY / throttle settings are available before the
    # service and its providers are built. Done here, not at import time, so that
    # importing this module in tests never pulls real API keys into the process.
    load_dotenv()
    mode = automation_mode()
    banner = "PAPER ORDERS ENABLED" if mode == "paper" else "dry-run only — NO orders placed"
    service = AlphaLabService()
    # Stamp an immediate heartbeat at boot so the status command shows liveness
    # without waiting for the first 5-minute cron tick, and log the resolved DB
    # path so the launchd logs make the active database unambiguous.
    beat = service.record_scheduler_heartbeat("scheduler-start")
    print(f"[alphalab-scheduler] starting in mode={mode} ({banner}) db={beat['db_path']}", flush=True)
    build_scheduler(service=service).start()


def _process_inbox() -> None:
    from paper_trader.simulated_broker import SimulatedPaperBroker

    process_inbox(
        "paper_trader/inbox",
        "paper_trader/processed",
        "paper_trader/rejected",
        "alpha_lab/config.example.json",
        "alpha_lab/data/audit.jsonl",
        SimulatedPaperBroker(),
        dry_run=True,
    )


if __name__ == "__main__":
    start()
