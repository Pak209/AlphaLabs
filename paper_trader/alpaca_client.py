from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


SECRET_ENV_NAMES = {
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "POLYGON_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ALPHALAB_API_TOKEN",
}


class AlpacaSafetyError(RuntimeError):
    pass


class AlpacaAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlpacaCredentials:
    api_key: str
    secret_key: str
    base_url: str


def load_credentials_from_env() -> AlpacaCredentials:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    base_url = os.getenv("ALPACA_PAPER_BASE_URL", "").strip()
    missing = [
        name
        for name, value in {
            "ALPACA_API_KEY": api_key,
            "ALPACA_SECRET_KEY": secret_key,
            "ALPACA_PAPER_BASE_URL": base_url,
        }.items()
        if not value
    ]
    if missing:
        raise AlpacaSafetyError(f"missing required env vars: {', '.join(missing)}")
    assert_paper_base_url(base_url)
    return AlpacaCredentials(api_key=api_key, secret_key=secret_key, base_url=base_url)


def redact_secrets(text: str) -> str:
    redacted = text
    for name in SECRET_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value and len(value) >= 4:
            redacted = redacted.replace(value, f"<redacted:{name}>")
    return redacted


def assert_paper_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    if parsed.scheme != "https" or host != "paper-api.alpaca.markets":
        raise AlpacaSafetyError(
            "ALPACA_PAPER_BASE_URL must be exactly https://paper-api.alpaca.markets for paper trading"
        )


class AlpacaClient:
    def __init__(self, credentials: AlpacaCredentials):
        assert_paper_base_url(credentials.base_url)
        self.credentials = credentials

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "/v2/account")

    def get_positions(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/positions")

    def get_clock(self) -> dict[str, Any]:
        return self._request("GET", "/v2/clock")

    def get_latest_trade_price(self, symbol: str) -> float | None:
        try:
            response = self._request("GET", f"/v2/stocks/{symbol}/trades/latest")
        except AlpacaAPIError:
            return None
        price = response.get("trade", {}).get("p")
        return float(price) if price is not None else None

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/orders/{order_id}")

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        try:
            return self._request("GET", f"/v2/positions/{symbol.upper()}")
        except AlpacaAPIError:
            return None

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.confirm_paper_account()
        return self._request("POST", "/v2/orders", payload)

    def close_position(self, symbol: str) -> dict[str, Any]:
        self.confirm_paper_account()
        return self._request("DELETE", f"/v2/positions/{symbol.upper()}")

    def cancel_orders(self) -> Any:
        self.confirm_paper_account()
        return self._request("DELETE", "/v2/orders")

    def confirm_paper_account(self) -> dict[str, Any]:
        assert_paper_base_url(self.credentials.base_url)
        account = self.get_account()
        if account.get("trading_blocked") or account.get("account_blocked"):
            raise AlpacaSafetyError("Alpaca account is blocked; refusing to trade")
        return account

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = urljoin(self.credentials.base_url.rstrip("/") + "/", path.lstrip("/"))
        headers = {
            "APCA-API-KEY-ID": self.credentials.api_key,
            "APCA-API-SECRET-KEY": self.credentials.secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AlpacaAPIError(redact_secrets(f"Alpaca {method} {path} failed: {exc.code} {detail}")) from exc
        return json.loads(body) if body else {}
