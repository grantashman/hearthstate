# Briefing scheduler

The first scheduler slice runs the existing morning briefing composer once per day for Grant in the account-backed `home` household. It enforces the 07:00–21:00 quiet window and claims the `(viewer, briefing type, local date)` dedupe key before returning output, so concurrent scheduler invocations cannot emit the same briefing twice.

The current transport boundary is journald: the service renders the message and exits. Photon/iMessage or another delivery transport can be added around `run_briefing()` without moving scheduling or dedupe logic into the transport layer.

## Install the user timer

From the Hearthstate repository:

```bash
install -m 0644 deploy/systemd/hearthstate-briefing.service ~/.config/systemd/user/hearthstate-briefing.service
install -m 0644 deploy/systemd/hearthstate-briefing.timer ~/.config/systemd/user/hearthstate-briefing.timer
systemctl --user daemon-reload
systemctl --user enable --now hearthstate-briefing.timer
```

Run one production-style invocation manually:

```bash
systemctl --user start hearthstate-briefing.service
journalctl --user -u hearthstate-briefing.service -n 20 --no-pager
```

The timer uses the host's `Australia/Sydney` timezone through `TZ` and is persistent, so a missed run is caught up after the user service returns. The service passes `--household-id home`, matching the account-backed dashboard's sibling `hearthstate.db.home` store. Do not run smoke tests against the production database with mutation commands.
