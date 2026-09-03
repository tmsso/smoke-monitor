# Manual test sheet — Batch 1 mic support (2026-09-04)

Covers the physical / acoustic checks that can't be automated on the deploy
host (no USB mic attached; headless/quiet — speaker→mic coupling untested).
Everything else is covered by `pytest tests/` and the notes in PRs #3–#5.

Run from the repo root with the venv active and the service **stopped** for the
mic tests (`sudo systemctl stop smoke-monitor`), then restart it afterwards
(`sudo systemctl start smoke-monitor`). Report results by case ID.

Prereqs: a USB microphone you can plug/unplug; a phone or second device that
can play a ~3.2 kHz tone (or use `--play-tone` on this machine's speakers).

---

## DP — device_priority selection (PR #3)

**DP-1 — USB mic listed first, plugged in → chosen**
1. Plug in the USB mic. Confirm it appears in
   `python -c "import sounddevice; print(sounddevice.query_devices())"` and note its
   name substring (e.g. `USB`).
2. Set in `config.toml [audio]`: `device_priority = ["USB", "default"]`.
3. `python monitor.py --config config.toml` (or start the service).
4. **Expect:** startup log line `Selected input device <N>: <USB mic name> (matched device_priority)`
   and `Starting smoke monitor | device=<N>: <USB mic name>`.

**DP-2 — USB mic unplugged → next entry / default chosen**
1. Same config as DP-1, USB mic **unplugged**.
2. Start the monitor.
3. **Expect:** warning `No device_priority entry [...] matched an input device — falling back to ...`
   *only if* no later entry matches; with `"default"` as entry 2, expect it to select the
   ALSA default instead, logged as the chosen device. No crash.

**DP-3 — empty list unchanged**
1. `device_priority = []`, `device = ""`.
2. Start. **Expect:** identical behaviour to before this batch — system default mic,
   `device=system default` in the startup line.

---

## HP — hotplug recovery & hot-swap (PR #4)

**HP-1 — yank the active mic mid-run → recovers**
1. `device_priority = ["USB", "default"]`, USB mic plugged in, start the monitor,
   confirm `Listening on <N>: <USB mic>`.
2. Physically unplug the USB mic.
3. **Expect within ~60 s (`hotplug_silence_seconds`) or ~5 s (full stall):**
   - log `Input device ... looks lost (stalled|silent) — reconnecting`
   - **exactly one** low-priority ntfy: "Smoke monitor lost its microphone …"
   - log `Listening on <M>: <fallback/default>` — detection continues on the internal mic
   - no restart of the process required

**HP-2 — replug a higher-priority mic → switches back**
1. Continue from HP-1 (running on the fallback mic). Note the device **index**
   in the current `Listening on <N>: …` line.
2. Plug the USB mic back in. Wait up to `device_poll_seconds` (30 s).
3. **Expect:**
   - log `Higher-priority input device available: <N> <USB mic> — switching`
   - **one** low-priority ntfy: "Smoke monitor switched microphone to …"
   - `Listening on <N>: <USB mic>` again
4. Record the fallback index from step 1 and the post-switch index here. ALSA can
   renumber devices when a USB device appears/disappears; `better_device` compares
   the integer index captured at open time, so a renumber could in theory cause a
   wrong target or a switch/switch-back loop. Watch for repeated "switching" lines.

**HP-3 — no spurious reconnects on a healthy mic**
1. Any single healthy mic, `device_priority` matching it. Start and leave for ~5 min.
2. **Expect:** no "lost" / "switched" / "recovered" log lines or notifications;
   just the initial `Listening on …`. (Automated proxy already run: 75 s on the ALSA
   default, zero spurious notifications.)

**HP-4 — clean shutdown**
1. While running under the supervised loop, press `Ctrl+C` (manual run) or
   `sudo systemctl stop smoke-monitor`.
2. **Expect:** `Stopped by user` (manual) and prompt exit, no traceback, no hung
   process.

---

## PT — --play-tone end-to-end (PR #5)

**PT-1 — tone drives --test through the real mic**
1. `sudo systemctl stop smoke-monitor`.
2. Terminal A: `python monitor.py --test --debug`
3. Terminal B: `python monitor.py --play-tone 20`  (or play a 3.2 kHz tone from a
   phone held near the mic)
4. **Expect (Terminal A):** `band ratio` rises well above `0.35` on the beeps and
   `ALARM DETECTED — sending notification` fires at least once; a test ntfy arrives.
   - If the laptop speakers are too quiet for coupling, use the phone method or
     hold the phone speaker to the mic.
5. `sudo systemctl start smoke-monitor` when done.

**PT-2 — tone options**
1. `python monitor.py --play-tone` → ~15 s of beeps, then `Tone finished`, exits.
2. `python monitor.py --play-tone 5 --tone-hz 2900` → ~5 s, lower pitch.
3. **Expect:** audible T3 pattern (beep-beep-beep … pause), process exits on its
   own, no notification sent.

---

## Notes / known gotchas

- On this host the internal analog capture is exposed through the ALSA `default` /
  `sysdefault` plug (index depends on enumeration), **not** the `CX20590 Analog`
  entry (which reports 0 input channels). `device_priority = ["default"]` also
  matches `sysdefault` (substring) — use an explicit index for a specific one.
- `--play-tone`'s T3 cadence drives `--test` (single-hit) but **not** a full
  non-`--test` run: 3 × 0.5 s beeps never fill 5 of 8 confirmation windows.
  Sustained-tone confirmation is a detector-tuning matter (Batch 3).
