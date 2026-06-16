import pytest

from paper_trader.alpaca_client import AlpacaCredentials, AlpacaClient, AlpacaSafetyError, assert_paper_base_url, redact_secrets


def test_accepts_paper_endpoint():
    assert_paper_base_url("https://paper-api.alpaca.markets")


def test_rejects_live_endpoint():
    with pytest.raises(AlpacaSafetyError):
        assert_paper_base_url("https://api.alpaca.markets")


def test_client_rejects_live_endpoint():
    with pytest.raises(AlpacaSafetyError):
        AlpacaClient(AlpacaCredentials("key", "secret", "https://api.alpaca.markets"))


def test_redacts_env_secrets(monkeypatch):
    monkeypatch.setenv("ALPACA_SECRET_KEY", "super-secret-value")
    assert "super-secret-value" not in redact_secrets("upstream echoed super-secret-value")
