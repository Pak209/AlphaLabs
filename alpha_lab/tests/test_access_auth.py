"""Cloudflare Access identity as write-auth: the security properties.

The point of this suite is the NEGATIVE cases. A forged or mis-scoped token
must never authorize a write, because the app is reachable on loopback/tailnet
where Cloudflare is not in the request path.
"""
from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from alpha_lab import access_auth
from alpha_lab.api import create_app

TEAM = "testteam"
AUD = "a" * 64
KID = "test-kid-1"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def access_env(monkeypatch, signing_key):
    """Configure Access and serve a JWKS built from the local test key."""
    monkeypatch.setenv("ALPHALAB_ACCESS_TEAM", TEAM)
    monkeypatch.setenv("ALPHALAB_ACCESS_AUD", AUD)
    numbers = signing_key.public_key().public_numbers()
    jwk = {
        "kid": KID, "kty": "RSA", "alg": "RS256",
        "n": b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }
    access_auth._jwks_cache.update({"fetched_at": time.time(), "keys": {KID: jwk}})
    yield
    access_auth._jwks_cache.update({"fetched_at": 0.0, "keys": {}})


def make_token(signing_key, *, aud=AUD, iss=None, exp_delta=3600, kid=KID,
               alg="RS256", email="operator@example.com", sign=True):
    header = {"alg": alg, "kid": kid, "typ": "JWT"}
    claims = {
        "aud": [aud],
        "iss": iss if iss is not None else f"https://{TEAM}.cloudflareaccess.com",
        "exp": time.time() + exp_delta,
        "nbf": time.time() - 10,
        "email": email,
    }
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
    if sign:
        signature = signing_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    else:
        signature = b"not-a-real-signature"
    return f"{signing_input}.{b64url(signature)}"


# ─── verification unit tests ─────────────────────────────────────────────────

def test_valid_token_yields_identity(access_env, signing_key):
    claims = access_auth.verify_access_token(make_token(signing_key))
    assert claims and claims["email"] == "operator@example.com"


def test_forged_signature_is_rejected(access_env, signing_key):
    """The whole threat model: a header someone made up must not pass."""
    assert access_auth.verify_access_token(make_token(signing_key, sign=False)) is None


def test_token_signed_by_a_different_key_is_rejected(access_env):
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert access_auth.verify_access_token(make_token(attacker)) is None


def test_token_for_another_application_is_rejected(access_env, signing_key):
    """A valid Cloudflare token for a DIFFERENT app must not authorize us."""
    assert access_auth.verify_access_token(make_token(signing_key, aud="b" * 64)) is None


def test_wrong_issuer_is_rejected(access_env, signing_key):
    token = make_token(signing_key, iss="https://evil.cloudflareaccess.com")
    assert access_auth.verify_access_token(token) is None


def test_expired_token_is_rejected(access_env, signing_key):
    assert access_auth.verify_access_token(make_token(signing_key, exp_delta=-120)) is None


def test_alg_none_is_rejected(access_env, signing_key):
    """Classic JWT attack: swap the algorithm to bypass signature checking."""
    assert access_auth.verify_access_token(make_token(signing_key, alg="none", sign=False)) is None
    assert access_auth.verify_access_token(make_token(signing_key, alg="HS256")) is None


def test_unknown_kid_is_rejected_without_network(access_env, signing_key, monkeypatch):
    monkeypatch.setattr(access_auth, "_fetch_jwks", lambda force=False: {})
    assert access_auth.verify_access_token(make_token(signing_key, kid="other")) is None


def test_disabled_when_unconfigured(monkeypatch, signing_key):
    monkeypatch.delenv("ALPHALAB_ACCESS_TEAM", raising=False)
    monkeypatch.delenv("ALPHALAB_ACCESS_AUD", raising=False)
    assert access_auth.access_enabled() is False
    assert access_auth.verify_access_token(make_token(signing_key)) is None


def test_garbage_input_never_raises(access_env):
    for junk in ("", "not-a-token", "a.b", "a.b.c", "...", "x" * 500):
        assert access_auth.verify_access_token(junk) is None


# ─── middleware integration: the actual approval path ────────────────────────

def write_request(client, headers):
    """POST an unrouted path: the middleware runs BEFORE routing, so a 401
    means auth denied and a 404 means auth passed. Isolates the credential
    check from any business logic or database state."""
    return client.post("/api/__auth_probe__", headers=headers, json={})


def test_access_identity_authorizes_writes_without_the_token(
        access_env, signing_key, monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "shared-secret-token")
    client = TestClient(create_app())

    # no credential at all -> 401 (unchanged behavior)
    assert write_request(client, {}).status_code == 401

    # forged Access header -> still 401 (the tailnet-spoofing case)
    forged = {access_auth.ACCESS_HEADER: make_token(signing_key, sign=False)}
    assert write_request(client, forged).status_code == 401

    # verified Access identity -> passes the gate (404 = reached routing)
    good = {access_auth.ACCESS_HEADER: make_token(signing_key)}
    assert write_request(client, good).status_code == 404

    # the shared token still works (no regression for tailnet/CLI callers)
    assert write_request(
        client, {"Authorization": "Bearer shared-secret-token"}).status_code == 404


def test_reads_stay_open_and_token_only_mode_unchanged(monkeypatch):
    """With Access unconfigured, behavior is exactly as before."""
    monkeypatch.delenv("ALPHALAB_ACCESS_TEAM", raising=False)
    monkeypatch.delenv("ALPHALAB_ACCESS_AUD", raising=False)
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "shared-secret-token")
    client = TestClient(create_app())
    assert client.get("/api/dashboard").status_code == 200          # reads open
    assert write_request(client, {}).status_code == 401             # writes gated
