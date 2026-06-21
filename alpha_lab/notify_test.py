"""
alpha_lab/notify_test.py — test-mode for the notification system.

Creates synthetic alerts at each level and runs them through the real routing +
dispatch path so you can verify *which* channels would fire — WITHOUT sending
anything by default. Dispatch defaults to dry-run (ALERT_DELIVERY_DRY_RUN), which
LOGS every would-be delivery to the notification_audit table but sends no push or
SMS. Pass --send to actually deliver (still gated by per-alert preferences AND the
ALERT_SMS_ENABLED / VAPID / Twilio config — nothing leaves the box unless fully
configured and opted in).

    .venv/bin/python -m alpha_lab.notify_test                 # all 4 sample levels, dry-run
    .venv/bin/python -m alpha_lab.notify_test --level URGENT_IDEA
    .venv/bin/python -m alpha_lab.notify_test --json
    .venv/bin/python -m alpha_lab.notify_test --send          # real delivery (if configured)
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from .env import load_dotenv
from .notifications import NotificationCenter, delivery_is_dry_run

# The levels test-mode exercises by default — one actionable sample per tier above
# INFO, matching the requirement (WATCH / URGENT_IDEA / APPROVAL_REQUIRED / RISK_KILL).
DEFAULT_LEVELS = ["WATCH", "URGENT_IDEA", "APPROVAL_REQUIRED", "RISK_KILL"]

SAMPLE_BODIES = {
    "WATCH": "Watchlist ticker is approaching a key level; no action required yet.",
    "URGENT_IDEA": "A high-conviction idea just crossed its trigger — review soon.",
    "APPROVAL_REQUIRED": "A paper trade is staged and needs your sign-off before execution.",
    "RISK_KILL": "Risk guard tripped — positions flattened. Immediate attention.",
}


def run(levels: list[str], *, force_dry_run: bool | None, db_path: str | None = None) -> list[dict[str, Any]]:
    center = NotificationCenter(db_path=db_path)
    results = []
    for level in levels:
        summary = center.create_and_dispatch(
            level=level,
            title=f"[TEST] {level}",
            body=SAMPLE_BODIES.get(level, "Synthetic test alert."),
            source="notify_test",
            force_dry_run=force_dry_run,
        )
        results.append(summary)
    return results


def _format_human(results: list[dict[str, Any]]) -> str:
    lines = ["AlphaLab notification test", "=========================="]
    for summary in results:
        alert = summary["alert"]
        decision = summary["decision"]
        mode = "DRY-RUN (no send)" if summary["dry_run"] else "LIVE SEND"
        lines.append(f"  #{alert['id']} {alert['level']:<17} [{mode}]")
        lines.append(f"      push={decision['push']}  sms={decision['sms']}  "
                     f"quiet_hours={decision['quiet_hours']}  channels_sent={summary['channels_sent']}")
        for channel, reason in decision["reasons"].items():
            lines.append(f"      - {channel}: {reason}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create synthetic alerts and run them through routing + dispatch.")
    parser.add_argument("--level", default=None, help=f"Single level to test (default: {', '.join(DEFAULT_LEVELS)}).")
    parser.add_argument("--db", default=None, help="SQLite DB path; defaults to ALPHA_LAB_DB_PATH or app default.")
    parser.add_argument("--send", action="store_true",
                        help="Actually deliver (still gated by prefs + channel config). Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    load_dotenv()
    levels = [args.level.strip().upper()] if args.level else DEFAULT_LEVELS
    # --send flips to real delivery; otherwise force dry-run regardless of env so the
    # test command is always safe to run by default.
    force_dry_run = False if args.send else True
    results = run(levels, force_dry_run=force_dry_run, db_path=args.db)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(_format_human(results))
        if not args.send and not delivery_is_dry_run():
            print("\n  (env ALERT_DELIVERY_DRY_RUN is off, but --send was not passed — forced dry-run.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
