from __future__ import annotations

from alpha_lab import source_smoke_test


def test_alpaca_paper_probe_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_BASE_URL", raising=False)

    result = source_smoke_test.probe_alpaca_paper()

    assert result["status"] == "no_credentials"
    assert result["api_key_present"] is False
    assert result["secret_key_present"] is False
    assert "ALPACA_API_KEY" in result["action"]


def test_alpaca_paper_probe_checks_account_and_market_data(monkeypatch):
    calls: list[str] = []

    def fake_http_get_json(url: str, headers: dict[str, str] | None = None):
        calls.append(url)
        assert headers
        assert headers["APCA-API-KEY-ID"] == "paper-key"
        assert headers["APCA-API-SECRET-KEY"] == "paper-secret"
        if url.endswith("/v2/account"):
            return "success", {"trading_blocked": False, "account_blocked": False}, None
        return "success", {"quote": {"ap": 501.25}}, None

    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setattr(source_smoke_test, "_http_get_json", fake_http_get_json)

    result = source_smoke_test.probe_alpaca_paper()

    assert result["status"] == "success"
    assert result["account_status"] == "success"
    assert result["market_data_status"] == "success"
    assert result["market_data_has_quote"] is True
    assert calls == [
        "https://paper-api.alpaca.markets/v2/account",
        "https://data.alpaca.markets/v2/stocks/SPY/quotes/latest",
    ]


def test_alpaca_paper_probe_rejects_non_paper_base_url(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://api.alpaca.markets")

    result = source_smoke_test.probe_alpaca_paper()

    assert result["status"] == "invalid_paper_base_url"
    assert result["paper_base_url_valid"] is False
