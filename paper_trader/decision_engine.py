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


class GateTrace:
    """Telemetry-only recorder for every gate a candidate passes or fails.

    Each record captures the gate name, the exact value compared, the threshold
    it was compared against, and the human-readable reason. Purely observational:
    it never changes what evaluate_signal decides, and gates that do not apply
    to a signal (e.g. short-guards on a bullish idea) are not recorded, so
    per-gate aggregation denominators stay honest.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def check(
        self,
        gate: str,
        passed: bool,
        *,
        observed: Any = None,
        threshold: Any = None,
        comparator: str = "",
        fail_reason: str = "",
        stage: str = "risk_engine",
    ) -> bool:
        self.records.append(
            {
                "stage": stage,
                "gate": gate,
                "passed": bool(passed),
                "observed": observed,
                "threshold": threshold,
                "comparator": comparator,
                "detail": ("" if passed else fail_reason) or ("ok" if passed else ""),
            }
        )
        return passed

    @property
    def first_failed(self) -> str | None:
        for record in self.records:
            if not record["passed"]:
                return record["gate"]
        return None


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
    trace = GateTrace()
    orders_today = audit_log.count_today("order_submitted")
    # Broker/config state that fed the checks below — persisted with the trace
    # so every rejection can be replayed against the exact inputs it saw.
    equity_raw = float(account.get("equity", 0) or 0)
    last_equity_raw = float(account.get("last_equity", 0) or 0)
    gate_context: dict[str, Any] = {
        "open_positions": len(positions),
        "position_tickers": sorted({str(p.get("symbol", "")).upper() for p in positions if p.get("symbol")}),
        "has_position_in_ticker": _has_position(positions, signal.ticker),
        "orders_submitted_today": orders_today,
        "market_open": bool(clock.get("is_open")),
        "equity": equity_raw,
        "last_equity": last_equity_raw,
        "drawdown_pct": round((last_equity_raw - equity_raw) / last_equity_raw, 6) if equity_raw > 0 and last_equity_raw > 0 else None,
        "signal": {"ticker": signal.ticker, "bias": signal.bias, "confidence": signal.confidence,
                   "timeframe": signal.timeframe, "asset_type": signal.asset_type, "source": signal.source},
        "config": {
            "min_confidence": config.min_confidence,
            "max_open_positions": config.max_open_positions,
            "max_trades_per_day": config.max_trades_per_day,
            "max_daily_drawdown_pct": config.max_daily_drawdown_pct,
            "max_position_size_usd": config.max_position_size_usd,
            "max_equity_pct_per_trade": config.max_equity_pct_per_trade,
            "allow_short": config.allow_short,
            "approved_tickers_count": len(config.approved_tickers),
        },
    }

    def gate(gate_name: str, passed: bool, fail_reason: str, **kwargs: Any) -> None:
        if not trace.check(gate_name, passed, fail_reason=fail_reason, **kwargs):
            reasons.append(fail_reason)

    gate(
        "confidence",
        signal.confidence >= config.min_confidence,
        f"confidence {signal.confidence:.2f} below threshold {config.min_confidence:.2f}",
        observed=signal.confidence, threshold=config.min_confidence, comparator=">=",
    )
    gate(
        "bias_actionable",
        signal.bias in {"bullish", "bearish"},
        "bias is not actionable",
        observed=signal.bias, threshold="bullish|bearish", comparator="in",
    )
    # Buying a put is a long, defined-risk position (not a short sale), so the
    # short-selling guard only applies to equity/crypto bearish entries.
    if signal.bias == "bearish" and signal.asset_type != "option":
        gate(
            "short_allowed",
            config.allow_short,
            "bearish short entries are disabled by config",
            observed=config.allow_short, threshold=True, comparator="==",
        )
    # Alpaca does not allow shorting crypto (non-marginable, long-only), so a
    # bearish crypto entry can never execute. Reject it up front with an honest
    # reason instead of letting it fail later at short-sizing with a misleading
    # "latest price required" error.
    if signal.bias == "bearish":
        gate(
            "crypto_long_only",
            signal.asset_type != "crypto",
            "Alpaca does not support shorting crypto (crypto is long-only)",
            observed=signal.asset_type, threshold="crypto", comparator="!=",
        )
    gate(
        "watchlist",
        signal.ticker in config.approved_tickers,
        "ticker is not in approved watchlist",
        observed=signal.ticker, threshold=f"{len(config.approved_tickers)} approved tickers", comparator="in",
    )
    if signal.asset_type != "crypto":
        gate(
            "market_open",
            bool(clock.get("is_open")),
            "market is closed",
            observed=bool(clock.get("is_open")), threshold=True, comparator="==",
        )
    gate(
        "max_open_positions",
        len(positions) < config.max_open_positions,
        "max open positions reached",
        observed=len(positions), threshold=config.max_open_positions, comparator="<",
    )
    gate(
        "duplicate_position",
        not _has_position(positions, signal.ticker),
        "duplicate position already open",
        observed=signal.ticker, threshold="no open position in ticker", comparator="not in",
    )
    gate(
        "max_trades_per_day",
        orders_today < config.max_trades_per_day,
        "max trades per day reached",
        observed=orders_today, threshold=config.max_trades_per_day, comparator="<",
    )
    gate(
        "daily_drawdown",
        not _daily_drawdown_exceeded(account, config),
        "max daily drawdown reached",
        observed=gate_context["drawdown_pct"], threshold=config.max_daily_drawdown_pct, comparator="<",
    )

    if reasons:
        return Decision(False, "reject", reasons, signal, alpha=alpha,
                        gate_results=trace.records, gate_context=gate_context)

    equity = float(account.get("equity", 0))
    max_by_equity = equity * config.max_equity_pct_per_trade
    notional = min(config.max_position_size_usd, max_by_equity)
    if not trace.check(
        "equity_available", notional > 0,
        observed=notional, threshold=0, comparator=">", stage="sizing",
        fail_reason="paper account equity is unavailable",
    ):
        return Decision(False, "reject", ["paper account equity is unavailable"], signal, alpha=alpha,
                        gate_results=trace.records, gate_context=gate_context)

    # Phase-1 options: buy exactly one ATM call (bullish) or put (bearish). The
    # contract was selected upstream and passed in via `option`; we only size to a
    # single contract and verify its cost fits the per-trade budget.
    if signal.asset_type == "option":
        if not trace.check(
            "option_contract_selected", bool(option and option.get("contract_symbol")),
            observed=(option or {}).get("contract_symbol"), threshold="contract symbol present",
            comparator="present", stage="sizing",
            fail_reason="option signal is missing a selected contract",
        ):
            return Decision(False, "reject", ["option signal is missing a selected contract"], signal, alpha=alpha,
                            gate_results=trace.records, gate_context=gate_context)
        est_cost = float(option.get("estimated_cost_usd") or 0)
        if not trace.check(
            "option_cost_known", est_cost > 0,
            observed=est_cost, threshold=0, comparator=">", stage="sizing",
            fail_reason="option contract cost is unavailable",
        ):
            return Decision(False, "reject", ["option contract cost is unavailable"], signal, alpha=alpha,
                            gate_results=trace.records, gate_context=gate_context)
        if not trace.check(
            "option_cost_within_budget", est_cost <= notional,
            observed=est_cost, threshold=notional, comparator="<=", stage="sizing",
            fail_reason=f"option cost ${est_cost:.0f} exceeds per-trade budget ${notional:.0f}",
        ):
            return Decision(
                False,
                "reject",
                [f"option cost ${est_cost:.0f} exceeds per-trade budget ${notional:.0f}"],
                signal,
                alpha=alpha,
                gate_results=trace.records,
                gate_context=gate_context,
            )
        option_payload: dict[str, Any] = {
            "symbol": option["contract_symbol"],
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": 1,
        }
        if dry_run:
            return Decision(True, "dry_run", ["dry-run accepted; no option order placed"], signal, est_cost, 1, option_payload, alpha=alpha,
                            gate_results=trace.records, gate_context=gate_context)
        return Decision(True, "submit_order", ["accepted for Alpaca paper option order"], signal, est_cost, 1, option_payload, alpha=alpha,
                        gate_results=trace.records, gate_context=gate_context)

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
        if not trace.check(
            "short_sizing_price", price is not None and price > 0,
            observed=price, threshold=0, comparator=">", stage="sizing",
            fail_reason="latest price is required for paper short sizing",
        ):
            return Decision(False, "reject", ["latest price is required for paper short sizing"], signal, alpha=alpha,
                            gate_results=trace.records, gate_context=gate_context)
        qty = round(notional / price, 4)
        order_payload["qty"] = qty
    else:
        order_payload["notional"] = round(notional, 2)

    if config.use_bracket_orders and price and price > 0:
        order_payload["order_class"] = "bracket"
        order_payload["stop_loss"] = {"stop_price": round(price * (1 - config.stop_loss_pct), 2)}
        order_payload["take_profit"] = {"limit_price": round(price * (1 + config.take_profit_pct), 2)}

    if dry_run:
        return Decision(True, "dry_run", ["dry-run accepted; no order placed"], signal, notional, qty, order_payload, alpha=alpha,
                        gate_results=trace.records, gate_context=gate_context)
    return Decision(True, "submit_order", ["accepted for Alpaca paper order"], signal, notional, qty, order_payload, alpha=alpha,
                    gate_results=trace.records, gate_context=gate_context)


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
        "gate_results": decision.gate_results,
        "gate_context": decision.gate_context,
        "first_failed_gate": next(
            (record["gate"] for record in decision.gate_results or [] if not record.get("passed")), None
        ),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
