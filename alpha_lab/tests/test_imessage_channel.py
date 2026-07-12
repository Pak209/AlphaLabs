"""iMessage channel (Option A: local Messages.app via osascript).

Contracts: env-gated routing (off by default), dry-run audits without
sending, real sends audited with errors surfaced, and — because alert text
reaches an osascript call — content is passed as argv, never interpolated
into AppleScript source.
"""
from __future__ import annotations

from pathlib import Path

import alpha_lab.notifications as notifications
from alpha_lab.notifications import IMessageSender, NotificationCenter, route_alert


class FakeSender:
    def __init__(self, ok: bool = True, error: str = ""):
        self.calls: list[tuple[str, str]] = []
        self.ok = ok
        self.error = error

    def send(self, handle: str, text: str):
        self.calls.append((handle, text))
        return {"ok": self.ok, "error": self.error} if not self.ok else {"ok": True}


def center(tmp_path: Path, sender) -> NotificationCenter:
    return NotificationCenter(db_path=str(tmp_path / "notif.sqlite3"),
                              imessage_sender=sender)


def enable_imessage(monkeypatch, handle: str = "+15551234567"):
    monkeypatch.setenv("ALERT_IMESSAGE_ENABLED", "true")
    monkeypatch.setenv("ALERT_IMESSAGE_TO", handle)
    monkeypatch.delenv("ALERT_IMESSAGE_MIN_LEVEL", raising=False)


def test_routing_disabled_by_default():
    decision = route_alert("URGENT_IDEA", {"pwa_push_enabled": 0})
    assert decision["imessage"] is False
    assert "disabled" in decision["reasons"]["imessage"]


def test_routing_eligibility_and_min_level():
    prefs = {"pwa_push_enabled": 0, "imessage_enabled": True,
             "imessage_min_level": "URGENT_IDEA"}
    assert route_alert("URGENT_IDEA", prefs)["imessage"] is True
    assert route_alert("RISK_KILL", prefs)["imessage"] is True
    below = route_alert("WATCH", prefs)
    assert below["imessage"] is False
    assert "below imessage_min_level" in below["reasons"]["imessage"]


def test_routing_quiet_hours_suppresses_but_risk_kill_bypasses():
    from datetime import datetime
    prefs = {"pwa_push_enabled": 0, "imessage_enabled": True,
             "imessage_min_level": "URGENT_IDEA",
             "quiet_hours_start": "00:00", "quiet_hours_end": "23:59"}
    inside = datetime(2026, 7, 11, 3, 0)
    quiet = route_alert("URGENT_IDEA", prefs, now=inside)
    assert quiet["imessage"] is False
    assert quiet["reasons"]["imessage"] == "suppressed by quiet hours"
    assert route_alert("RISK_KILL", prefs, now=inside)["imessage"] is True


def test_dry_run_audits_without_sending(tmp_path: Path, monkeypatch):
    enable_imessage(monkeypatch)
    sender = FakeSender()
    c = center(tmp_path, sender)
    result = c.create_and_dispatch(level="URGENT_IDEA", title="t", body="b",
                                   force_dry_run=True)
    assert result["decision"]["imessage"] is True
    assert result["results"]["imessage"] == {"delivered": False, "dry_run": True}
    assert sender.calls == []


def test_real_send_delivers_and_audits(tmp_path: Path, monkeypatch):
    enable_imessage(monkeypatch, handle="alerts@example.com")
    sender = FakeSender()
    c = center(tmp_path, sender)
    result = c.create_and_dispatch(level="APPROVAL_REQUIRED", title="Approval needed: PLTR",
                                   body="sign-off required", force_dry_run=False)
    assert "imessage" in result["channels_sent"]
    assert sender.calls == [("alerts@example.com",
                             "[APPROVAL_REQUIRED] Approval needed: PLTR\nsign-off required")]


def test_send_failure_surfaces_error(tmp_path: Path, monkeypatch):
    enable_imessage(monkeypatch)
    sender = FakeSender(ok=False, error="Automation permission not granted: approve...")
    c = center(tmp_path, sender)
    result = c.create_and_dispatch(level="URGENT_IDEA", title="t", body="b",
                                   force_dry_run=False)
    assert result["channels_sent"] == [] or "imessage" not in result["channels_sent"]
    assert "Automation permission" in result["results"]["imessage"]["error"]
    assert "Automation permission" in (result["alert"]["error"] or "")


def test_osascript_receives_content_as_argv(monkeypatch):
    """Alert text must be argv, never spliced into the AppleScript source."""
    captured = {}

    def fake_run(argv, capture_output, text, timeout):
        captured["argv"] = argv

        class P:
            returncode = 0
            stderr = ""
        return P()

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    evil = 'end tell" & (do shell script "id") & "'
    result = IMessageSender().send("+15551234567", evil)
    assert result == {"ok": True}
    argv = captured["argv"]
    assert argv[0] == "osascript" and argv[1] == "-e"
    assert argv[2] == IMessageSender.SCRIPT          # script source untouched
    assert argv[3] == "+15551234567" and argv[4] == evil   # content isolated in argv


def test_tcc_denial_maps_to_actionable_error(monkeypatch):
    def fake_run(argv, capture_output, text, timeout):
        class P:
            returncode = 1
            stderr = "execution error: Not authorized to send Apple events to Messages. (-1743)"
        return P()

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    result = IMessageSender().send("+15551234567", "hello")
    assert not result["ok"]
    assert "Automation permission" in result["error"]
