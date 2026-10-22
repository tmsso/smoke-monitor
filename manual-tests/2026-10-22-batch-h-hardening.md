# Manual test sheet — Batch H hardening (2026-10-22)

Covers what pytest and CI can't: the deployed service, the real phone, the
real alarm, wall-clock behaviour, and the sudo-installed unit. Everything
else is covered by `pytest tests/` (106 tests, also in CI) and the PR notes
for #18–#28. Report results by case ID.

Prereq for all cases: the Batch H chain is merged and deployed —
`git pull --ff-only` in the live checkout, then
`sudo systemctl restart smoke-monitor`.

When reading the journal, never paste raw output anywhere public: older
lines (before H-6 was deployed) contain the ntfy topic.

---

## DEP — deploy

**DEP-1 — clean start on the new code**
1. `systemctl status smoke-monitor --no-pager | head -3` → `active (running)`, recent start time.
2. `journalctl -u smoke-monitor -n 20 --no-pager` → `Starting smoke monitor`, `Listening on …`, no traceback.

**DEP-2 — topic no longer logged (H-6)**
1. After the next heartbeat (or `--notify`), run
   `journalctl -u smoke-monitor --since "<deploy time>" --no-pager | grep -c "HTTP Request"`.
2. **Expect:** `0`.

## HB — heartbeat (H-4)

**HB-1 — first heartbeat carries real stats**
1. Wait for the next 09:00.
2. **Expect** on the phone: "Smoke Monitor OK", body names the mic and a
   non-zero "windows analysed" count; it arrives at 09:00 (± a few seconds).

**HB-2 — DST change (Budapest falls back Sun 2026-10-25)**
1. Check the heartbeats on Sun 10-25 and Mon 10-26.
2. **Expect:** both at 09:00 local, not 08:00 or 10:00.

**HB-3 — degraded heartbeat (optional)**
1. Mute the mic (`alsamixer` capture mute), set `heartbeat_time` to 2 minutes
   from now, restart.
2. **Expect:** "Smoke Monitor DEGRADED … mic delivers pure silence"
   at default priority. Unmute and restore `heartbeat_time` afterwards.

## AL — alert path (H-1, H-2, H-8)

**AL-1 — the real alarm confirms (H-8; pairs with owner step O-3)**
1. Service running, `[recording] enabled = true` (see SVC-1 for the dir).
2. Press the smoke alarm's test button and hold it for the full cycle.
3. **Expect:** an urgent "SMOKE ALARM" push within ~10 s; a `*-hit.wav` in
   `recordings/`. Then `python monitor.py --replay recordings/<file>.wav`
   prints "alarm would have fired".

**AL-2 — alert survives a network outage (H-2)**
1. Turn the laptop's network off.
2. Trigger a detection (alarm test button, or a phone playing a 3.2 kHz tone
   next to the mic for ~10 s).
3. Journal shows `Smoke alert not delivered — retry 1 in 5s`, then 10s, 20s…
4. Turn the network back on within ~2 minutes.
5. **Expect:** exactly **one** urgent push arrives after the network returns.

**AL-3 — alarm right after boot is sent (H-1)**
1. Reboot. Within 5 minutes of the service starting, trigger a detection.
2. **Expect:** the urgent push arrives (before H-1 it was silently dropped as "in cooldown").

## SVC — hardened unit (H-11, needs sudo)

**SVC-1 — install and record under the sandbox**
1. `mkdir -p recordings && chmod 700 recordings`
2. Check `User=` in `smoke-monitor.service`.
3. `sudo cp smoke-monitor.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart smoke-monitor`
4. **Expect:** `Listening on …` in the journal.
5. Run AL-1 (or any detection with recording on). **Expect:** the clip is
   written (`ls -l recordings/` shows `-rw-------`), no "Read-only file system" error.

**SVC-2 — clean exit is restarted (Restart=always)**
1. `sudo systemctl kill -s SIGINT smoke-monitor` (simulates a clean exit).
2. **Expect:** the journal shows "Stopped by user", then a fresh `Starting smoke monitor` ~10 s later.

## HC — dead-man's switch (H-13, only if you set it up)

**HC-1 — pings keep the check green**
1. Create the check (README "Dead-man's switch"), put `HEALTHCHECK_URL` in `.env`, restart.
2. **Expect:** journal `Health check pings enabled every 300s`; the check turns green within 5 min.

**HC-2 — a dead monitor alerts**
1. `sudo systemctl stop smoke-monitor`.
2. **Expect:** the health-check service alerts your phone after period + grace.
3. `sudo systemctl start smoke-monitor`; the check recovers.
