# Safe Production PWA Push Policy & Runbook

This runbook defines which alerts are allowed to reach the iPhone as **real**
Web Push notifications, how to run one supervised real-push test, and how to
return to the safe dry-run posture. It is notifications-only: it never changes
scheduler mode, paper trading, Alpaca, or live-trading settings.

## Policy: which levels may push

Real PWA push is reserved for **important, actionable** alerts. The five ordered
levels (lowest → highest severity) are `INFO`, `WATCH`, `URGENT_IDEA`,
`APPROVAL_REQUIRED`, `RISK_KILL`.

| Level             | Real push? | Rationale                                  |
| ----------------- | ---------- | ------------------------------------------ |
| `INFO`            | No         | Routine; would be spam.                    |
| `WATCH`           | No         | Informational; would be spam.              |
| `URGENT_IDEA`     | Yes        | Time-sensitive opportunity.                |
| `APPROVAL_REQUIRED` | Yes      | A trade needs human sign-off.              |
| `RISK_KILL`       | Yes        | Risk tripped; needs immediate attention.   |

The policy is `push_min_level = URGENT_IDEA`. Because routing uses a "level ≥
min" comparison, this allows exactly `URGENT_IDEA`, `APPROVAL_REQUIRED`, and
`RISK_KILL` and excludes `INFO`/`WATCH`.

Enforcement points in code:

- `PRODUCTION_PUSH_MIN_LEVEL = "URGENT_IDEA"` and `PUSH_ELIGIBLE_LEVELS` in
  `alpha_lab/notifications.py` express the policy.
- `route_alert()` fails safe to `PRODUCTION_PUSH_MIN_LEVEL` when no
  `push_min_level` is stored, so a missing/blank value can never widen coverage.
- The `notification_preferences.push_min_level` schema default is `URGENT_IDEA`
  (`alpha_lab/database.py`), so a freshly provisioned box is safe-by-default.
- Tests lock this in: see `test_route_alert_production_policy_pushes_only_important_levels`,
  `test_route_alert_fails_safe_to_policy_floor_when_min_level_missing`,
  `test_fresh_db_push_min_level_defaults_to_policy_floor`, and
  `test_production_push_policy_eligible_levels` in
  `alpha_lab/tests/test_notifications.py`.

SMS stays disabled in all cases (`ALERT_SMS_ENABLED=false`).

### Applying the policy to an existing box

The schema default only affects **new** databases. An existing
`notification_preferences` row keeps whatever `push_min_level` it was created
with. Check it (read-only):

```bash
# On the server (reads are open; no token needed):
curl -s http://127.0.0.1:8787/api/notifications/preferences \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("push_min_level=",d["push_min_level"],"pwa_push_enabled=",d["pwa_push_enabled"])'
```

If `push_min_level` is not `URGENT_IDEA`, raise it to the policy floor before any
real delivery is enabled (this only narrows what would push — it is strictly
safety-increasing):

```bash
# Token-protected write; read the token without printing it.
TOKEN=$(grep -E '^ALPHALAB_API_TOKEN=' .env | head -1 | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8787/api/notifications/preferences \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"push_min_level":"URGENT_IDEA"}' >/dev/null
```

## Actionable routing: where a tapped notification opens

A delivered push is not just a banner — tapping it opens AlphaLabs directly to the
item that triggered it. The server attaches only safe routing metadata to the
payload (no secrets): `alert_id`, `related_trade_id` (FK to `trades`, may be
null), `level`, `source`, and a precomputed in-app hash `url`.

`_click_url()` in `alpha_lab/notifications.py` chooses the destination:

| Alert level                         | Destination hash route        |
| ----------------------------------- | ----------------------------- |
| `APPROVAL_REQUIRED` / `RISK_KILL`   | `/#approvals` (the queue)     |
| All other levels (`URGENT_IDEA`, …) | `/#alerts/<alert_id>`         |

All destinations are **hash-only, same-origin** routes — no external URLs ever
travel in the payload (`test_click_url_routes_are_hash_only_no_external_urls`).

Why sign-off alerts are **not** deep-linked to a specific card: the approval
queue is keyed by `idea_id` (an idea awaiting sign-off, *before* any trade
exists), while the only structured id an alert carries is `related_trade_id` — a
`trades` foreign key that only exists *after* placement. The two never coincide on
the approvals page, so a `/#approvals/<trade_id>` deep-link could never match a
card. Sign-off clicks therefore land on the queue itself, which is the reliable
behavior. (`related_trade_id` still rides along in the payload as informational
metadata.)

