from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .audit_log import AuditLog
from .models import Decision, RiskConfig, Signal


class BrokerState:
    def get_account(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_clock(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_latest_trade_price(self, symbol: str) -> float | None:
        raise NotImplementedError


def evaluate_signal(
    signal: Signal,
    config: RiskConfig,
    broker: BrokerState,
    audit_log: AuditLog,
    dry_run: bool = True,
    alpha: dict[str, Any] | None = None,
    option: dict[str, Any] | None = None,
) -> Decision:
    reasons: list[str] = []
    positions = broker.get_positions()
    account = broker.get_account()
    clock = broker.get_clock()

    if signal.confidence < config.min_confidence:
        reasons.append(f"confidence {signal.confidence:.2f} below threshold {config.min_confidence:.2f}")
    if signal.bias not in {"bullish", "bearish"}:
        reasons.append("bias is not actionable")
    # Buying a put is a long, defined-risk position (not a short sale), so the
    # short-selling guard only applies to equity/crypto bearish entries.
    if signal.bias == "bearish" and not config.allow_short and signal.asset_type != "option":
        reasons.append("bearish short entries are disabled by config")
    if signal.ticker not in config.approved_tickers:
        reasons.append("ticker is not in approved watchlist")
    if signal.asset_type != "crypto" and not bool(clock.get("is_open")):
        reasons.append("market is closed")
    if len(positions) >= config.max_open_positions:
        reasons.append("max open positions reached")
    if _has_position(positions, signal.ticker):
        reasons.append("duplicate position already open")
    if audit_log.count_today("order_submitted") >= config.max_trades_per_day:
        reasons.append("max trades per day reached")
    if _daily_drawdown_exceeded(account, config):
        reasons.append("max daily drawdown reached")

    if reasons:
        return Decision(False, "reject", reasons, signal, alpha=alpha)

    equity = float(account.get("equity", 0))
    max_by_equity = equity * config.max_equity_pct_per_trade
    notional = min(config.max_position_size_usd, max_by_equity)
    if notional <= 0:
        return Decision(False, "reject", ["paper account equity is unavailable"], signal, alpha=alpha)

    # Phase-1 options: buy exactly one ATM call (bullish) or put (bearish). The
    # contract was selected upstream and passed in via `option`; we only size to a
    # single contract and verify its cost fits the per-trade budget.
    if signal.asset_type == "option":
        if not option or not option.get("contract_symbol"):
            return Decision(False, "reject", ["option signal is missing a selected contract"], signal, alpha=alpha)
        est_cost = float(option.get("estimated_cost_usd") or 0)
        if est_cost <= 0:
            return Decision(False, "reject", ["option contract cost is unavailable"], signal, alpha=alpha)
        if est_cost > notional:
            return Decision(
                False,
                "reject",
                [f"option cost ${est_cost:.0f} exceeds per-trade budget ${notional:.0f}"],
                signal,
                alpha=alpha,
            )
        option_payload: dict[str, Any] = {
            "symbol": option["contract_symbol"],
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": 1,
        }
        if dry_run:
            return Decision(True, "dry_run", ["dry-run accepted; no option order placed"], signal, est_cost, 1, option_payload, alpha=alpha)
        return Decision(True, "submit_order", ["accepted for Alpaca paper option order"], signal, est_cost, 1, option_payload, alpha=alpha)

    side = "buy" if signal.bias == "bullish" else "sell"
    # Alpaca rejects "day" for crypto (422 invalid crypto time_in_force); crypto requires "gtc".
    if signal.asset_type == "crypto":
        time_in_force = "gtc"
    else:
        time_in_force = "day" if signal.timeframe == "intraday" else "gtc"
    order_payload: dict[str, Any] = {
        "symbol": signal.ticker,
        "side": side,
        "type": "market",
        "time_in_force": time_in_force,
    }

    price = broker.get_latest_trade_price(signal.ticker)
    qty = None
    if side == "sell":
        if price is None or price <= 0:
            return Decision(False, "reject", ["latest price is required for paper short sizing"], signal, alpha=alpha)
        qty = round(notional / price, 4)
        order_payload["qty"] = qty
    else:
        order_payload["notional"] = round(notional, 2)

    if config.use_bracket_orders and price and price > 0:
        order_payload["order_class"] = "bracket"
        order_payload["stop_loss"] = {"stop_price": round(price * (1 - config.stop_loss_pct), 2)}
        order_payload["take_profit"] = {"limit_price": round(price * (1 + config.take_profit_pct), 2)}

    if dry_run:
        return Decision(True, "dry_run", ["dry-run accepted; no order placed"], signal, notional, qty, order_payload, alpha=alpha)
    return Decision(True, "submit_order", ["accepted for Alpaca paper order"], signal, notional, qty, order_payload, alpha=alpha)


def _has_position(positions: list[dict[str, Any]], ticker: str) -> bool:
    return any(str(position.get("symbol", "")).upper() == ticker for position in positions)


def _daily_drawdown_exceeded(account: dict[str, Any], config: RiskConfig) -> bool:
    equity = float(account.get("equity", 0) or 0)
    last_equity = float(account.get("last_equity", 0) or 0)
    if equity <= 0 or last_equity <= 0:
        return False
    return (last_equity - equity) / last_equity >= config.max_daily_drawdown_pct


def serialize_decision(decision: Decision) -> dict[str, Any]:
    return {
        "accepted": decision.accepted,
        "action": decision.action,
        "reasons": decision.reasons,
        "ticker": decision.signal.ticker,
        "bias": decision.signal.bias,
        "confidence": decision.signal.confidence,
        "timeframe": decision.signal.timeframe,
        "asset_type": decision.signal.asset_type,
        "notional": decision.notional,
        "qty": decision.qty,
        "order_payload": decision.order_payload,
        "alpha": decision.alpha,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
