---
name: redeploy-service
description: Restart the smoke-monitor systemd service after a code/config change and confirm it's actually healthy — not just "active".
---

Use after a code/config change to this repo that's already on disk on the target host.

1. `sudo systemctl restart smoke-monitor`
2. `systemctl status smoke-monitor --no-pager` — confirm the state is `active (running)`, not just that the restart command returned exit 0.
3. `journalctl -u smoke-monitor -n 30 --no-pager` — actually read the startup log lines for errors/exceptions; don't just check that the tail exists.
4. If the service has an ntfy/heartbeat check, confirm one fired after the restart before calling this done.

## Reporting

Report pass/fail per step individually — "restarted successfully" alone is not enough; state explicitly that the service is running AND that the logs are clean AND (if applicable) that a heartbeat was seen.
