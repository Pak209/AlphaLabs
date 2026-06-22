"""
alpha_lab/notifications.py — alerts, routing rules, and delivery channels.

This module turns AlphaLab events into operator alerts and decides *which*
channels (PWA Web Push, Twilio SMS) each alert should reach, then delivers them.

Design goals (safety first):
  * Nothing leaves the box by default. Push and SMS are both opt-in via the
    notification_preferences row AND gated again at delivery time by env config.
  * Dry-run by default. With ALERT_DELIVERY_DRY_RUN unset/true, deliveries are
    LOGGED to the notification_audit table but never actually sent. Flip to false
    only once channels are configured and you want real sends.
  * No secrets in bodies. Every alert body is passed through ``sanitize_text``
    which redacts long digit runs (account numbers) and key-like tokens.
  * Full audit. Every delivery attempt — including dry-run no-sends — writes a
    notification_audit row, so there is always a record of what was/would be sent.

The routing decision (`route_alert`) is a pure function of (level, preferences,
clock) so it can be unit-tested without a database or network.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time as dt_time
from typing import Any, Optional

from .database import connect, init_db, resolve_db_path

# Ordered alert levels, lowest -> highest severity. The numeric order drives the
# ">= min level" comparisons for both push and SMS routing.
ALERT_LEVELS = ["INFO", "WATCH", "URGENT_IDEA", "APPROVAL_REQUIRED", "RISK_KILL"]
LEVEL_ORDER = {name: index for index, name in enumerate(ALERT_LEVELS)}

# Levels that ALWAYS pierce quiet hours — these are actionable/critical and a
# user who set quiet hours still needs them (a trade needs sign-off; risk tripped).
QUIET_HOURS_BYPASS_LEVELS = {"APPROVAL_REQUIRED", "RISK_KILL"}

# Safe production PWA push policy. Real pushes are reserved for important,
# actionable alerts — URGENT_IDEA and above (URGENT_IDEA, APPROVAL_REQUIRED,
# RISK_KILL). INFO and WATCH never push by default, so the phone is not spammed.
# This is the floor used as the routing default; the operator can raise it per
# preferences but the system fails safe to this level when none is stored.
PRODUCTION_PUSH_MIN_LEVEL = "URGENT_IDEA"
PUSH_ELIGIBLE_LEVELS = frozenset(
    name for name in ALERT_LEVELS if LEVEL_ORDER[name] >= LEVEL_ORDER[PRODUCTION_PUSH_MIN_LEVEL]
)

# Env values that read as "off"/false for boolean flags.
FALSE_ENV_VALUES = {"", "0", "false", "no", "off"}

# Hex alphabet used to detect a legacy hex-encoded VAPID public key.
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

ALERT_STATUSES = {"unread", "read", "dismissed", "actioned"}

# Channel identifiers used in channels_sent / notification_audit.
CHANNEL_PUSH = "pwa_push"
CHANNEL_SMS = "sms"


def normalize_level(level: Any) -> str:
    """Coerce arbitrary input to a known level, defaulting to INFO."""
    candidate = str(level or "").strip().upper()
    return candidate if candidate in LEVEL_ORDER else "INFO"


def level_at_least(level: str, threshold: str) -> bool:
    """True when ``level`` is at or above ``threshold`` in the severity order."""
    return LEVEL_ORDER[normalize_level(level)] >= LEVEL_ORDER[normalize_level(threshold)]


def _parse_clock(value: Any) -> Optional[dt_time]:
    """Parse an 'HH:MM' (or 'HH:MM:SS') quiet-hours bound into a time, else None."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def in_quiet_hours(now: datetime, start: Any, end: Any) -> bool:
    """Is ``now`` inside the [start, end) quiet window?

    Supports windows that wrap past midnight (e.g. 22:00 -> 07:00). If either
    bound is missing/unparseable, quiet hours are treated as disabled.
    """
    start_t = _parse_clock(start)
    end_t = _parse_clock(end)
    if start_t is None or end_t is None or start_t == end_t:
        return False
    current = now.time()
    if start_t < end_t:
        return start_t <= current < end_t
    # Wrap-around window (overnight): inside if after start OR before end.
    return current >= start_t or current < end_t


# A conservative redactor for anything that smells like an account number or
# credential. We never want those in a push/SMS body or stored alert.
_DIGIT_RUN = re.compile(r"\d{7,}")
_KEY_LIKE = re.compile(r"\b(?:sk|pk|rk|whsec|AC|SK|AKIA)[-_A-Za-z0-9]{12,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")


