import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alpha_lab.api import create_app
from alpha_lab.database import connect, init_db
from alpha_lab.notifications import (
    NotificationCenter,
    WebPushClient,
    _apply_sms_fallback,
    _click_url,
    _sanitize_push_error,
    clamp_limit,
    in_quiet_hours,
    level_at_least,
    normalize_level,
    normalize_vapid_private_key,
    normalize_vapid_public_key,
    route_alert,
    sanitize_text,
)
from alpha_lab.repository import AlphaLabRepository
from alpha_lab.service import AlphaLabService


def base_prefs(**overrides):
    prefs = {
        "pwa_push_enabled": False,
        "push_min_level": "INFO",
        "sms_enabled": False,
        "sms_phone_number": "",
        "sms_min_level": "APPROVAL_REQUIRED",
        "quiet_hours_start": None,
        "quiet_hours_end": None,
    }
    prefs.update(overrides)
    return prefs


# ---- pure helpers -----------------------------------------------------------
def test_normalize_level_defaults_to_info():
    assert normalize_level("urgent_idea") == "URGENT_IDEA"
    assert normalize_level("nonsense") == "INFO"
    assert normalize_level(None) == "INFO"


# ---- VAPID public-key normalization (P-256 / base64url) ---------------------
import base64 as _base64


def _sample_p256_point() -> bytes:
    # A 65-byte uncompressed P-256 point: 0x04 prefix + 64 bytes (X||Y). The bytes
    # need not be a real curve point for normalization/encoding shape testing.
    return b"\x04" + bytes(range(64))


def test_vapid_hex_input_is_converted_to_base64url():
    point = _sample_p256_point()
    hex_key = point.hex()  # 130 chars, the legacy hex form
    assert len(hex_key) == 130
    out = normalize_vapid_public_key(hex_key)
    # Round-trips back to the same raw 65-byte point, and is URL-safe + unpadded.
    assert out == _base64.urlsafe_b64encode(point).decode().rstrip("=")
    assert "=" not in out and "+" not in out and "/" not in out
    padded = out + "=" * (-len(out) % 4)
    assert _base64.urlsafe_b64decode(padded) == point


def test_vapid_base64url_input_is_passed_through_normalized():
    point = _sample_p256_point()
    b64 = _base64.urlsafe_b64encode(point).decode()  # padded url-safe
    out = normalize_vapid_public_key(b64)
    assert out == b64.rstrip("=")  # unpadded, unchanged otherwise


def test_vapid_standard_base64_is_converted_to_urlsafe():
    # A standard-base64 key (with +/) must be translated to URL-safe (-/_).
    raw = bytes([0xFB, 0xFF, 0x04]) + bytes(62)
    std = _base64.b64encode(raw).decode()
    out = normalize_vapid_public_key(std)
    assert "+" not in out and "/" not in out and "=" not in out


def test_vapid_missing_input_returns_empty_safely():
    assert normalize_vapid_public_key("") == ""
    assert normalize_vapid_public_key("   ") == ""
    assert normalize_vapid_public_key(None) == ""


# ---- VAPID private-key normalization (legacy hex -> base64url raw scalar) -----
def test_vapid_private_hex_is_converted_to_raw_base64url():
    scalar = bytes(range(1, 33))  # 32-byte private scalar
    hex_key = scalar.hex()  # 64 chars, the legacy hex form
    assert len(hex_key) == 64
    out = normalize_vapid_private_key(hex_key)
    # Must decode to exactly 32 bytes — the form py_vapid's from_string treats as raw.
    padded = out + "=" * (-len(out) % 4)
    decoded = _base64.urlsafe_b64decode(padded)
    assert decoded == scalar and len(decoded) == 32
    assert "=" not in out and "+" not in out and "/" not in out


def test_vapid_private_hex_key_is_parseable_by_py_vapid():
    # The actual failure was py_vapid raising ValueError on a 64-char hex key.
    # After normalization the raw-key path must succeed.
    py_vapid = pytest.importorskip("py_vapid")
    scalar = bytes(range(1, 33))
    out = normalize_vapid_private_key(scalar.hex())
    # from_string base64url-decodes and uses from_raw when len==32; must not raise.
    py_vapid.Vapid01.from_string(out)


def test_vapid_private_pem_is_passed_through_untouched():
    pem = "-----BEGIN PRIVATE KEY-----\nMIGHAgEA\n-----END PRIVATE KEY-----"
    assert normalize_vapid_private_key(pem) == pem


