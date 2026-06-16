from __future__ import annotations

import re
from typing import Any

# OCC option symbol, e.g. AAPL260618C00292500 (root + YYMMDD + C/P + 8-digit strike).
_OCC_RE = re.compile(r"^[A-Z]+\d{6}[CP]\d{8}$")


def _is_option_symbol(symbol: str) -> bool:
    return bool(_OCC_RE.match(symbol.upper()))


class SimulatedPaperBroker:
    """Dry-run broker state for local testing without Alpaca credentials.

    Beyond simple state, it can simulate the full order lifecycle (immediate fill,
    position tracking, lookup, and close) so the options lifecycle can be exercised
    offline. ``price`` is the entry fill; ``close_price`` (defaults to ``price``)
    is the exit fill, letting tests produce a non-zero realized P/L.
    """

    def __init__(
        self,
        equity: float = 100000.0,
        market_open: bool | None = None,
        price: float = 100.0,
        close_price: float | None = None,
    ):
        self.equity = equity
        self.market_open = True if market_open is None else market_open
        self.market_open_explicit = market_open is not None
        self.price = price
        self.close_price = price if close_price is None else close_price
        self.orders: list[dict[str, Any]] = []
        self._orders_by_id: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def get_account(self) -> dict[str, Any]:
        return {
            "equity": str(self.equity),
            "cash": str(self.equity),
            "last_equity": str(self.equity),
            "paper_simulated": True,
        }

    def get_positions(self) -> list[dict[str, Any]]:
        return list(self._positions.values())

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        return self._positions.get(symbol.upper())

    def get_clock(self) -> dict[str, Any]:
        return {"is_open": self.market_open}

    def get_latest_trade_price(self, symbol: str) -> float:
        return self.price

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.orders.append(payload)
        self._seq += 1
        order_id = f"sim-order-{self._seq}"
        symbol = str(payload.get("symbol", "")).upper()
        qty = float(payload.get("qty") or 1)
        multiplier = 100 if _is_option_symbol(symbol) else 1
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": payload.get("side"),
            "qty": str(qty),
            "status": "filled",
            "filled_qty": str(qty),
            "filled_avg_price": str(self.price),
            "paper_simulated": True,
        }
        self._orders_by_id[order_id] = order
        self._positions[symbol] = {
            "symbol": symbol,
            "qty": str(qty),
            "avg_entry_price": str(self.price),
            "current_price": str(self.price),
            "market_value": str(self.price * qty * multiplier),
            "unrealized_pl": "0",
            "asset_class": "us_option" if multiplier == 100 else "us_equity",
            "_multiplier": multiplier,
        }
        return order

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._orders_by_id[order_id]

    def close_position(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        position = self._positions.pop(symbol, None)
        qty = float(position["qty"]) if position else 1.0
        self._seq += 1
        order_id = f"sim-close-{self._seq}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": "sell",
            "qty": str(qty),
            "status": "filled",
            "filled_qty": str(qty),
            "filled_avg_price": str(self.close_price),
            "paper_simulated": True,
        }
        self._orders_by_id[order_id] = order
        return order
