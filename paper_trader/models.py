from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


Bias = Literal["bullish", "bearish", "neutral"]
Timeframe = Literal["intraday", "swing"]
AssetType = Literal["equity", "option", "crypto"]


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Signal:
    ticker: str
    bias: Bias
    confidence: float
    timeframe: Timeframe
    reason: str
    source: str
    timestamp: datetime
    asset_type: AssetType = "equity"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Signal":
        required = ["ticker", "bias", "confidence", "timeframe", "reason", "source", "timestamp"]
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValidationError(f"missing required fields: {', '.join(missing)}")

        ticker = str(payload["ticker"]).strip().upper()
        if not ticker:
            raise ValidationError("ticker is required")

        bias = str(payload["bias"]).strip().lower()
        if bias not in {"bullish", "bearish", "neutral"}:
            raise ValidationError("bias must be bullish, bearish, or neutral")

        try:
            confidence = float(payload["confidence"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("confidence must be a number") from exc
        if confidence < 0 or confidence > 1:
            raise ValidationError("confidence must be between 0.0 and 1.0")

        timeframe = str(payload["timeframe"]).strip().lower()
        if timeframe not in {"intraday", "swing"}:
            raise ValidationError("timeframe must be intraday or swing")

        asset_type = str(payload.get("asset_type", _infer_asset_type(ticker))).strip().lower()
        if asset_type == "equities":
            asset_type = "equity"
        if asset_type == "options":
            asset_type = "option"
        if asset_type not in {"equity", "option", "crypto"}:
            raise ValidationError("asset_type must be equity, option, or crypto")
        if asset_type == "crypto":
            ticker = _canonical_crypto_ticker(ticker)

        reason = str(payload["reason"]).strip()
        source = str(payload["source"]).strip()
        if not reason:
            raise ValidationError("reason is required")
        if not source:
            raise ValidationError("source is required")

        timestamp_raw = str(payload["timestamp"]).strip()
        try:
            normalized = timestamp_raw.replace("Z", "+00:00")
            timestamp = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValidationError("timestamp must be an ISO date") from exc
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return cls(
            ticker=ticker,
            bias=bias,  # type: ignore[arg-type]
            confidence=confidence,
            timeframe=timeframe,  # type: ignore[arg-type]
            reason=reason,
            source=source,
            timestamp=timestamp,
            asset_type=asset_type,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class RiskConfig:
    min_confidence: float
    max_position_size_usd: float
    max_equity_pct_per_trade: float
    max_trades_per_day: int
    max_open_positions: int
    approved_tickers: set[str]
    stop_loss_pct: float
    take_profit_pct: float
    max_daily_drawdown_pct: float
    allow_short: bool = False
    use_bracket_orders: bool = False


def _infer_asset_type(ticker: str) -> str:
    normalized = ticker.upper()
    crypto_symbols = {"BTC", "BTC/USD", "BTCUSD", "ETH", "ETH/USD", "ETHUSD", "SOL", "SOL/USD", "SOLUSD", "LINK", "LINK/USD", "LINKUSD", "HYPE", "HYPE/USD", "HYPEUSD", "BNB", "BNB/USD", "BNBUSD", "DOGE", "DOGE/USD", "DOGEUSD"}
    if normalized in crypto_symbols or normalized.endswith("/USD") and normalized.split("/")[0] in crypto_symbols:
        return "crypto"
    return "equity"


def _canonical_crypto_ticker(ticker: str) -> str:
    normalized = str(ticker or "").strip().upper().replace("-", "/")
    if "/" not in normalized and normalized.endswith("USD"):
        normalized = f"{normalized[:-3]}/USD"
    if "/" not in normalized and normalized in {"BTC", "ETH", "SOL", "LINK", "HYPE", "BNB", "DOGE"}:
        normalized = f"{normalized}/USD"
    return normalized


@dataclass(frozen=True)
class Decision:
    accepted: bool
    action: str
    reasons: list[str]
    signal: Signal
    notional: float = 0.0
    qty: float | None = None
    order_payload: dict[str, Any] | None = None
    # MVP Analyst Brain score (a plain dict so paper_trader stays decoupled from
    # alpha_lab). Populated by the caller; rides through serialize_decision.
    alpha: dict[str, Any] | None = None
    # Telemetry only (never consulted for the decision itself): one record per
    # gate evaluated — gate name, observed value, threshold, comparator, pass/
    # fail, and the exact rejection reason — plus the broker/config state the
    # gates read. Rides through serialize_decision into decision_logs and the
    # execution audit so every candidate's path is replayable.
    gate_results: list[dict[str, Any]] | None = None
    gate_context: dict[str, Any] | None = None
