from __future__ import annotations

from pathlib import Path
from typing import Any

from .alpaca_client import AlpacaClient, AlpacaSafetyError, load_credentials_from_env
from .runner import process_signal_payload
from .simulated_broker import SimulatedPaperBroker


def create_app(config_path: str | Path, log_path: str | Path, dry_run: bool):
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:
        raise RuntimeError("FastAPI is not installed. Run: pip install -r paper_trader/requirements.txt") from exc

    app = FastAPI(title="Paper Trader Alpha", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "dry-run" if dry_run else "paper"}

    @app.post("/signals")
    def signals(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            broker = AlpacaClient(load_credentials_from_env())
        except AlpacaSafetyError:
            if not dry_run:
                raise
            broker = SimulatedPaperBroker()
        try:
            if isinstance(payload.get("signals"), list):
                results = [
                    process_signal_payload(signal, config_path, log_path, broker, dry_run)
                    for signal in payload["signals"]
                ]
            else:
                results = [process_signal_payload(payload, config_path, log_path, broker, dry_run)]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"results": results}

    return app
