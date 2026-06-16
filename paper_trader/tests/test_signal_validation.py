import pytest

from paper_trader.models import Signal, ValidationError


def valid_payload():
    return {
        "ticker": "nvda",
        "bias": "bullish",
        "confidence": 0.8,
        "timeframe": "intraday",
        "reason": "relative strength",
        "source": "market_scan_bot",
        "timestamp": "2026-06-04T13:00:00Z",
    }


def test_valid_signal_normalizes_ticker():
    signal = Signal.from_dict(valid_payload())
    assert signal.ticker == "NVDA"
    assert signal.confidence == 0.8


def test_rejects_invalid_confidence():
    payload = valid_payload()
    payload["confidence"] = 1.2
    with pytest.raises(ValidationError):
        Signal.from_dict(payload)


def test_rejects_missing_field():
    payload = valid_payload()
    del payload["ticker"]
    with pytest.raises(ValidationError):
        Signal.from_dict(payload)