def test_vapid_private_base64_is_normalized_urlsafe():
    raw = bytes(32)
    std = _base64.b64encode(raw).decode()
    out = normalize_vapid_private_key(std)
    assert "+" not in out and "/" not in out and "=" not in out


def test_vapid_private_missing_returns_empty_safely():
    assert normalize_vapid_private_key("") == ""
    assert normalize_vapid_private_key("   ") == ""
    assert normalize_vapid_private_key(None) == ""


def test_webpush_client_accepts_hex_private_key_without_format_failure(monkeypatch):
    # A client built from a legacy hex private key must store a parseable raw key
    # and report itself configured (given pywebpush present) — i.e. the key-format
    # problem is resolved before any network send is attempted.
    pytest.importorskip("pywebpush")
    scalar = bytes(range(1, 33))
    point = b"\x04" + bytes(range(64))
    client = WebPushClient(
        public_key=point.hex(),
        private_key=scalar.hex(),
        subject="mailto:alerts@alphalab.local",
    )
    # Stored private key is the normalized 32-byte raw form, not the raw hex.
    stored = client._private_key
    padded = stored + "=" * (-len(stored) % 4)
    assert _base64.urlsafe_b64decode(padded) == scalar
    assert client.is_configured is True


def test_sanitize_push_error_strips_endpoint_and_caps():
    msg = "WebPushException: failed for https://fcm.googleapis.com/fcm/send/abc123TOKEN"
    out = _sanitize_push_error(msg)
    assert "https://" not in out and "abc123TOKEN" not in out
    assert "[endpoint]" in out


def test_send_returns_sanitized_detail_without_endpoint(monkeypatch):
    # Force the webpush call to raise with an endpoint-bearing message; the
    # returned detail must be scrubbed and must not contain the URL/token.
    pytest.importorskip("pywebpush")
    scalar = bytes(range(1, 33))
    point = b"\x04" + bytes(range(64))
    client = WebPushClient(point.hex(), scalar.hex(), "mailto:a@b.c")

    def boom(*a, **k):
        raise ValueError("boom at https://fcm.googleapis.com/fcm/send/SECRETTOKEN")

    monkeypatch.setattr(client, "_webpush", boom)
    res = client.send({"endpoint": "https://x/y", "p256dh": "p", "auth": "a"}, {"t": 1})
    assert res["ok"] is False
    assert res["error"] == "ValueError"
    assert "https://" not in res["detail"] and "SECRETTOKEN" not in res["detail"]


def test_level_at_least_ordering():
    assert level_at_least("RISK_KILL", "APPROVAL_REQUIRED") is True
    assert level_at_least("WATCH", "URGENT_IDEA") is False
    assert level_at_least("INFO", "INFO") is True


def test_in_quiet_hours_overnight_wrap():
    # 22:00 -> 07:00 window.
    assert in_quiet_hours(datetime(2026, 6, 20, 23, 30), "22:00", "07:00") is True
    assert in_quiet_hours(datetime(2026, 6, 20, 6, 30), "22:00", "07:00") is True
    assert in_quiet_hours(datetime(2026, 6, 20, 12, 0), "22:00", "07:00") is False


def test_in_quiet_hours_disabled_when_unset():
    assert in_quiet_hours(datetime(2026, 6, 20, 3, 0), None, None) is False


def test_sanitize_text_redacts_secrets_and_digits():
    masked = sanitize_text("account 1234567890 token sk-ABCDEFGHIJKLMNOP")
    assert "1234567890" not in masked
    assert "****7890" in masked
    assert "[redacted]" in masked


# ---- routing rules ----------------------------------------------------------
def test_route_alert_all_disabled_by_default():
    decision = route_alert("RISK_KILL", base_prefs())
    assert decision["push"] is False
    assert decision["sms"] is False


def test_route_push_respects_min_level():
    prefs = base_prefs(pwa_push_enabled=True, push_min_level="URGENT_IDEA")
    assert route_alert("WATCH", prefs)["push"] is False
    assert route_alert("URGENT_IDEA", prefs)["push"] is True


