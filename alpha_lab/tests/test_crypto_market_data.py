from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from alpha_lab import market_data


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("BTC/USD", "BTC/USD"),
        ("BTCUSD", "BTC/USD"),
        ("btc/usd", "BTC/USD"),
        ("ethusd", "ETH/USD"),
        ("SOL-USD", "SOL/USD"),
        ("link", "LINK/USD"),
        ("HYPE/USD", "HYPE/USD"),
        ("dogeusd", "DOGE/USD"),
    ],
)
def test_normalize_crypto_symbol(raw: str, canonical: str):
    assert market_data.normalize_crypto_symbol(raw) == canonical


def test_fetch_json_uses_cached_payload_and_backs_off_on_429(monkeypatch):
    market_data._HTTP_CACHE.clear()
    market_data._HTTP_BACKOFF_UNTIL.clear()

    now = {"value": 0.0}
    calls = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return _Response()
        raise HTTPError(request.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr(market_data.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(market_data, "urlopen", fake_urlopen)

    url = "https://api.coingecko.com/api/v3/test"
    assert market_data._fetch_json(url) == {"ok": True}

    now["value"] = market_data._HTTP_CACHE_TTL_SECONDS + 1
    assert market_data._fetch_json(url) == {"ok": True}
    assert calls["count"] == 2

    now["value"] += 1
    assert market_data._fetch_json(url) == {"ok": True}
    assert calls["count"] == 2
