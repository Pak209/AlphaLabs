from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runner import process_file


PROCESSING_DIR = ".processing"


def process_inbox(
    inbox_dir: str | Path,
    processed_dir: str | Path,
    rejected_dir: str | Path,
    config_path: str | Path,
    log_path: str | Path,
    broker: Any,
    dry_run: bool,
) -> list[dict[str, Any]]:
    inbox = Path(inbox_dir)
    processing = inbox / PROCESSING_DIR
    processed = Path(processed_dir)
    rejected = Path(rejected_dir)

    inbox.mkdir(parents=True, exist_ok=True)
    processing.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    rejected.mkdir(parents=True, exist_ok=True)

    outcomes = []
    for signal_file in sorted(inbox.glob("*.json")):
        claimed = _claim(signal_file, processing)
        if claimed is None:
            continue
        outcomes.append(_process_claimed_file(claimed, processed, rejected, config_path, log_path, broker, dry_run))
    return outcomes


def _claim(signal_file: Path, processing: Path) -> Path | None:
    claimed = processing / signal_file.name
    try:
        signal_file.rename(claimed)
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return claimed


def _process_claimed_file(
    claimed: Path,
    processed: Path,
    rejected: Path,
    config_path: str | Path,
    log_path: str | Path,
    broker: Any,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        results = process_file(claimed, config_path, log_path, broker, dry_run)
    except Exception as exc:
        result = {"file": str(claimed), "status": "rejected", "error": str(exc), "results": []}
        destination = _unique_destination(rejected, claimed.name)
        claimed.rename(destination)
        _write_result_sidecar(destination, result)
        return result

    status = "processed" if results and all(row.get("accepted") for row in results) else "rejected"
    destination_dir = processed if status == "processed" else rejected
    destination = _unique_destination(destination_dir, claimed.name)
    claimed.rename(destination)
    result = {"file": str(destination), "status": status, "results": results}
    _write_result_sidecar(destination, result)
    return result


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return directory / f"{candidate.stem}-{timestamp}{candidate.suffix}"


def _write_result_sidecar(signal_file: Path, result: dict[str, Any]) -> None:
    sidecar = signal_file.with_suffix(signal_file.suffix + ".result.json")
    sidecar.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")