def sanitize_text(value: Any, *, max_length: int = 600) -> str:
    """Redact secret-like substrings and cap length.

    Long digit runs (>=7) collapse to a masked tail (e.g. ``****6789``) so an
    account/card number can never ride along in an alert. Key-like tokens and
    bearer values are fully redacted. Defense in depth — callers should still
    avoid putting secrets in alerts in the first place.
    """
    text = str(value or "")
    text = _KEY_LIKE.sub("[redacted]", text)
    text = _BEARER.sub("bearer [redacted]", text)
    text = _DIGIT_RUN.sub(lambda m: "****" + m.group(0)[-4:], text)
    text = text.strip()
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def route_alert(level: Any, prefs: dict[str, Any], now: Optional[datetime] = None) -> dict[str, Any]:
    """Pure routing decision: which channels should fire for this alert.

    Inputs are the alert ``level`` and the operator's ``prefs`` dict; ``now`` is
    the local time used for quiet-hours evaluation (defaults to ``datetime.now()``).
    Returns a dict with boolean ``push``/``sms`` plus a ``reasons`` map explaining
    each decision (handy for the test-mode output and debugging). This function
    knows nothing about provider configuration or dry-run — those are applied by
    the dispatcher at send time.
    """
    now = now or datetime.now()
    norm_level = normalize_level(level)
    reasons: dict[str, str] = {}

    quiet = in_quiet_hours(now, prefs.get("quiet_hours_start"), prefs.get("quiet_hours_end"))
    bypass = norm_level in QUIET_HOURS_BYPASS_LEVELS
    quiet_blocks = quiet and not bypass

    push_enabled = bool(prefs.get("pwa_push_enabled"))
    push_min = normalize_level(prefs.get("push_min_level") or PRODUCTION_PUSH_MIN_LEVEL)
    push = push_enabled and level_at_least(norm_level, push_min)
    if not push_enabled:
        reasons["push"] = "push disabled in preferences"
    elif not level_at_least(norm_level, push_min):
        reasons["push"] = f"level {norm_level} below push_min_level {push_min}"
    elif quiet_blocks:
        push = False
        reasons["push"] = "suppressed by quiet hours"
    else:
        reasons["push"] = "eligible"

    sms_enabled = bool(prefs.get("sms_enabled"))
    sms_number = str(prefs.get("sms_phone_number") or "").strip()
    sms_min = normalize_level(prefs.get("sms_min_level") or "APPROVAL_REQUIRED")
    sms = sms_enabled and bool(sms_number) and level_at_least(norm_level, sms_min)
    if not sms_enabled:
        reasons["sms"] = "sms disabled in preferences"
    elif not sms_number:
        reasons["sms"] = "no sms_phone_number configured"
    elif not level_at_least(norm_level, sms_min):
        reasons["sms"] = f"level {norm_level} below sms_min_level {sms_min}"
    elif quiet_blocks:
        sms = False
        reasons["sms"] = "suppressed by quiet hours"
    else:
        reasons["sms"] = "eligible"

    return {
        "level": norm_level,
        "push": push,
        "sms": sms,
        "quiet_hours": quiet,
        "quiet_hours_bypassed": quiet and bypass,
        "reasons": reasons,
    }


def delivery_is_dry_run() -> bool:
    """True (the safe default) unless ALERT_DELIVERY_DRY_RUN is explicitly false.

    Dry-run logs every would-be delivery to the audit table but sends nothing.
    """
    raw = os.getenv("ALERT_DELIVERY_DRY_RUN")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def sms_globally_enabled() -> bool:
    """SMS sending requires an explicit env opt-in AND a configured Twilio client.

    This is independent of per-alert preferences — it is the box-level master
    switch that keeps SMS off until the operator has set credentials and flipped
    ALERT_SMS_ENABLED=true.
    """
    return os.getenv("ALERT_SMS_ENABLED", "").strip().lower() not in FALSE_ENV_VALUES


def live_execution_enabled() -> bool:
    """Reports the ALPHALAB_ALLOW_LIVE_EXECUTION env flag — AUDIT METADATA ONLY.

    IMPORTANT: this flag does NOT gate trade execution. It is read solely to stamp
    ``live_mode`` on approval_decisions rows so the audit trail records the posture
    in effect at sign-off time. Live (non-paper) execution is not implemented and is
    blocked structurally at the broker layer: AlpacaClient requires the
    paper-api.alpaca.markets endpoint, so no order can reach a live account
    regardless of this flag. Do not treat this as an execution switch.
    """
    return os.getenv("ALPHALAB_ALLOW_LIVE_EXECUTION", "").strip().lower() not in FALSE_ENV_VALUES