def test_route_sms_requires_number_and_min_level():
    prefs = base_prefs(sms_enabled=True, sms_min_level="APPROVAL_REQUIRED")
    # No number configured -> no SMS even at high level.
    assert route_alert("RISK_KILL", prefs)["sms"] is False
    prefs["sms_phone_number"] = "+15555550123"
    assert route_alert("APPROVAL_REQUIRED", prefs)["sms"] is True
    assert route_alert("WATCH", prefs)["sms"] is False


def test_quiet_hours_suppresses_low_levels_but_bypassed_by_critical():
    now = datetime(2026, 6, 20, 23, 30)
    prefs = base_prefs(
        pwa_push_enabled=True,
        push_min_level="INFO",
        sms_enabled=True,
        sms_phone_number="+15555550123",
        sms_min_level="WATCH",
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
    )
    watch = route_alert("WATCH", prefs, now=now)
    assert watch["push"] is False
    assert watch["sms"] is False
    assert watch["quiet_hours"] is True

    critical = route_alert("RISK_KILL", prefs, now=now)
    assert critical["push"] is True
    assert critical["sms"] is True
    assert critical["quiet_hours_bypassed"] is True


# ---- dispatch (dry-run, no network) -----------------------------------------
def center(tmp_path: Path) -> NotificationCenter:
    return NotificationCenter(db_path=str(tmp_path / "alpha.sqlite3"))


def test_dispatch_dry_run_audits_without_sending(tmp_path: Path):
    nc = center(tmp_path)
    nc.update_preferences({"pwa_push_enabled": True, "push_min_level": "INFO"})
    summary = nc.create_and_dispatch("URGENT_IDEA", "Test", "body", "unit-test", force_dry_run=True)
    assert summary["dry_run"] is True
    assert summary["decision"]["push"] is True
    # Dry-run never marks a channel as actually sent.
    assert summary["channels_sent"] == []
    audit = nc.list_audit()
    assert any(row["channel"] == "pwa_push" and row["status"] == "dry_run" for row in audit)


def test_create_alert_persists_and_lists(tmp_path: Path):
    nc = center(tmp_path)
    nc.create_alert("WATCH", "Hello", "world", "unit-test")
    result = nc.list_alerts()
    assert result["unread"] == 1
    assert result["alerts"][0]["title"] == "Hello"
    assert result["alerts"][0]["channels_sent"] == []


def test_set_alert_status_validation(tmp_path: Path):
    nc = center(tmp_path)
    alert = nc.create_alert("INFO", "x")
    nc.set_alert_status(alert["id"], "read")
    assert nc.get_alert(alert["id"])["status"] == "read"
    with pytest.raises(ValueError):
        nc.set_alert_status(alert["id"], "bogus")


