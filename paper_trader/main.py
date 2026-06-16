from __future__ import annotations

import argparse
import json
from pathlib import Path

from .alpaca_client import AlpacaClient, AlpacaSafetyError, load_credentials_from_env
from .dashboard import build_report
from .inbox_processor import process_inbox
from .runner import process_file, process_signal_payload
from .scheduler import start_scheduler
from .simulated_broker import SimulatedPaperBroker


DEFAULT_CONFIG = "paper_trader/config.example.json"
DEFAULT_LOG = "paper_trader/logs/paper_trader.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper Trader Alpha for Alpaca paper trading")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to required risk config JSON")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Path to JSONL audit log")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest one signal file")
    ingest.add_argument("--file", required=True, help="JSON signal file")
    ingest.add_argument("--dry-run", action="store_true", help="Log accepted trades without placing paper orders")

    inbox = subparsers.add_parser("inbox", help="Consume JSON signal files once from inbox")
    inbox.add_argument("--inbox-dir", default="paper_trader/inbox")
    inbox.add_argument("--processed-dir", default="paper_trader/processed")
    inbox.add_argument("--rejected-dir", default="paper_trader/rejected")
    inbox.add_argument("--dry-run", action="store_true", help="Log accepted trades without placing paper orders")

    manual = subparsers.add_parser("manual", help="Submit one manual signal")
    manual.add_argument("--ticker", required=True)
    manual.add_argument("--bias", required=True, choices=["bullish", "bearish", "neutral"])
    manual.add_argument("--confidence", required=True, type=float)
    manual.add_argument("--timeframe", required=True, choices=["intraday", "swing"])
    manual.add_argument("--reason", required=True)
    manual.add_argument("--source", default="manual_cli")
    manual.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("dashboard", help="Print CLI dashboard")
    subparsers.add_parser("account", help="Fetch Alpaca paper account")
    subparsers.add_parser("positions", help="Fetch Alpaca paper positions")

    close = subparsers.add_parser("close", help="Close one Alpaca paper position")
    close.add_argument("--ticker", required=True)

    subparsers.add_parser("cancel-orders", help="Cancel all open Alpaca paper orders")

    serve = subparsers.add_parser("serve", help="Run FastAPI webhook server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8765, type=int)
    serve.add_argument("--dry-run", action="store_true")

    schedule = subparsers.add_parser("schedule", help="Run market-time scheduler")
    schedule.add_argument("--signals-dir", default="paper_trader/sample_signals")
    schedule.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.command == "serve":
        from .webhook import create_app

        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError("uvicorn is not installed. Run: pip install -r paper_trader/requirements.txt") from exc
        uvicorn.run(create_app(args.config, args.log, args.dry_run), host=args.host, port=args.port)
        return

    if args.command == "schedule":
        start_scheduler(args.config, args.log, args.signals_dir, args.dry_run)
        return

    broker = _build_broker(dry_run=getattr(args, "dry_run", False))

    if args.command == "ingest":
        print(json.dumps(process_file(args.file, args.config, args.log, broker, args.dry_run), indent=2))
    elif args.command == "inbox":
        print(
            json.dumps(
                process_inbox(
                    args.inbox_dir,
                    args.processed_dir,
                    args.rejected_dir,
                    args.config,
                    args.log,
                    broker,
                    args.dry_run,
                ),
                indent=2,
            )
        )
    elif args.command == "manual":
        payload = {
            "ticker": args.ticker,
            "bias": args.bias,
            "confidence": args.confidence,
            "timeframe": args.timeframe,
            "reason": args.reason,
            "source": args.source,
            "timestamp": _now_iso(),
        }
        print(json.dumps(process_signal_payload(payload, args.config, args.log, broker, args.dry_run), indent=2))
    elif args.command == "dashboard":
        print(build_report(broker.get_account(), broker.get_positions(), Path(args.log)))
    elif args.command == "account":
        print(json.dumps(broker.get_account(), indent=2))
    elif args.command == "positions":
        print(json.dumps(broker.get_positions(), indent=2))
    elif args.command == "close":
        print(json.dumps(broker.close_position(args.ticker), indent=2))
    elif args.command == "cancel-orders":
        print(json.dumps(broker.cancel_orders(), indent=2))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _build_broker(dry_run: bool):
    try:
        return AlpacaClient(load_credentials_from_env())
    except AlpacaSafetyError:
        if dry_run:
            return SimulatedPaperBroker()
        raise


if __name__ == "__main__":
    main()