class TwilioSMSClient:
    """Minimal, dependency-free Twilio Messages client (urllib + basic auth).

    Reads credentials from the environment; ``is_configured`` is false unless all
    of account SID, auth token, and from-number are present. The auth token is
    never logged or returned — only the resulting message SID / error class is.
    """

    API_ROOT = "https://api.twilio.com/2010-04-01/Accounts"

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    @classmethod
    def from_env(cls) -> "TwilioSMSClient":
        return cls(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
            from_number=os.getenv("TWILIO_FROM_NUMBER", "").strip(),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._from_number)

    def send(self, to_number: str, body: str) -> dict[str, Any]:
        """Send one SMS. Returns {ok, sid|error}. Never raises on network errors;
        never includes the auth token in the result."""
        if not self.is_configured:
            return {"ok": False, "error": "twilio_not_configured"}
        if not to_number:
            return {"ok": False, "error": "missing_to_number"}
        url = f"{self.API_ROOT}/{urllib.parse.quote(self._account_sid)}/Messages.json"
        form = urllib.parse.urlencode(
            {"From": self._from_number, "To": to_number, "Body": sanitize_text(body)}
        ).encode("utf-8")
        token = base64.b64encode(f"{self._account_sid}:{self._auth_token}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            url,
            data=form,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            return {"ok": True, "sid": payload.get("sid", "")}
        except urllib.error.HTTPError as exc:
            # Twilio returns a JSON error body; surface only its code/message, not
            # request details that might echo credentials.
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
                message = str(detail.get("message") or detail.get("code") or exc.code)
            except Exception:  # pragma: no cover - defensive
                message = f"http_{exc.code}"
            return {"ok": False, "error": sanitize_text(message, max_length=200)}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"ok": False, "error": sanitize_text(str(exc).splitlines()[0], max_length=200)}


def normalize_vapid_public_key(raw: str) -> str:
    """Return a VAPID public key as unpadded URL-safe base64, or "" if unset.

    The browser Push API requires ``applicationServerKey`` to be the raw,
    uncompressed P-256 public point (65 bytes, ``0x04`` prefix) encoded as
    URL-safe base64. Two stored forms are accepted and both are normalized:

      * Standard or URL-safe base64 — normalized to unpadded URL-safe.
      * Legacy hex (130 hex chars = 65 raw bytes) — converted to base64url.
        A hex key served verbatim is misread by the browser as base64 and
        rejected with "applicationServerKey must contain a valid P-256 public
        key"; converting it here is exactly what prevents that failure.

    This only ever touches the public key — the private key is never read here.
    """
    key = (raw or "").strip()
    if not key:
        return ""
    # Legacy hex form: an uncompressed P-256 point is exactly 65 bytes -> 130
    # hex chars. The length pins it unambiguously (a base64url 65-byte key is
    # 87/88 chars), so a real base64 key is never misclassified as hex.
    if len(key) == 130 and all(c in _HEX_DIGITS for c in key):
        try:
            data = bytes.fromhex(key)
        except ValueError:
            data = b""
        if len(data) == 65 and data[0] == 0x04:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
        # Not a valid P-256 point; fall through and serve normalized as-is.
    # Standard base64 -> URL-safe; drop padding (the browser re-pads itself).
    return key.replace("+", "-").replace("/", "_").rstrip("=")


def public_vapid_key() -> str:
    """Env-backed VAPID public key, normalized to base64url.

    Reads ``VAPID_PUBLIC_KEY`` only — never the private key — so it is safe to
    expose to the browser via the public-key API route.
    """
    return normalize_vapid_public_key(os.getenv("VAPID_PUBLIC_KEY", ""))


def normalize_vapid_private_key(raw: str) -> str:
    """Return a VAPID private key in a form py_vapid/pywebpush can parse, or "".

    py_vapid's ``from_string`` base64url-decodes the value and treats it as a raw
    32-octet private scalar only when the decoded length is exactly 32 (otherwise
    it tries DER). A key stored as **legacy 64-char hex** decodes to 48 bytes, so
    it falls through to DER parsing and raises ``ValueError`` — exactly the real
    send failure observed. Three stored forms are accepted:

      * PEM (``-----BEGIN``) — returned untouched; parsed directly by py_vapid.
      * Legacy hex (64 hex chars = 32 raw bytes) — converted to base64url so the
        raw-key path is taken.
      * Base64 / base64url (raw or DER) — normalized to unpadded URL-safe.

    This NEVER returns or logs the key elsewhere; the value flows only to the
    in-process pywebpush call. Callers must not print the result.
    """
    key = (raw or "").strip()
    if not key:
        return ""
    # PEM is parsed as-is (it has its own framing and internal newlines).
    if "-----BEGIN" in key:
        return key
    # Legacy raw hex: 32 octets == 64 hex chars. The length + hex alphabet pin it
    # unambiguously (a base64url 32-byte key is 43 chars), so a real base64 key is
    # never misclassified as hex.
    if len(key) == 64 and all(c in _HEX_DIGITS for c in key):
        try:
            data = bytes.fromhex(key)
        except ValueError:
            data = b""
        if len(data) == 32:
            return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
        # Not a 32-byte scalar; fall through and serve normalized as-is.
    # Standard base64 -> URL-safe; drop padding (py_vapid re-pads on decode).
    return key.replace("+", "-").replace("/", "_").rstrip("=")