def test_subscription_roundtrip(tmp_path: Path):
    nc = center(tmp_path)
    nc.save_subscription({"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}})
    assert len(nc.list_subscriptions()) == 1
    removed = nc.remove_subscription("https://push.example/abc")
    assert removed["removed"] == 1
    assert nc.list_subscriptions() == []


# ---- strict preference validation (#8) --------------------------------------
def test_update_preferences_rejects_malformed_values(tmp_path: Path):
    nc = center(tmp_path)
    with pytest.raises(ValueError):
        nc.update_preferences({"pwa_push_enabled": "maybe"})  # not a boolean
    with pytest.raises(ValueError):
        nc.update_preferences({"push_min_level": "LOUD"})  # unknown level
    with pytest.raises(ValueError):
        nc.update_preferences({"sms_phone_number": "not-a-number"})
    with pytest.raises(ValueError):
        nc.update_preferences({"quiet_hours_start": "25:99"})  # bad clock


def test_update_preferences_accepts_and_normalizes_valid(tmp_path: Path):
    nc = center(tmp_path)
    prefs = nc.update_preferences(
        {
            "pwa_push_enabled": True,
            "sms_phone_number": "+1 (555) 555-0123",
            "quiet_hours_start": "22:00",
        }
    )
    assert prefs["pwa_push_enabled"] is True
    # The API return masks the number (last 4 only) and confirms it's configured;
    # the full value never leaves the server.
    assert prefs["sms_phone_number"] == "***-***-0123"
    assert prefs["sms_phone_configured"] is True
    assert prefs["quiet_hours_start"] == "22:00"
    # Separators were stripped before storage (raw value stays server-side).
    with connect(nc.db_path) as conn:
        raw = conn.execute(
            "SELECT sms_phone_number FROM notification_preferences WHERE id = 1"
        ).fetchone()[0]
    assert raw == "+15555550123"


# ---- phone masking on reads (#4) --------------------------------------------
def test_get_preferences_masks_phone_and_flags_configured(tmp_path: Path):
    nc = center(tmp_path)
    nc.update_preferences({"sms_phone_number": "+15555550123"})
    prefs = nc.get_preferences()
    assert prefs["sms_phone_number"] == "***-***-0123"
    assert prefs["sms_phone_configured"] is True


def test_get_preferences_reports_unconfigured_phone(tmp_path: Path):
    nc = center(tmp_path)
    prefs = nc.get_preferences()
    assert prefs["sms_phone_number"] == ""
    assert prefs["sms_phone_configured"] is False


def test_blank_phone_update_preserves_stored_number(tmp_path: Path):
    # The frontend omits sms_phone_number when its field is left blank, so an
    # unrelated update must never wipe the stored number.
    nc = center(tmp_path)
    nc.update_preferences({"sms_phone_number": "+15555550123"})
    nc.update_preferences({"sms_enabled": True})  # no sms_phone_number key
    with connect(nc.db_path) as conn:
        raw = conn.execute(
            "SELECT sms_phone_number FROM notification_preferences WHERE id = 1"
        ).fetchone()[0]
    assert raw == "+15555550123"


def test_clamp_limit_bounds():
    assert clamp_limit(10) == 10
    assert clamp_limit(0) == 1
    assert clamp_limit(10_000) == 500
    assert clamp_limit(-5) == 1
    assert clamp_limit("bad") == 100


def test_subscription_requires_https_endpoint(tmp_path: Path):
    nc = center(tmp_path)
    with pytest.raises(ValueError):
        nc.save_subscription(
            {"endpoint": "http://insecure/x", "keys": {"p256dh": "k", "auth": "a"}}
        )


# ---- notification click routing (#5) ----------------------------------------
def test_click_url_resolves_to_known_routes(tmp_path: Path):
    nc = center(tmp_path)
    alert = nc.create_alert("URGENT_IDEA", "t")
    url = _click_url(alert)
    # Router selects the page from the leading hash segment ("alerts/<id>" -> alerts).
    base = url.replace("/#", "").split("/")[0]
    assert base == "alerts"
    crit = nc.create_alert("APPROVAL_REQUIRED", "t")
    assert _click_url(crit) == "/#approvals"


# ---- service worker privacy (#7) --------------------------------------------
def test_service_worker_excludes_api_from_cache():
    sw = Path("alpha_lab/static/sw.js").read_text(encoding="utf-8")
    assert 'pathname.startsWith("/api/")' in sw
    assert "isApi" in sw
    # The cache write must be guarded by the !isApi check.
    assert "!isApi" in sw


# ---- SMS env fallback routing (#6) ------------------------------------------
def test_sms_env_fallback_makes_routing_reachable(monkeypatch):
    prefs = base_prefs(sms_enabled=True, sms_phone_number="", sms_min_level="WATCH")
    # Without the env fallback there is no number -> no SMS.
    monkeypatch.delenv("ALERT_SMS_TO_NUMBER", raising=False)
    assert route_alert("WATCH", _apply_sms_fallback(prefs))["sms"] is False
    # With it, routing becomes reachable.
    monkeypatch.setenv("ALERT_SMS_TO_NUMBER", "+15555550123")
    effective = _apply_sms_fallback(prefs)
    assert effective["sms_phone_number"] == "+15555550123"
    assert route_alert("WATCH", effective)["sms"] is True


def test_malformed_env_fallback_is_rejected_fail_closed(monkeypatch):
    # A malformed ALERT_SMS_TO_NUMBER must NOT be injected — it can never make SMS
    # routing eligible (same fail-closed validator as a stored number).
    prefs = base_prefs(sms_enabled=True, sms_phone_number="", sms_min_level="WATCH")
    monkeypatch.setenv("ALERT_SMS_TO_NUMBER", "not-a-real-number")
    effective = _apply_sms_fallback(prefs)
    assert effective.get("sms_phone_number", "") == ""
    assert route_alert("RISK_KILL", effective)["sms"] is False


class _FakeSMS:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    @property
    def is_configured(self) -> bool:
        return True

    def send(self, to_number: str, body: str) -> dict:
        self.sent.append((to_number, body))
        return {"ok": True, "sid": "SM_fake"}


def test_dispatch_real_sms_uses_env_fallback_number(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALERT_SMS_ENABLED", "true")
    monkeypatch.setenv("ALERT_SMS_TO_NUMBER", "+15555550999")
    fake = _FakeSMS()
    nc = NotificationCenter(db_path=str(tmp_path / "sms.sqlite3"), sms_client=fake)
    nc.update_preferences({"sms_enabled": True, "sms_min_level": "WATCH", "sms_phone_number": ""})
    summary = nc.create_and_dispatch("RISK_KILL", "t", "b", "src", force_dry_run=False)
    assert summary["decision"]["sms"] is True
    assert fake.sent and fake.sent[0][0] == "+15555550999"


# ---- provider fake live-send (#10) ------------------------------------------
class _FakePush:
    library_available = True

    def __init__(self):
        self.sent: list[tuple[dict, dict]] = []

    @property
    def is_configured(self) -> bool:
        return True

    def send(self, subscription: dict, payload: dict) -> dict:
        self.sent.append((subscription, payload))
        return {"ok": True}


def test_dispatch_real_push_send_with_fake_client(tmp_path: Path):
    fake = _FakePush()
    nc = NotificationCenter(db_path=str(tmp_path / "push.sqlite3"), push_client=fake)
    nc.update_preferences({"pwa_push_enabled": True, "push_min_level": "INFO"})
    nc.save_subscription({"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}})
    summary = nc.create_and_dispatch("URGENT_IDEA", "t", "b", "src", force_dry_run=False)
    assert summary["channels_sent"] == ["pwa_push"]
    assert len(fake.sent) == 1
    assert any(r["channel"] == "pwa_push" and r["status"] == "sent" for r in nc.list_audit())


# ---- dedup / idempotency (#2) -----------------------------------------------
def test_notify_event_deduplicates(tmp_path: Path):
    nc = center(tmp_path)
    first = nc.notify_event("APPROVAL_REQUIRED", "Approval needed: NVDA", "b", "src", dedup_key="approval:1")
    assert first["deduplicated"] is False
    second = nc.notify_event("APPROVAL_REQUIRED", "Approval needed: NVDA", "b2", "src", dedup_key="approval:1")
    assert second["deduplicated"] is True
    assert second["dispatched"] is False
    approval = [a for a in nc.list_alerts()["alerts"] if a["title"].startswith("Approval needed")]
    assert len(approval) == 1  # only one alert ever created


def test_dedup_partial_unique_index_blocks_concurrent_duplicate(tmp_path: Path):
    # The atomic dedupe guarantee: a partial UNIQUE index on (dedup_key WHERE the
    # alert is live) means a racing INSERT for the same key cannot create a second
    # live alert — so two concurrent-ish callers can never both dispatch.
    nc = center(tmp_path)
    first = nc.notify_event("APPROVAL_REQUIRED", "Approval needed: NVDA", "b", "src", dedup_key="approval:42")
    assert first["deduplicated"] is False
    with connect(nc.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO alerts (level, title, status, dedup_key) "
                "VALUES ('APPROVAL_REQUIRED', 'racing dup', 'unread', 'approval:42')"
            )
    # Only one alert exists for the key.
    live = [a for a in nc.list_alerts()["alerts"] if a.get("dedup_key") == "approval:42"]
    assert len(live) == 1


def test_dedup_allows_new_alert_after_prior_dismissed(tmp_path: Path):
    # Once the live alert leaves the index (dismissed/actioned), a NEW alert for the
    # same key is allowed again — the constraint only spans live alerts.
    nc = center(tmp_path)
    first = nc.notify_event("APPROVAL_REQUIRED", "Approval needed: NVDA", "b", "src", dedup_key="approval:7")
    assert first["deduplicated"] is False
    nc.set_alert_status(first["alert"]["id"], "dismissed")
    second = nc.notify_event("APPROVAL_REQUIRED", "Approval needed: NVDA", "b", "src", dedup_key="approval:7")
    assert second["deduplicated"] is False
    assert second["alert"]["id"] != first["alert"]["id"]


def test_migration_reconciles_duplicate_live_dedup_keys(tmp_path: Path):
    # A pre-fix DB can hold duplicate LIVE dedup keys that the unique index would
    # reject. init must reconcile them deterministically and never raise.
    db = str(tmp_path / "prefix.sqlite3")
    init_db(db)  # full schema (incl. the unique index)
    # Simulate a pre-fix state: drop the unique index, then inject duplicate live
    # rows sharing a dedup_key plus a historical (dismissed) row that must survive.
    with connect(db) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_alerts_dedup_live")
        conn.execute("INSERT INTO alerts (title, status, dedup_key) VALUES ('old', 'unread', 'approval:9')")
        conn.execute("INSERT INTO alerts (title, status, dedup_key) VALUES ('mid', 'read', 'approval:9')")
        conn.execute("INSERT INTO alerts (title, status, dedup_key) VALUES ('new', 'unread', 'approval:9')")
        conn.execute("INSERT INTO alerts (title, status, dedup_key) VALUES ('history', 'dismissed', 'approval:9')")
        conn.commit()
        newest_live_id = conn.execute(
            "SELECT MAX(id) FROM alerts WHERE dedup_key = 'approval:9' AND status IN ('unread', 'read')"
        ).fetchone()[0]

    # Re-running init must NOT raise despite the duplicate live keys.
    init_db(db)

    with connect(db) as conn:
        # The unique index is (re)created.
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_alerts_dedup_live'"
        ).fetchone()
        assert idx is not None
        # Exactly one LIVE row keeps the dedup_key, and it is the newest (max id).
        live = conn.execute(
            "SELECT id FROM alerts WHERE dedup_key = 'approval:9' AND status IN ('unread', 'read')"
        ).fetchall()
        assert [r[0] for r in live] == [newest_live_id]
        # Alert history is preserved — no rows were deleted.
        assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 4
        # The older duplicates were retired by nulling their key, not removed.
        retired = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE dedup_key IS NULL AND status IN ('unread', 'read')"
        ).fetchone()[0]
        assert retired == 2

    # Idempotent: another init still doesn't raise and changes nothing.
    init_db(db)
    with connect(db) as conn:
        live2 = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE dedup_key = 'approval:9' AND status IN ('unread', 'read')"
        ).fetchone()[0]
        assert live2 == 1


# ---- secured test endpoint (#1) + API auth (#8/#10) -------------------------
def _client(tmp_path: Path) -> TestClient:
    lab = AlphaLabService(
        db_path=str(tmp_path / "api.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )
    return TestClient(create_app(lab))


def test_vapid_endpoint_returns_base64url_when_configured(tmp_path: Path, monkeypatch):
    # Stored as legacy hex; the endpoint must serve a valid base64url key.
    point = _sample_p256_point()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", point.hex())
    client = _client(tmp_path)
    resp = client.get("/api/notifications/vapid-public-key")
    assert resp.status_code == 200
    key = resp.json()["public_key"]
    assert key and "+" not in key and "/" not in key and "=" not in key
    padded = key + "=" * (-len(key) % 4)
    assert _base64.urlsafe_b64decode(padded) == point  # round-trips to the P-256 point


def test_vapid_endpoint_returns_empty_when_unconfigured(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    client = _client(tmp_path)
    resp = client.get("/api/notifications/vapid-public-key")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == ""


def test_vapid_route_never_exposes_private_key(tmp_path: Path, monkeypatch):
    # With BOTH keys configured, no public route may echo the private key in any form.
    secret_hex = bytes(range(1, 33)).hex()  # legacy 64-char hex private key
    secret_b64 = _base64.urlsafe_b64encode(bytes(range(1, 33))).decode().rstrip("=")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", (b"\x04" + bytes(range(64))).hex())
    monkeypatch.setenv("VAPID_PRIVATE_KEY", secret_hex)
    client = _client(tmp_path)
    for path in (
        "/api/notifications/vapid-public-key",
        "/api/notifications/preferences",
        "/api/notifications/audit",
    ):
        body = client.get(path).text
        assert secret_hex not in body
        assert secret_b64 not in body


def test_test_endpoint_is_dry_run_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS", raising=False)
    client = _client(tmp_path)
    resp = client.post("/api/notifications/test", json={"level": "WATCH"})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True


def test_test_endpoint_refuses_real_send_without_gate(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS", raising=False)
    client = _client(tmp_path)
    resp = client.post("/api/notifications/test", json={"level": "WATCH", "force_dry_run": False})
    assert resp.status_code == 403


def test_test_endpoint_allows_real_send_only_when_gated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS", "true")
    client = _client(tmp_path)
    resp = client.post("/api/notifications/test", json={"level": "WATCH", "force_dry_run": False})
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is False  # honored, but no channels enabled so nothing sends


def test_test_endpoint_rejects_unknown_fields(tmp_path: Path):
    client = _client(tmp_path)
    resp = client.post("/api/notifications/test", json={"level": "WATCH", "evil": "x"})
    assert resp.status_code == 400


def test_test_endpoint_rejects_unknown_level(tmp_path: Path):
    client = _client(tmp_path)
    resp = client.post("/api/notifications/test", json={"level": "NONSENSE"})
    assert resp.status_code == 400


def test_preferences_endpoint_returns_400_on_bad_input(tmp_path: Path):
    client = _client(tmp_path)
    resp = client.post("/api/notifications/preferences", json={"push_min_level": "LOUD"})
    assert resp.status_code == 400


def test_write_endpoints_require_token_when_set(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ALPHALAB_API_TOKEN", "secret-token")
    client = _client(tmp_path)
    # Reads stay open.
    assert client.get("/api/alerts").status_code == 200
    # Writes without a bearer are rejected.
    assert client.post("/api/notifications/test", json={"level": "WATCH"}).status_code == 401
    # Writes with the correct bearer succeed.
    ok = client.post(
        "/api/notifications/test",
        json={"level": "WATCH"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert ok.status_code == 200


# ---- approval audit reliability + transactionality (#3) ---------------------
def _lab(tmp_path: Path) -> AlphaLabService:
    return AlphaLabService(
        db_path=str(tmp_path / "svc.sqlite3"),
        risk_config_path="alpha_lab/config.example.json",
        audit_log_path=str(tmp_path / "audit.jsonl"),
    )


def _make_idea(lab: AlphaLabService) -> dict:
    return lab.create_idea(
        {
            "ticker": "NVDA",
            "bias": "bullish",
            "confidence": 0.8,
            "timeframe": "intraday",
            "thesis": "AI momentum.",
            "source": "test",
            "timestamp": "2026-06-04T13:00:00Z",
        }
    )


def test_approval_writes_audit_row(tmp_path: Path):
    lab = _lab(tmp_path)
    idea = _make_idea(lab)
    lab.approve_idea_for_execution(idea["id"], "looks good")
    with connect(lab.db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM approval_decisions WHERE idea_id = ?", (idea["id"],)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["decision"] == "approved"


def test_approval_audit_is_atomic_on_failure(tmp_path: Path, monkeypatch):
    lab = _lab(tmp_path)
    idea = _make_idea(lab)

    def boom(self, *args, **kwargs):
        raise RuntimeError("approval write failed")

    monkeypatch.setattr(AlphaLabRepository, "set_approval_status", boom)
    with pytest.raises(RuntimeError):
        lab.approve_idea_for_execution(idea["id"], "note")
    # The staged audit row must roll back with the failed approval — not linger.
    with connect(lab.db_path) as conn:
        audit = conn.execute(
            "SELECT * FROM approval_decisions WHERE idea_id = ?", (idea["id"],)
        ).fetchall()
        status = conn.execute(
            "SELECT status FROM alpha_ideas WHERE id = ?", (idea["id"],)
        ).fetchone()["status"]
    assert audit == []
    assert status != "approved"


def test_live_execution_flag_is_audit_metadata_only(tmp_path: Path, monkeypatch):
    # The flag only stamps live_mode; with it unset the audit records 0 and the
    # approval still succeeds (it does not gate execution).
    monkeypatch.delenv("ALPHALAB_ALLOW_LIVE_EXECUTION", raising=False)
    lab = _lab(tmp_path)
    idea = _make_idea(lab)
    lab.approve_idea_for_execution(idea["id"])
    with connect(lab.db_path) as conn:
        row = conn.execute(
            "SELECT live_mode FROM approval_decisions WHERE idea_id = ?", (idea["id"],)
        ).fetchone()
    assert row["live_mode"] == 0


def test_notify_approval_required_creates_deduped_alert(tmp_path: Path):
    lab = _lab(tmp_path)
    payload = {"action": "needs_human_approval", "ticker": "NVDA"}
    lab._notify_approval_required(7, payload)
    lab._notify_approval_required(7, payload)  # repeated attempt must not spam
    alerts = lab.notifications.list_alerts()["alerts"]
    approval = [a for a in alerts if a["level"] == "APPROVAL_REQUIRED"]
    assert len(approval) == 1
    assert approval[0]["source"] == "paper-execution"
