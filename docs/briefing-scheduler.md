# Briefing scheduler and delivery

The scheduler runs the morning briefing once per day for Grant in the account-backed `home` household. It now delivers through the verified AgentMail inbox rather than writing briefing contents to a local file.

The delivery path is deliberately split into four boundaries:

1. `compose_briefing()` builds a privacy-filtered preview without claiming delivery.
2. `PlannerStore` stores per-member notification preferences and a unique delivery record for `(viewer, briefing type, local date)`.
3. `deliver_briefing()` checks enabled state, preferred time, and quiet hours, then claims a short lease atomically before calling the transport.
4. `send_briefing_email()` adapts the claimed message to AgentMail; success, provider ID, bounded failure status, attempt count, and retry time are persisted.

Concurrent workers cannot both claim the same delivery record. Provider failures are recorded without storing raw exception text; attempts retry after five minutes up to three total attempts. A process crash after an external provider accepts a message and before Hearthstate records `sent` remains an unavoidable at-least-once boundary; the short claim lease prevents concurrent duplicates while making abandoned claims retryable.

## Notification defaults

Each `(viewer, briefing type)` gets these defaults on first use:

- enabled: `true`
- preferred time: `07:30`
- quiet window: `21:00` through `07:00`
- channel: `email`

The current store API is:

```python
store.get_notification_preferences("grant")
store.set_notification_preferences(
    "grant",
    enabled=True,
    preferred_time="07:30",
    quiet_start="21:00",
    quiet_end="07:00",
    updated_by="grant",
)
```

Authenticated dashboard members can read and update their own morning preferences through `GET`/`POST /api/notifications/preferences`. The API derives the viewer from the session and rejects spoofed actor fields; it does not yet include a dedicated settings page.

Only the email channel is enabled in this slice. Photon/iMessage and push remain separate future adapters.

## Production service

The service resolves the viewer's email from the account database and uses the AgentMail secrets outside the repository:

- `/home/ubuntu/.hermes/secret/agentmail_api_key`
- `/home/ubuntu/.hermes/secret/agentmail_inbox_id`

The service command is:

```bash
python3 -m hearthstate.briefing_delivery \
  --database /home/ubuntu/workspace/hearthstate/hearthstate.db \
  --accounts-database /home/ubuntu/workspace/hearthstate/hearthstate-accounts.db \
  --household-id home \
  --viewer grant \
  --briefing-type morning \
  --agentmail
```

Briefing contents are not printed to stdout or written to journald. The service emits only sanitized JSON status; errors remain journal-visible. AgentMail request failures never expose the API key or raw provider exception to the delivery record.

## Install or update the user timer

From the Hearthstate repository:

```bash
install -m 0644 deploy/systemd/hearthstate-briefing.service ~/.config/systemd/user/hearthstate-briefing.service
install -m 0644 deploy/systemd/hearthstate-briefing.timer ~/.config/systemd/user/hearthstate-briefing.timer
systemctl --user daemon-reload
systemctl --user enable --now hearthstate-briefing.timer
```

Run one production-style invocation manually only when an actual email delivery is intended:

```bash
systemctl --user start hearthstate-briefing.service
journalctl --user -u hearthstate-briefing.service -n 20 --no-pager
```

The timer is explicitly pinned to `Australia/Sydney` and is persistent, so a missed run is caught up after the user service returns. It runs daily at `07:30` local time. The service passes `--household-id home`, matching the account-backed dashboard's sibling `hearthstate.db.home` store.

Inspect delivery state without exposing briefing text:

```bash
python3 - <<'PY'
from hearthstate.store import PlannerStore
store = PlannerStore('/home/ubuntu/workspace/hearthstate/hearthstate.db', household_id='home')
print(store.get_notification_preferences('grant'))
print(store.get_briefing_delivery('grant', 'morning', 'YYYY-MM-DD'))
store.close()
PY
```

Do not run smoke tests against the production database with mutation commands. Use a temporary planner and account database for delivery tests.