# Strip endpoint URLs (which carry per-subscription push tokens) from any error
# text before it is stored/returned.
_URL_RE = re.compile(r"https?://\S+")


def _sanitize_push_error(message: Any) -> str:
    """Make a push exception safe to persist: drop endpoint URLs/tokens, redact
    secret-like substrings, and cap length. Never includes key material."""
    text = _URL_RE.sub("[endpoint]", str(message or ""))
    return sanitize_text(text, max_length=200)


class WebPushClient:
    """Web Push (VAPID) sender backed by the optional ``pywebpush`` package.

    Encrypted Web Push requires VAPID keys and the pywebpush/cryptography stack.
    When those are absent the client reports ``is_configured = False`` and the
    dispatcher records a 'skipped' audit row rather than crashing — the subscribe
    flow and dry-run logging still work without the library installed.
    """

    def __init__(self, public_key: str, private_key: str, subject: str):
        self._public_key = public_key
        # Normalize the private key (e.g. legacy 64-char hex -> base64url) so the
        # raw-key path py_vapid expects is taken; without this a hex key reaches
        # pywebpush in an unsupported format and the send fails with ValueError.
        self._private_key = normalize_vapid_private_key(private_key)
        self._subject = subject or "mailto:alerts@alphalab.local"
        try:  # Optional dependency; absence is a soft, expected condition.
            from pywebpush import webpush, WebPushException  # type: ignore

            self._webpush = webpush
            self._WebPushException = WebPushException
        except Exception:  # pragma: no cover - depends on environment
            self._webpush = None
            self._WebPushException = None

    @classmethod
    def from_env(cls) -> "WebPushClient":
        return cls(
            public_key=os.getenv("VAPID_PUBLIC_KEY", "").strip(),
            private_key=os.getenv("VAPID_PRIVATE_KEY", "").strip(),
            subject=os.getenv("VAPID_SUBJECT", "").strip(),
        )

    @property
    def library_available(self) -> bool:
        return self._webpush is not None

    @property
    def is_configured(self) -> bool:
        return bool(self._private_key and self._public_key and self.library_available)

    def send(self, subscription: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """Deliver one encrypted push. Returns {ok, error?}. Never raises."""
        if not self.library_available:
            return {"ok": False, "error": "pywebpush_not_installed"}
        if not self._private_key:
            return {"ok": False, "error": "vapid_keys_not_configured"}
        info = {
            "endpoint": subscription.get("endpoint"),
            "keys": {"p256dh": subscription.get("p256dh"), "auth": subscription.get("auth")},
        }
        try:
            self._webpush(
                subscription_info=info,
                data=json.dumps(payload),
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},
                timeout=12,
            )
            return {"ok": True}
        except Exception as exc:  # pragma: no cover - network/library dependent
            name = type(exc).__name__
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Capture the first line of the message, scrubbed of endpoint URLs (which
            # carry per-subscription tokens) and any secret-like substrings, so the
            # audit row is diagnosable without leaking the key or subscription.
            first_line = str(exc).splitlines()[0] if str(exc) else ""
            detail = _sanitize_push_error(f"{name}: {first_line}" if first_line else name)
            return {"ok": False, "error": name, "detail": detail, "status_code": status}


class NotificationCenter:
    """Service-layer entry point for alerts, preferences, subscriptions, delivery.

    Mirrors the AlphaLabService pattern: resolve one DB path, open a fresh
    connection per operation. Channel clients default to env-configured instances
    but can be injected (tests pass fakes).
    """

    def __init__(
        self,
        db_path: str | None = None,
        sms_client: TwilioSMSClient | None = None,
        push_client: WebPushClient | None = None,
    ):
        self.db_path = resolve_db_path(db_path)
        init_db(self.db_path)
        self._sms_client = sms_client
        self._push_client = push_client

    # -- channel clients (lazily built from env if not injected) --------------- #
    @property
    def sms_client(self) -> TwilioSMSClient:
        return self._sms_client or TwilioSMSClient.from_env()

    @property
    def push_client(self) -> WebPushClient:
        return self._push_client or WebPushClient.from_env()

    # -- preferences ----------------------------------------------------------- #
    def get_preferences(self) -> dict[str, Any]:
        # Masked for the client: the full SMS number never leaves the server.
        with connect(self.db_path) as conn:
            return _mask_preferences(_read_preferences(conn))

    def update_preferences(self, updates: dict[str, Any]) -> dict[str, Any]:
        # Strict validators: a malformed value RAISES ValueError (surfaced as a 400)
        # rather than being silently coerced into an "enabled" state. Unknown keys in
        # the payload are ignored — only this allow-list is ever written.
        allowed = {
            "pwa_push_enabled": _strict_bool,
            "push_min_level": _validate_level,
            "sms_enabled": _strict_bool,
            "sms_phone_number": _validate_phone,
            "sms_min_level": _validate_level,
            "quiet_hours_start": _validate_clock,
            "quiet_hours_end": _validate_clock,
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, coerce in allowed.items():
            if key in updates:
                sets.append(f"{key} = ?")
                values.append(coerce(updates[key]))
        with connect(self.db_path) as conn:
            if sets:
                values.append(1)
                conn.execute(
                    f"UPDATE notification_preferences SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
                conn.commit()
            return _mask_preferences(_read_preferences(conn))

    # -- push subscriptions ---------------------------------------------------- #
    def save_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(subscription.get("endpoint") or "").strip()
        keys = subscription.get("keys") or {}
        p256dh = str(subscription.get("p256dh") or keys.get("p256dh") or "").strip()
        auth = str(subscription.get("auth") or keys.get("auth") or "").strip()
        user_agent = sanitize_text(str(subscription.get("user_agent") or ""), max_length=200)
        if not (endpoint and p256dh and auth):
            raise ValueError("subscription requires endpoint, p256dh, and auth")
        # Push endpoints are always absolute https URLs issued by a browser push
        # service. Reject anything else and bound the field sizes so a malformed or
        # oversized payload can't be persisted.
        if not (endpoint.startswith("https://") and len(endpoint) <= 1024):
            raise ValueError("subscription endpoint must be an https URL under 1024 chars")
        if len(p256dh) > 256 or len(auth) > 256:
            raise ValueError("subscription keys are malformed (too long)")
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                  p256dh = excluded.p256dh,
                  auth = excluded.auth,
                  user_agent = excluded.user_agent,
                  last_used_at = CURRENT_TIMESTAMP
                """,
                (endpoint, p256dh, auth, user_agent),
            )
            conn.commit()
        return {"ok": True, "endpoint": endpoint}

    def remove_subscription(self, endpoint: str) -> dict[str, Any]:
        endpoint = str(endpoint or "").strip()
        with connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
            conn.commit()
        return {"ok": True, "removed": int(cur.rowcount or 0)}

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, endpoint, p256dh, auth, user_agent, created_at, last_used_at FROM push_subscriptions ORDER BY id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # -- alerts ---------------------------------------------------------------- #
    def create_alert(
        self,
        level: str,
        title: str,
        body: str = "",
        source: str = "",
        related_trade_id: int | None = None,
        dedup_key: str | None = None,
    ) -> dict[str, Any]:
        norm_level = normalize_level(level)
        clean_title = sanitize_text(title, max_length=140)
        clean_body = sanitize_text(body)
        key = sanitize_text(str(dedup_key or ""), max_length=120) or None
        with connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts (level, title, body, source, related_trade_id, dedup_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (norm_level, clean_title, clean_body, sanitize_text(source, max_length=80), related_trade_id, key),
            )
            conn.commit()
            return _read_alert(conn, int(cur.lastrowid))

    def notify_event(
        self,
        level: str,
        title: str,
        body: str = "",
        source: str = "",
        *,
        dedup_key: str | None = None,
        related_trade_id: int | None = None,
    ) -> dict[str, Any]:
        """Idempotently create + dispatch an alert for a real system event.

        When ``dedup_key`` matches an existing alert that is still live (status
        unread/read), this is a no-op: it returns ``{"deduplicated": True, ...}``
        WITHOUT creating a second alert or re-dispatching push/SMS. This is what
        keeps repeated triggers (e.g. several paper-trade attempts on one
        idea awaiting sign-off) from spamming the operator. Notifications are
        informational only — this never approves, rejects, or places a trade.
        """
        key = str(dedup_key or "").strip()
        if not key:
            # No idempotency key — always a fresh create + dispatch.
            alert = self.create_alert(level, title, body, source, related_trade_id)
            summary = self.dispatch(alert["id"])
            summary["deduplicated"] = False
            return summary

        # Atomic dedupe. The partial UNIQUE index idx_alerts_dedup_live (on
        # dedup_key WHERE the alert is still live) makes this INSERT OR IGNORE the
        # single arbiter: only ONE of several concurrent callers actually inserts a
        # row (rowcount == 1) and proceeds to dispatch; every other call is ignored
        # by the constraint and returns a deduplicated no-op WITHOUT sending push/SMS.
        # This closes the check-then-insert race the prior non-unique index allowed.
        clean_key = sanitize_text(key, max_length=120) or None
        with connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO alerts (level, title, body, source, related_trade_id, dedup_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalize_level(level),
                    sanitize_text(title, max_length=140),
                    sanitize_text(body),
                    sanitize_text(source, max_length=80),
                    related_trade_id,
                    clean_key,
                ),
            )
            conn.commit()
            won_insert = cur.rowcount == 1
            new_id = int(cur.lastrowid) if won_insert else None
            if not won_insert:
                row = conn.execute(
                    "SELECT * FROM alerts WHERE dedup_key = ? AND status IN ('unread', 'read') ORDER BY id DESC LIMIT 1",
                    (clean_key,),
                ).fetchone()
        if not won_insert:
            existing = _hydrate_alert(dict(row)) if row is not None else None
            return {"deduplicated": True, "dispatched": False, "alert": existing}
        summary = self.dispatch(new_id)
        summary["deduplicated"] = False
        return summary

    def list_alerts(self, limit: int = 100, status: str | None = None) -> dict[str, Any]:
        """Return ``{"alerts": [...], "unread": int}`` newest-first."""
        limit = clamp_limit(limit)
        if status is not None:
            status = str(status).strip().lower()
            if status not in ALERT_STATUSES:
                raise ValueError(f"status must be one of {sorted(ALERT_STATUSES)}")
        with connect(self.db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE status = ? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            unread = int(conn.execute("SELECT COUNT(*) FROM alerts WHERE status = 'unread'").fetchone()[0])
        items = [_hydrate_alert(dict(row)) for row in rows]
        return {"alerts": items, "unread": unread}

    def get_alert(self, alert_id: int) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return _read_alert(conn, alert_id)

    def set_alert_status(self, alert_id: int, status: str) -> dict[str, Any]:
        status = str(status or "").strip().lower()
        if status not in ALERT_STATUSES:
            raise ValueError(f"status must be one of {sorted(ALERT_STATUSES)}")
        with connect(self.db_path) as conn:
            conn.execute("UPDATE alerts SET status = ? WHERE id = ?", (status, alert_id))
            conn.commit()
            return _read_alert(conn, alert_id)

    # -- delivery -------------------------------------------------------------- #
    def dispatch(self, alert_id: int, *, force_dry_run: bool | None = None) -> dict[str, Any]:
        """Route the alert and deliver it over each eligible channel.

        Records a notification_audit row for every channel attempt (including
        dry-run no-sends), updates the alert's channels_sent/error, and returns a
        summary with the routing decision and per-channel results.
        """
        dry_run = delivery_is_dry_run() if force_dry_run is None else bool(force_dry_run)
        with connect(self.db_path) as conn:
            alert = _read_alert(conn, alert_id)
            prefs = _read_preferences(conn)
        # Effective prefs: if no per-operator SMS number is stored, fall back to the
        # box-level ALERT_SMS_TO_NUMBER env recipient so routing (route_alert) and
        # delivery (_deliver_sms) agree on the same number. route_alert stays pure —
        # the fallback is injected here, in the dispatcher, not inside the rule.
        prefs = _apply_sms_fallback(prefs)
        decision = route_alert(alert["level"], prefs)
        channels_sent: list[str] = []
        results: dict[str, Any] = {}
        last_error: str | None = None

        if decision["push"]:
            result = self._deliver_push(alert, dry_run=dry_run)
            results[CHANNEL_PUSH] = result
            if result.get("delivered"):
                channels_sent.append(CHANNEL_PUSH)
            if result.get("error"):
                last_error = result["error"]

        if decision["sms"]:
            result = self._deliver_sms(alert, prefs, dry_run=dry_run)
            results[CHANNEL_SMS] = result
            if result.get("delivered"):
                channels_sent.append(CHANNEL_SMS)
            if result.get("error"):
                last_error = result["error"]

        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE alerts SET channels_sent = ?, error = ? WHERE id = ?",
                (json.dumps(channels_sent), last_error, alert_id),
            )
            conn.commit()
            alert = _read_alert(conn, alert_id)
        return {
            "alert": alert,
            "decision": decision,
            "dry_run": dry_run,
            "channels_sent": channels_sent,
            "results": results,
        }

    def create_and_dispatch(
        self,
        level: str,
        title: str,
        body: str = "",
        source: str = "",
        related_trade_id: int | None = None,
        force_dry_run: bool | None = None,
    ) -> dict[str, Any]:
        alert = self.create_alert(level, title, body, source, related_trade_id)
        return self.dispatch(alert["id"], force_dry_run=force_dry_run)

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = clamp_limit(limit)
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM notification_audit ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- internal channel delivery -------------------------------------------- #
    def _deliver_push(self, alert: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        subscriptions = self.list_subscriptions()
        # Safe routing metadata only — ids, level, and source let the service
        # worker/PWA deep-link to the triggering item. No secrets, prices, or
        # free-text beyond the already-sanitized title/body are included.
        payload = {
            "title": f"[{alert['level']}] {alert['title']}",
            "body": alert["body"],
            "alert_id": alert["id"],
            "related_trade_id": alert.get("related_trade_id"),
            "level": alert["level"],
            "source": alert.get("source") or "",
            "url": _click_url(alert),
        }
        if dry_run:
            self._audit(alert["id"], CHANNEL_PUSH, "dry_run", f"{len(subscriptions)} subscription(s)", dry_run=True)
            return {"delivered": False, "dry_run": True, "subscriptions": len(subscriptions)}
        if not subscriptions:
            self._audit(alert["id"], CHANNEL_PUSH, "skipped", "no subscriptions", dry_run=False)
            return {"delivered": False, "error": "no_subscriptions"}
        client = self.push_client
        if not client.is_configured:
            detail = "pywebpush missing" if not client.library_available else "VAPID keys not configured"
            self._audit(alert["id"], CHANNEL_PUSH, "skipped", detail, dry_run=False)
            return {"delivered": False, "error": detail}
        sent = 0
        errors: list[str] = []
        for sub in subscriptions:
            result = client.send(sub, payload)
            if result.get("ok"):
                sent += 1
            else:
                # Prefer the sanitized first-line detail (no secrets/endpoints) for
                # diagnosis; fall back to the bare exception class name.
                errors.append(str(result.get("detail") or result.get("error")))
                # A 404/410 means the browser dropped the subscription; prune it.
                if result.get("status_code") in (404, 410):
                    self.remove_subscription(sub["endpoint"])
        status = "sent" if sent else "error"
        detail = f"sent={sent} errors={len(errors)}"
        if errors and not sent:
            detail = f"{detail}: {'; '.join(errors[:3])}"
        self._audit(alert["id"], CHANNEL_PUSH, status, detail, dry_run=False)
        return {"delivered": sent > 0, "sent": sent, "error": "; ".join(errors[:3]) if errors and not sent else None}

    def _deliver_sms(self, alert: dict[str, Any], prefs: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        # prefs already carries the validated ALERT_SMS_TO_NUMBER fallback (injected
        # by _apply_sms_fallback in dispatch), so a malformed env number never reaches
        # here — it was rejected upstream and SMS routing stayed ineligible.
        to_number = str(prefs.get("sms_phone_number") or "").strip()
        body = f"[{alert['level']}] {alert['title']} — {alert['body']}".strip(" —")
        if dry_run:
            self._audit(alert["id"], CHANNEL_SMS, "dry_run", "would send 1 sms", dry_run=True)
            return {"delivered": False, "dry_run": True}
        if not to_number:
            self._audit(alert["id"], CHANNEL_SMS, "skipped", "no sms recipient", dry_run=False)
            return {"delivered": False, "error": "no_sms_recipient"}
        if not sms_globally_enabled():
            self._audit(alert["id"], CHANNEL_SMS, "skipped", "ALERT_SMS_ENABLED not set", dry_run=False)
            return {"delivered": False, "error": "sms_globally_disabled"}
        client = self.sms_client
        if not client.is_configured:
            self._audit(alert["id"], CHANNEL_SMS, "skipped", "twilio not configured", dry_run=False)
            return {"delivered": False, "error": "twilio_not_configured"}
        result = client.send(to_number, body)
        if result.get("ok"):
            self._audit(alert["id"], CHANNEL_SMS, "sent", "ok", dry_run=False)
            return {"delivered": True, "sid": result.get("sid")}
        self._audit(alert["id"], CHANNEL_SMS, "error", str(result.get("error")), dry_run=False)
        return {"delivered": False, "error": str(result.get("error"))}

    def _audit(self, alert_id: int, channel: str, status: str, detail: str, *, dry_run: bool) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO notification_audit (alert_id, channel, status, detail, dry_run) VALUES (?, ?, ?, ?, ?)",
                (alert_id, channel, status, sanitize_text(detail, max_length=200), 1 if dry_run else 0),
            )
            conn.commit()


# --- module-level DB helpers (kept tiny; the class owns connection lifecycle) -- #
_TRUE_TOKENS = {"1", "true", "yes", "on"}
_PHONE_STRIP = re.compile(r"[\s\-().]")
_PHONE_VALID = re.compile(r"\+?\d{7,15}")


def clamp_limit(value: Any, default: int = 100, lo: int = 1, hi: int = 500) -> int:
    """Coerce a pagination limit into [lo, hi]; malformed input -> default."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _strict_bool(value: Any) -> int:
    """Parse a boolean strictly. Unrecognized values RAISE rather than defaulting
    to "on" — a malformed flag must never silently enable a channel."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        if value in (0, 1):
            return value
        raise ValueError(f"expected boolean, got {value!r}")
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return 1
        if token in FALSE_ENV_VALUES:
            return 0
    raise ValueError(f"expected boolean, got {value!r}")


def _validate_level(value: Any) -> str:
    """Return a known ALERT level or RAISE — unknown levels are rejected, not
    silently coerced to INFO (which would mask a client bug)."""
    text = str(value or "").strip().upper()
    if text not in LEVEL_ORDER:
        raise ValueError(f"level must be one of {ALERT_LEVELS}")
    return text


def _validate_phone(value: Any) -> str:
    """Normalize/validate an SMS number to digits with optional leading '+'.

    Empty clears the number. A non-empty but malformed value RAISES. Separators
    (spaces, dashes, parens) are stripped; 7–15 digits are required (E.164 range).
    """
    text = str(value or "").strip()
    if not text:
        return ""
    digits = _PHONE_STRIP.sub("", text)
    if not _PHONE_VALID.fullmatch(digits):
        raise ValueError("sms_phone_number must be 7-15 digits with an optional leading +")
    return digits


def _validate_clock(value: Any) -> Optional[str]:
    """Normalize an 'HH:MM' quiet-hours bound. Empty disables; a non-empty but
    unparseable value RAISES rather than silently disabling quiet hours."""
    text = str(value or "").strip()
    if not text:
        return None
    parsed = _parse_clock(text)
    if parsed is None:
        raise ValueError("quiet hours bound must be HH:MM (24-hour)")
    return parsed.strftime("%H:%M")


def _apply_sms_fallback(prefs: dict[str, Any]) -> dict[str, Any]:
    """Return prefs with the ALERT_SMS_TO_NUMBER env fallback filled in when no
    per-operator SMS number is stored. Pure w.r.t. the input dict (returns a copy).

    The env fallback runs through the SAME fail-closed validator as a stored number
    (``_validate_phone``): a malformed, non-empty value is NOT injected, so it can
    never make SMS routing eligible. The number itself is never logged.
    """
    if str(prefs.get("sms_phone_number") or "").strip():
        return prefs
    raw = os.getenv("ALERT_SMS_TO_NUMBER", "").strip()
    if not raw:
        return prefs
    try:
        fallback = _validate_phone(raw)
    except ValueError:
        # Fail closed: a malformed env recipient is dropped (SMS stays ineligible).
        # Log only that it was rejected — never the value.
        logging.getLogger(__name__).warning(
            "ALERT_SMS_TO_NUMBER is malformed; ignoring SMS env fallback"
        )
        return prefs
    if not fallback:
        return prefs
    merged = dict(prefs)
    merged["sms_phone_number"] = fallback
    return merged


def _mask_phone(number: Any) -> str:
    """Mask a phone number to its last 4 digits (e.g. ``***-***-1234``).

    Returns "" when there is no number. Used so API reads never expose the full
    stored SMS number to the frontend.
    """
    digits = re.sub(r"\D", "", str(number or ""))
    if not digits:
        return ""
    return f"***-***-{digits[-4:]}"


def _mask_preferences(prefs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of prefs safe to send to the client: the SMS number is masked
    to its last 4 digits and a ``sms_phone_configured`` boolean is added. The raw
    number stays server-side (delivery uses ``_read_preferences`` directly)."""
    masked = dict(prefs)
    raw = str(prefs.get("sms_phone_number") or "").strip()
    masked["sms_phone_configured"] = bool(raw)
    masked["sms_phone_number"] = _mask_phone(raw)
    return masked


def _read_preferences(conn) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM notification_preferences WHERE id = 1").fetchone()
    if row is None:
        conn.execute("INSERT OR IGNORE INTO notification_preferences (id) VALUES (1)")
        conn.commit()
        row = conn.execute("SELECT * FROM notification_preferences WHERE id = 1").fetchone()
    prefs = dict(row)
    prefs["pwa_push_enabled"] = bool(prefs.get("pwa_push_enabled"))
    prefs["sms_enabled"] = bool(prefs.get("sms_enabled"))
    return prefs


def _hydrate_alert(alert: dict[str, Any]) -> dict[str, Any]:
    try:
        alert["channels_sent"] = json.loads(alert.get("channels_sent") or "[]")
    except (TypeError, ValueError):
        alert["channels_sent"] = []
    return alert


def _read_alert(conn, alert_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise KeyError(f"alert not found: {alert_id}")
    return _hydrate_alert(dict(row))


def _click_url(alert: dict[str, Any]) -> str:
    """Where a notification click should land.

    Sign-off-class alerts (APPROVAL_REQUIRED / RISK_KILL) open the approval queue
    (``/#approvals``). They are intentionally NOT deep-linked to a specific card:
    the approval queue is keyed by ``idea_id`` (an idea awaiting sign-off, before
    any trade exists), whereas the only structured id an alert carries is
    ``related_trade_id`` — a ``trades`` foreign key that only exists *after*
    placement and is therefore never present on an approval-queue card. Emitting
    ``/#approvals/<trade_id>`` could never match a card, so the click lands on the
    queue itself. All other alerts open their own detail (``/#alerts/<id>``).
    Routes are in-app hash fragments only — no external URLs and no secrets.
    """
    if alert["level"] in ("APPROVAL_REQUIRED", "RISK_KILL"):
        return "/#approvals"
    return f"/#alerts/{alert['id']}"
