"""
alpha_lab/options_selector.py — read-only ATM option contract selection.

Phase-1 minimal slice: given an underlying + directional bias, pick a single
near-the-money option (call for bullish, put for bearish) at the nearest expiry
inside a DTE window, then apply liquidity guards (spread, and open-interest /
volume when the data feed provides them).

This module only issues GET requests to Alpaca's trading-contracts API
(paper host) and the options market-data API. It never places orders.
IV/greeks/open-interest are populated when Alpaca returns them and left as None
otherwise (the basic data feed omits them); callers store what is present.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Optional

from paper_trader.alpaca_client import load_credentials_from_env, redact_secrets

DATA_HOST = "https://data.alpaca.markets"


class OptionSelectionError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    creds = load_credentials_from_env()  # also enforces the paper base URL
    return {
        "APCA-API-KEY-ID": creds.api_key,
        "APCA-API-SECRET-KEY": creds.secret_key,
        "Accept": "application/json",
    }


def _trading_host() -> str:
    return load_credentials_from_env().base_url.rstrip("/")


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = redact_secrets(exc.read().decode("utf-8", errors="replace")[:300])
        raise OptionSelectionError(f"options data GET failed: {exc.code} {detail}") from exc
    return json.loads(body) if body else {}


def _underlying_price(underlying: str) -> Optional[float]:
    data = _get(f"{DATA_HOST}/v2/stocks/{underlying}/trades/latest")
    price = data.get("trade", {}).get("p")
    return float(price) if price is not None else None


def _latest_quote(contract_symbol: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"symbols": contract_symbol})
    data = _get(f"{DATA_HOST}/v1beta1/options/quotes/latest?{params}")
    return data.get("quotes", {}).get(contract_symbol, {}) or {}


def _snapshot(contract_symbol: str) -> dict[str, Any]:
    """Best-effort greeks/IV/OI; returns {} if the feed omits them."""
    params = urllib.parse.urlencode({"symbols": contract_symbol})
    try:
        data = _get(f"{DATA_HOST}/v1beta1/options/snapshots?{params}")
    except OptionSelectionError:
        return {}
    return data.get("snapshots", {}).get(contract_symbol, {}) or {}


def select_atm_contract(
    underlying: str,
    bias: str,
    *,
    min_dte: int = 7,
    max_dte: int = 14,
    max_spread_pct: float = 15.0,
    min_open_interest: int = 0,
    min_volume: int = 0,
) -> dict[str, Any]:
    """
    Return a structured selection dict for the chosen ATM contract, or raise
    OptionSelectionError with a human-readable reason if nothing qualifies.

    The returned dict carries everything the logging layer needs:
      contract_symbol, underlying, option_type, strike, expiry, dte,
      underlying_price, bid, ask, mid, spread_pct, bid_size, ask_size,
      implied_volatility, delta, open_interest, volume, estimated_cost_usd.
    """
    underlying = underlying.strip().upper()
    option_type = {"bullish": "call", "bearish": "put"}.get(bias)
    if option_type is None:
        raise OptionSelectionError(f"bias '{bias}' is not directional; no option selected")

    price = _underlying_price(underlying)
    if not price:
        raise OptionSelectionError(f"no underlying price for {underlying}")

    today = datetime.now(timezone.utc).date()
    gte = (today.fromordinal(today.toordinal() + min_dte)).isoformat()
    lte = (today.fromordinal(today.toordinal() + max_dte)).isoformat()

    params = urllib.parse.urlencode(
        {
            "underlying_symbols": underlying,
            "type": option_type,
            "expiration_date_gte": gte,
            "expiration_date_lte": lte,
            "strike_price_gte": round(price * 0.95, 2),
            "strike_price_lte": round(price * 1.05, 2),
            "limit": 100,
        }
    )
    data = _get(f"{_trading_host()}/v2/options/contracts?{params}")
    contracts = data.get("option_contracts", []) or []
    if not contracts:
        raise OptionSelectionError(
            f"no {option_type} contracts for {underlying} within {min_dte}-{max_dte} DTE near ATM"
        )

    # Nearest expiry inside the window, then strike closest to spot.
    expiries = sorted({c["expiration_date"] for c in contracts})
    nearest_expiry = expiries[0]
    same_expiry = [c for c in contracts if c["expiration_date"] == nearest_expiry]
    same_expiry.sort(key=lambda c: abs(float(c["strike_price"]) - price))
    chosen = same_expiry[0]

    contract_symbol = chosen["symbol"]
    dte = (date.fromisoformat(nearest_expiry) - today).days

    quote = _latest_quote(contract_symbol)
    bid = _as_float(quote.get("bp"))
    ask = _as_float(quote.get("ap"))
    if not bid or not ask or ask <= 0:
        raise OptionSelectionError(f"no two-sided quote for {contract_symbol}")
    mid = round((bid + ask) / 2, 4)
    spread_pct = round((ask - bid) / mid * 100, 2) if mid else None

    if spread_pct is not None and spread_pct > max_spread_pct:
        raise OptionSelectionError(
            f"spread too wide on {contract_symbol}: {spread_pct}% > {max_spread_pct}% max"
        )

    # Liquidity guards only apply when the feed actually returns the figures.
    snap = _snapshot(contract_symbol)
    greeks = snap.get("greeks") or {}
    iv = _as_float(snap.get("impliedVolatility"))
    delta = _as_float(greeks.get("delta"))
    open_interest = _as_int(chosen.get("open_interest") or snap.get("openInterest"))
    volume = _as_int((snap.get("dailyBar") or {}).get("v"))

    if open_interest is not None and min_open_interest and open_interest < min_open_interest:
        raise OptionSelectionError(
            f"open interest too low on {contract_symbol}: {open_interest} < {min_open_interest}"
        )
    if volume is not None and min_volume and volume < min_volume:
        raise OptionSelectionError(
            f"volume too low on {contract_symbol}: {volume} < {min_volume}"
        )

    return {
        "contract_symbol": contract_symbol,
        "underlying": underlying,
        "option_type": option_type,
        "strike": float(chosen["strike_price"]),
        "expiry": nearest_expiry,
        "dte": dte,
        "underlying_price": round(price, 4),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": spread_pct,
        "bid_size": _as_int(quote.get("bs")),
        "ask_size": _as_int(quote.get("as")),
        "implied_volatility": iv,
        "delta": delta,
        "open_interest": open_interest,
        "volume": volume,
        "estimated_cost_usd": round(ask * 100, 2),  # 1 contract = 100 shares
    }


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
