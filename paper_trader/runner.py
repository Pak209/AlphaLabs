from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .alpaca_client import AlpacaClient
from .audit_log import AuditLog
from .config import load_config
from .decision_engine import evaluate_signal, serialize_decision
from .models import Signal, ValidationError


def load_signals_from_file(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("signals"), list):
            return data["signals"]
        return [data]
    raise ValidationError("signal file must contain an object, a list, or { signals: [...] }")


def process_signal_payload(
    payload: dict[str, Any],
    config_path: str | Path,
    log_path: str | Path,
    broker: AlpacaClient,
    dry_run: bool,
) -> dict[str, Any]:
    audit_log = AuditLog(log_path)
    try:
        signal = Signal.from_dict(payload)
    except ValidationError as exc:
        audit_log.write("signal_invalid", {"payload": payload, "reason": str(exc)})
        return {"accepted": False, "action": "invalid", "reasons": [str(exc)]}

    audit_log.write("signal_received", {"signal": _signal_dict(signal)})
    config = load_config(config_path)
    decision = evaluate_signal(signal, config, broker, audit_log, dry_run=dry_run)
    decision_payload = serialize_decision(decision)
    audit_log.write("decision", decision_payload)

    if not decision.accepted:
        audit_log.write("trade_rejected", decision_payload)
        return decision_payload

    if dry_run:
        audit_log.write("dry_run_order", decision_payload)
        return decision_payload

    assert decision.order_payload is not None
    response = broker.place_order(decision.order_payload)
    audit_log.write("order_submitted", {"decision": decision_payload, "order_response": response})
    return {**decision_payload, "order_response": response}


def process_file(
    signal_path: str | Path,
    config_path: str | Path,
    log_path: str | Path,
    broker: AlpacaClient,
    dry_run: bool,
) -> list[dict[str, Any]]:
    results = []
    for payload in load_signals_from_file(signal_path):
        results.append(process_signal_payload(payload, config_path, log_path, broker, dry_run))
    return results


def _signal_dict(signal: Signal) -> dict[str, Any]:
    return {
        "ticker": signal.ticker,
        "bias": signal.bias,
        "confidence": signal.confidence,
        "timeframe": signal.timeframe,
        "reason": signal.reason,
        "source": signal.source,
        "timestamp": signal.timestamp.isoformat(),
    }

