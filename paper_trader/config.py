from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import RiskConfig


class ConfigError(ValueError):
    pass


def load_config(path: str | Path, profile: str = "default") -> RiskConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config file is required and was not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    if profile == "crypto":
        data = {**data, **data.get("crypto_risk", {})}
    elif profile != "default":
        raise ConfigError("profile must be default or crypto")
    required = [
        "min_confidence",
        "max_position_size_usd",
        "max_equity_pct_per_trade",
        "max_trades_per_day",
        "max_open_positions",
        "approved_tickers",
        "stop_loss_pct",
        "take_profit_pct",
        "max_daily_drawdown_pct",
    ]
    missing = [field for field in required if field not in data]
    if missing:
        raise ConfigError(f"config missing required fields: {', '.join(missing)}")

    approved = {str(ticker).upper().strip() for ticker in data["approved_tickers"]}
    approved.discard("")
    if not approved:
        raise ConfigError("approved_tickers must contain at least one ticker")

    config = RiskConfig(
        min_confidence=_positive_float(data, "min_confidence"),
        max_position_size_usd=_positive_float(data, "max_position_size_usd"),
        max_equity_pct_per_trade=_positive_float(data, "max_equity_pct_per_trade"),
        max_trades_per_day=_positive_int(data, "max_trades_per_day"),
        max_open_positions=_positive_int(data, "max_open_positions"),
        approved_tickers=approved,
        stop_loss_pct=_positive_float(data, "stop_loss_pct"),
        take_profit_pct=_positive_float(data, "take_profit_pct"),
        max_daily_drawdown_pct=_positive_float(data, "max_daily_drawdown_pct"),
        allow_short=bool(data.get("allow_short", False)),
        use_bracket_orders=bool(data.get("use_bracket_orders", False)),
    )

    if config.min_confidence > 1:
        raise ConfigError("min_confidence must be between 0 and 1")
    if config.max_equity_pct_per_trade > 0.10:
        raise ConfigError("max_equity_pct_per_trade must be 0.10 or lower")
    if config.stop_loss_pct > 0.20:
        raise ConfigError("stop_loss_pct must be 0.20 or lower")
    if config.max_daily_drawdown_pct > 0.20:
        raise ConfigError("max_daily_drawdown_pct must be 0.20 or lower")

    return config


def _positive_float(data: dict[str, Any], field: str) -> float:
    try:
        value = float(data[field])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{field} must be greater than 0")
    return value


def _positive_int(data: dict[str, Any], field: str) -> int:
    try:
        value = int(data[field])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{field} must be greater than 0")
    return value
