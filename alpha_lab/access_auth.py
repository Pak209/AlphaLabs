"""
alpha_lab/access_auth.py — Cloudflare Access identity as a write-auth source.

Why this exists: the operator reaches the dashboard through Cloudflare Access
(a real per-user login), but the app separately demanded a shared bearer token
for writes — so approving from a new device meant pasting a secret first. That
token is also the *weaker* credential: shared, non-expiring, and parked in
localStorage. An Access JWT is per-user, short-lived, revocable, and carries
whatever MFA the Access policy enforces.

SECURITY — why we verify instead of trusting the header:
the app is also reachable on loopback/tailnet, where the edge is NOT in the
path. Anything that merely *checked for* `Cf-Access-Jwt-Assertion` would let
anyone on the tailnet forge a header and bypass auth entirely. So every token
is cryptographically verified (RS256 against Cloudflare's published keys) with
audience, issuer, and expiry checks. Only a token Cloudflare actually minted
for OUR application passes.

Fail-closed everywhere: unset config disables this path completely (pure
token behavior), and any fetch/parse/verify failure denies rather than allows.

Config (.env):
    ALPHALAB_ACCESS_TEAM=<team-name>        # e.g. the Zero Trust team slug
    ALPHALAB_ACCESS_AUD=<application-aud-tag>
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

ACCESS_HEADER = "Cf-Access-Jwt-Assertion"
_JWKS_TTL_SECONDS = 3600
_LEEWAY_SECONDS = 30
_jwks_cache: dict[str, Any] = {"fetched_at": 0.0, "keys": {}}


def access_team() -> str:
    return os.getenv("ALPHALAB_ACCESS_TEAM", "").strip()


def access_aud() -> str:
    return os.getenv("ALPHALAB_ACCESS_AUD", "").strip()


def access_enabled() -> bool:
    """Both values required — a half-configured Access path stays OFF."""
    return bool(access_team() and access_aud())


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _fetch_jwks(force: bool = False) -> dict[str, Any]:
    """Cloudflare's public signing keys, cached (they rotate, not per-request)."""
    now = time.time()
    if not force and _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    url = f"https://{access_team()}.cloudflareaccess.com/cdn-cgi/access/certs"
    request = urllib.request.Request(url, headers={"User-Agent": "AlphaLab/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    keys = {k["kid"]: k for k in payload.get("keys", []) if k.get("kid")}
    _jwks_cache.update({"fetched_at": now, "keys": keys})
    return keys


def _public_key(jwk: dict[str, Any]):
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    n = int.from_bytes(_b64url(jwk["n"]), "big")
    e = int.from_bytes(_b64url(jwk["e"]), "big")
    return RSAPublicNumbers(e, n).public_key()


def verify_access_token(token: str) -> Optional[dict[str, Any]]:
    """Return the verified claims, or None. Never raises.

    Checks, in order: structure -> known signing key (with one forced JWKS
    refresh on an unknown kid, for rotation) -> RS256 signature -> audience ->
    issuer -> expiry/not-before.
    """
    if not access_enabled() or not token or token.count(".") != 2:
        return None
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url(header_b64))
        if header.get("alg") != "RS256":          # no alg confusion, no "none"
            return None
        kid = header.get("kid")
        if not kid:
            return None

        keys = _fetch_jwks()
        jwk = keys.get(kid) or _fetch_jwks(force=True).get(kid)
        if not jwk:
            return None

        try:
            _public_key(jwk).verify(
                _b64url(signature_b64),
                f"{header_b64}.{payload_b64}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            return None

        claims = json.loads(_b64url(payload_b64))
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if access_aud() not in audiences:         # token for a DIFFERENT app
            return None
        if claims.get("iss") != f"https://{access_team()}.cloudflareaccess.com":
            return None
        now = time.time()
        if float(claims.get("exp", 0)) < now - _LEEWAY_SECONDS:
            return None
        if float(claims.get("nbf", 0)) > now + _LEEWAY_SECONDS:
            return None
        return claims
    except Exception as exc:                      # malformed input -> deny
        LOGGER.warning("Access token verification failed: %s", type(exc).__name__)
        return None


def identity_from_headers(headers: Any) -> Optional[str]:
    """Verified operator identity (email) from request headers, else None."""
    claims = verify_access_token((headers.get(ACCESS_HEADER) or "").strip())
    if not claims:
        return None
    return str(claims.get("email") or claims.get("sub") or "access-user")
