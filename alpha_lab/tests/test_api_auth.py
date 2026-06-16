"""Tests for the opt-in API token gate on mutating endpoints.

Safety property: when ALPHALAB_API_TOKEN is set, no write/execution request
succeeds without the matching bearer token, while reads (and health) stay open
so the dashboard still renders. With the token unset, behavior is unchanged.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.service import AlphaLabService


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    lab = AlphaLabService(
        db_path=str(tmp_path / "auth.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    return TestClient(create_app(lab))


def _idea_payload() -> dict:
    return {
        "ticker": "NVDA", "bias": "bullish", "confidence": 0.8,
        "timeframe": "intraday", "thesis": "test thesis", "source": "test",
        "timestamp": "2026-06-14T13:00:00Z",
    }


def test_writes_open_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("ALPHALAB_API_TOKEN", raising=False)
    # No token configured -> mutating request goes through (current dev behavior).
    assert client.post("/api/ideas", json=_idea_payload()).status_code == 200


def test_reads_open_even_when_token_set(client, monkeypatch):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "s3cret")
    # GETs must NOT require the token, or the dashboard can't render over Tailscale.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ideas").status_code == 200


def test_write_rejected_without_token(client, monkeypatch):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "s3cret")
    assert client.post("/api/ideas", json=_idea_payload()).status_code == 401


def test_write_rejected_with_wrong_token(client, monkeypatch):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "s3cret")
    r = client.post("/api/ideas", json=_idea_payload(), headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_write_allowed_with_correct_token(client, monkeypatch):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "s3cret")
    r = client.post("/api/ideas", json=_idea_payload(), headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


def test_approval_endpoint_is_gated(client, monkeypatch):
    # The whole point: execution-bearing endpoints can't be hit token-less.
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "s3cret")
    assert client.post("/api/ideas/1/approve").status_code == 401
    assert client.post("/api/ideas/1/paper-trade").status_code == 401