Delivery path:

1. `_deliver_push()` builds the payload with the metadata above.
2. `sw.js` `push` handler stores `{url, alert_id, related_trade_id, level,
   source}` on the notification's `data`.
3. `sw.js` `notificationclick` navigates the focused/new tab to `url` **and**
   `postMessage`s the same metadata (an already-open tab whose base route matches
   may not fire `hashchange`, so the app routes from the message instead).
4. `app.js` parses the trailing id from the hash (`routeFocusId`), stashes it as
   `pendingFocus`, and `applyPendingFocus()` highlights the matching card with a
   transient `.notif-focus` pulse, scrolling it into view. The selectors match the
   markers the cards actually render: alert detail uses
   `.alert-card[data-alert-id]`; the approvals branch uses
   `.approval-card[data-idea-id]` (the queue's natural key). Since sign-off alerts
   route to `/#approvals` with no trailing id, the approvals highlight is a safe
   no-op today, but the selector is now correct so an idea-keyed deep-link would
   highlight the right card if one is ever introduced.

Future option (out of scope here, needs a DB change): to deep-link a sign-off
notification to its exact approval card, the alert would need to carry the
`idea_id` (e.g. a new `related_idea_id` column on `alerts`) and `_click_url()`
would emit `/#approvals/<idea_id>`. The frontend selector already targets
`data-idea-id`, so only the server/schema side would need work.

Tests covering this: `test_click_url_*`,
`test_app_js_approval_highlight_targets_idea_id_marker`,
`test_push_payload_includes_safe_routing_metadata`, and
`test_service_worker_carries_routing_metadata_and_posts_click` in
`alpha_lab/tests/test_notifications.py`.

## 1. How to run ONE supervised real push test

Real delivery is OFF by default (`ALERT_DELIVERY_DRY_RUN=true`). A real send also
requires the explicit per-run opt-in `ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=true`.
Run a single test only while supervised, then revert immediately (section 2).

Pre-checks (read-only) — confirm the safe baseline first:

```bash
cd ~/AlphaLab
./ops safety-status        # scheduler dry_run, paper-trade guard disarmed
ssh danielkimoto@100.91.41.60 'curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8787/api/health'
```

Enable real delivery for the test (back up `.env` first; never print its
contents). Set exactly these three keys, leaving SMS off:

```text
ALERT_DELIVERY_DRY_RUN=false
ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=true
ALERT_SMS_ENABLED=false
```

Restart services so the new env is loaded, then send exactly one alert at an
eligible level (`URGENT_IDEA` / `APPROVAL_REQUIRED` / `RISK_KILL`):

```bash
./ops restart --yes        # kickstart dashboard + scheduler
# On the server; token read without printing:
TOKEN=$(grep -E '^ALPHALAB_API_TOKEN=' .env | head -1 | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8787/api/notifications/test \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"level":"URGENT_IDEA","force_dry_run":false}'
```

Success looks like `"dry_run": false` with
`"results": {"pwa_push": {"delivered": true, "sent": 1, "error": null}}` and the
notification appearing on the iPhone. (Testing `INFO`/`WATCH` with
`force_dry_run:false` correctly yields no push — they are below the policy floor.)

## 2. How to revert to dry-run

Immediately after the test, restore the safe values:

```text
ALERT_DELIVERY_DRY_RUN=true
ALPHALAB_ALLOW_REAL_NOTIFICATION_TESTS=false
ALERT_SMS_ENABLED=false
```

Then restart and confirm the safe posture, and remove any `.env` backup:

```bash
./ops restart --yes
./ops safety-status
```

Expected: `ALPHALAB_SCHEDULER_MODE=dry_run`, automation paper trading
`armed=false`, scheduler paper jobs `enabled=false`, safe stabilization mode
`true`.

## 3. What must NEVER change during notification testing

- Scheduler mode — `ALPHALAB_SCHEDULER_MODE` stays `dry_run`.
- Paper-trading arming / scheduler paper jobs — stay disarmed/disabled.
- Alpaca settings and endpoints — paper-only; never touched here.
- Live-trading flags (`ALPHALAB_ALLOW_LIVE_EXECUTION`) — never flipped for a
  notification test.
- SMS — `ALERT_SMS_ENABLED` stays `false`.
- LaunchAgent plists, the database file, and `.env` secrets — never edited as
  part of a notification test (only the three notification flags above, and only
  transiently).

The only transient changes for a supervised test are the three notification env
flags in section 1, reverted in section 2. Everything else is out of scope.
