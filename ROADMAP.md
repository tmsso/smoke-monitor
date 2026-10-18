# Roadmap

Work is organized into batches. Each batch is independently developable and
ordered by priority — pick up the topmost unfinished batch and implement it
completely before moving on. The heavy sound-understanding work is
deliberately last: everything before it is small, well-specified, and should
be finished first.

Items are written to be implementable as-is: they name the files to touch,
the config keys to add, and what "done" looks like. Current code layout:

| File | What lives there |
|---|---|
| `monitor.py` | CLI, `run()`: supervised audio stream, `process_loop`, power + heartbeat threads |
| `detector.py` | `SmokeDetector`; `analyze_window()` → `WindowMetrics` (stateful — call it **or** `process_window`, never both per window) |
| `audio_devices.py` | pure device-selection fns (`select_input_device`, `better_device`, `diagnose_stream`, `describe_device`) |
| `notifier.py` | `Notifier.send()` — ntfy push (currently fire-and-forget, swallows errors) |
| `recorder.py` | event recorder + rolling pre-buffer (filled only when `[recording] enabled`) |
| `dashboard.py` / `replay.py` / `tone.py` | `--dashboard`, `--replay`, `--play-tone` |
| `tests/` | pytest (`.venv/bin/python -m pytest -q`, ~40 s); no CI yet (H-10) |
| `manual-tests/` | dated physical-check sheets with stable case IDs |
| `config.toml` / `README.md` | all settings / keep in sync with every user-facing change |

## How to run a batch (long-batch runs at medium effort)

The batches below are specified so an unattended run can execute them without
re-deriving design: each item names files, config keys, and a **done-check
that is a runnable command or test**. Conventions:

- One item per PR, branched off a fresh `origin/main` (check local `main` is
  not ahead of origin first). Every new config key defaults to today's
  behavior.
- Offline-verifiable first: pure functions + pytest with fakes
  (`httpx.MockTransport` for ntfy, synthetic signals from `tone.build_t3`,
  injected device lists). Whatever needs a real mic, speaker, phone or the
  real alarm goes onto a new `manual-tests/` sheet — never claimed as verified.
- Keep `process_loop` non-blocking: no network I/O or retries on the audio
  processing thread (it has a 16-window ≈ 8 s queue; anything slower drops
  audio).
- Never write a live ntfy topic, token, hostname or personal name into the
  repo, a commit or a PR — the repo is public.
- **Owner-only / confirm-first carve-outs** (stop and ask, even in a long
  run): anything needing `sudo` (service restart, unit-file install), changes
  to `.env` or the phone subscription, new external services/accounts, and
  any feature that lets a remote message control the microphone (Batch 2
  listen-in) — those PRs are built and verified but merged only on explicit
  owner approval.

## Owner-only steps (do these before the next long-batch run)

- **O-1 Deploy what's merged.** The service has run unchanged since
  2026-07-13; nothing since Batch 1 is live. `git pull` →
  `.venv/bin/pip install -r requirements.txt` →
  `sudo systemctl restart smoke-monitor` → read `journalctl -u
  smoke-monitor -n 40`. Expect new behavior after deploy: low-priority
  "Mic offline/online/switched" pushes from hotplug handling.
- **O-2 Run the Batch 1 manual sheet**
  (`manual-tests/2026-09-04-batch1-mic-support.md`).
- **O-3 Record the real alarm once.** Set `[recording] enabled = true`,
  press the alarm's test button, keep the WAV locally (never commit it).
  It is the ground truth for D-1 and Batch 3 — every detection-tuning
  claim so far rests on synthetic signals.
- **O-4 Use a high-entropy ntfy topic.** ntfy.sh topics are
  unauthenticated: the topic name is the only secret, and anyone who knows
  it can read alerts *and* publish fake ones. Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(18))"`, never
  derive it from the hostname or project name, update `.env` and the phone
  subscription. Required before Batch 2 (which would put room audio on
  that topic). Also `chmod 600 .env`.

## Decisions needed (recommended default in **bold**)

- **D-1 Confirmation rule vs. T3 cadence** (H-8). The 5-of-8 rule misses a
  T3 alarm depending on how the beeps line up with the 0.5 s windows.
  Choose: **`confirm_windows = 5`, `confirm_out_of = 16`** / 6-of-16 /
  keep 5-of-8 and wait for Batch 3. Evidence in H-8.
- **D-2 External dead-man's switch** (H-13). Today, a dead laptop or a
  hung process is only noticed by the *absence* of the daily heartbeat.
  **Build the optional ping code (off unless an env var is set); the owner
  decides whether to create a free healthchecks.io-style check.**
- **D-3 GitHub Actions CI** running pytest on PRs (H-10). **Yes.**
- **D-4 Run as a systemd *user* service** (`systemctl --user`, needs a
  one-time `loginctl enable-linger`). Removes `sudo` from redeploys, which
  also means agent sessions could restart the service themselves — a new
  autonomous capability. **Keep the system unit for now**; revisit if
  manual redeploys keep lagging (see O-1).
- **D-5 Listen-in security bar** (Batch 2). **Ship listen-in only with all
  of: H-7 token support, a separate high-entropy command topic, a rate
  limit, and a visible audit notification for every request.**

## Completed

- ~~**Heartbeat notification**~~ — periodic "still alive" ping with configurable interval and first-fire time
- ~~**Power loss alert**~~ — notify when AC power is lost, with configurable cooldown
- ~~**Startup-on-battery alert**~~ — notify immediately if the service starts while on battery
- ~~**Test notification flag**~~ (`--notify`) — send a test push and exit
- ~~**Testing mode**~~ (`--test`) — notify on first detection event, skipping the confirmation window

---

## Batch 1 — External mic support & interactive testing

Goal: make hardware setup and detector tuning painless. Today, verifying a
config change means setting off the real alarm — it's loud and drains its
battery. After this batch, tuning happens on screen with recorded or
synthetic audio, and swapping in a USB mic requires no config surgery.

Status: **code complete — NOT yet deployed or hardware-checked.** All items
are implemented and merged (PRs #3–#5, #11–#13, #15) with passing unit +
functional tests, but:
1. **Not live.** The `smoke-monitor` service has been running since
   2026-07-13 and predates every Batch 1 merge. Deploy: `git pull` →
   `.venv/bin/pip install -r requirements.txt` (rich, new in #11) →
   `sudo systemctl restart smoke-monitor` → check `journalctl`. (The
   sessions that built this could not run `sudo`.)
2. **Physical checks pending.** USB-mic swap, speaker→mic coupling, and the
   dashboard meter under a real 3.2 kHz source are offline-verified only
   (injected-fake unit tests + functional passes); run
   `manual-tests/2026-09-04-batch1-mic-support.md` (`DP/HP/PT/DASH/REC/RP`).

Do both before treating Batch 2 as started.

- ~~**Device priority list**~~ — *done (PR #3).* In `config.toml [audio]`, add
  `device_priority = []`: an ordered list of device name substrings or
  integer indices. On startup, enumerate `sounddevice.query_devices()`
  input devices and pick the first match; log the chosen device name and
  index. Empty list (or absent key) keeps today's behavior: the existing
  single `device` setting, else system default. Case-insensitive substring
  match against device names.
  *Done when:* with a USB mic listed first and plugged in it is chosen;
  unplugged, the next entry (or default) is chosen; choice is logged.
- ~~**Hotplug handling**~~ — *done (PR #4).* Detect that the active input device has gone away:
  (a) `sd.InputStream` raises/aborts, or (b) `hotplug_silence_seconds`
  (default 60, `[audio]`) of consecutive zero-energy windows. On loss:
  close the stream, re-enumerate every 5 s, reopen on the best available
  device per the priority list. Also re-check the priority list every
  `device_poll_seconds` (default 30) so plugging in a *higher-priority*
  mic while running switches over seamlessly. Send a low-priority ntfy
  notification on every switch/loss/recovery (reuse `Notifier.send` with
  `priority="low"`). Restructure `run()` in `monitor.py` so the stream
  lives in a supervised loop rather than a single `with` block.
  This subsumes the old "microphone disconnect detection" item.
  *Done when:* yanking the USB mic mid-run recovers to the internal mic
  without a restart and sends one notification; replugging switches back.
- ~~**Live tuning dashboard**~~ (`--dashboard`) — *done (PR #11).* A terminal UI (use `rich`;
  must work over SSH) refreshed per window showing: band energy ratio as
  a meter with the threshold marked, dominant frequency (Hz), hit/miss
  verdict, rolling confirmation state (e.g. `3/8, need 5`), active input
  device, and overflow count. Implement by having
  `SmokeDetector.process_window` return (or expose via a small dataclass)
  the per-window metrics it already computes instead of a bare bool —
  keep the bool API for callers via a thin wrapper if simpler.
  *Done when:* running `--dashboard` next to a phone playing a 3.2 kHz
  tone visibly moves the meter past the threshold and counts hits.
  (`analyze_window` → `WindowMetrics`; render tested; meter-past-threshold
  under a real tone is manual-sheet `DASH-1`.)
- ~~**Synthetic alarm tone**~~ (`--play-tone`) — *done (PR #5).* Play an alarm-like beep
  pattern through the speakers via `sounddevice.play`: default 3200 Hz
  square-ish tone in T3 cadence (3 × 0.5 s beeps with 0.5 s gaps, 1.5 s
  pause, repeat) for 15 s. Flags/config: frequency and duration
  (`--play-tone [seconds]`, `tone_hz` in `[detection]` is *not* reused —
  keep the tone generator self-contained with CLI options only). Exits
  after playing; run it in a second terminal against `--dashboard` or
  `--test` for end-to-end verification without the real alarm.
  *Done when:* `--play-tone` in one terminal drives `--test` mode in
  another to a detection through the actual mic.
- ~~**Event recorder**~~ — *done (PR #12).* New `[recording]` config section:
  `enabled = false`, `dir = "recordings"`, `max_files = 50`,
  `pre_seconds = 5`, `post_seconds = 10`. When enabled, keep a rolling
  pre-buffer (see Batch 2 — implement the buffer here, Batch 2 reuses it)
  and write a mono 16 kHz WAV around every *hit* and *near-miss* (Batch 2
  defines near-miss; until then, record hits only). Filenames
  `YYYYmmdd-HHMMSS-{hit|nearmiss}.wav`; delete oldest beyond `max_files`.
  Use the stdlib `wave` module.
  *Done when:* a detection produces a WAV containing audio from before
  the trigger, and the directory never exceeds `max_files`.
  (Buffer sized for `pre_seconds` only — Batch 2 resizes it to
  `listen_in_seconds` and decouples the fill from `enabled`. One file per
  event, not per window: capture re-arms only after confirmation drops.)
- ~~**Replay mode**~~ (`--replay path.wav`) — *done (PR #13).* Run the detector offline over a
  WAV file (resample not required; reject files whose sample rate differs
  from `[audio] sample_rate` with a clear error). Print one line per
  window: time offset, band ratio, dominant frequency, hit/miss, and
  final verdict ("alarm would have fired at t=3.5s" or "no alarm").
  No audio stream, no notifications.
  *Done when:* replaying a recorded alarm event reproduces the detection
  and replaying ambient noise does not; threshold changes in
  `config.toml` visibly change the outcome. (Fully offline-verified.)

## Batch H — Reliability & privacy hardening (do next, before Batch 2)

Goal: make the alert path trustworthy before adding features on top of it.
Sources: a code review and the service journal for 2026-07-13 → 2026-10-18
(97 days: 0 alarms, 0 power events, 97/97 heartbeats delivered, 644
`input overflow` warnings, ~6/day spread evenly across all hours).
Suggested PR order: H-1, H-2, H-3, H-6/H-7 (one PR), H-4/H-5 (one PR),
H-8 (after D-1), H-9, H-12, H-10, H-13, H-11 last (owner installs it).

- **H-1 Cooldowns must start "never fired"** *(bug)*. `last_alert_time`
  and `last_power_alert_time` in `run()` start at `0.0` and are compared
  against `time.monotonic()`, which on Linux counts from boot. The service
  starts seconds after boot, so a smoke alarm in the first
  `cooldown_minutes` (10) after a reboot — and a power loss in the first
  30 — is logged "in cooldown" and **not sent**. Fix: start them as
  `None`; factor the check into `cooldown_elapsed(last, now, seconds)`.
  *Done when:* `pytest tests/test_cooldown.py` shows a confirmation at
  `monotonic() == 30.0` sends, and a second one inside the cooldown doesn't.
- **H-2 Reliable, non-blocking alert delivery.** Today
  `notifier.send()` runs on the audio-processing thread (10 s timeout,
  ≈ the 8 s queue → audio dropped mid-alarm), swallows every error, and
  `last_alert_time` is set *before* the send — so one network blip loses
  the smoke alert and suppresses retries for 10 minutes. Fix:
  `Notifier.send()` returns `bool`; new `AlertSender` (in `notifier.py`): a
  daemon thread + queue; `process_loop` only enqueues. Urgent smoke
  alerts retry with backoff (5, 10, 20, 40, 60, 60… s) for up to
  `cooldown_minutes`; while one is pending, further confirmations don't
  enqueue duplicates; the cooldown starts at *successful* delivery.
  Other kinds (power, mic, heartbeat) get one retry. Shut down cleanly via
  `stop_event`.
  *Done when:* a test with `httpx.MockTransport` failing twice then
  returning 200 delivers exactly one smoke push; the enqueue call returns
  in < 10 ms while the transport sleeps; all existing tests pass.
- **H-3 A crashed worker must not look healthy.** An exception in
  `process_loop` kills that daemon thread silently; the audio callback
  keeps stamping `last_window_ts`, so `diagnose_stream` says "ok" and the
  heartbeat says "running normally" while nothing is analyzed. Fix: wrap
  the per-window body in `try/except Exception: logger.exception(...)`;
  add `_Health.last_processed_ts`; the supervisor exits non-zero (systemd
  restarts it) if the worker is dead or `last_processed_ts` is older than
  `2 × STREAM_STALL_SECONDS` while windows still arrive.
  *Done when:* a test detector that raises on one window keeps processing
  the next; a test that kills the worker makes `run()` exit non-zero.
- **H-4 Honest heartbeat.** The heartbeat is the only daily liveness
  signal but says "running normally" unconditionally. Build it from a pure
  `heartbeat_status(stats) -> (title, message, priority, tags)`: device in
  use, windows processed, overflow count and peak band ratio since the
  last heartbeat, current silent/stall state, worker alive. Unhealthy →
  title "Smoke Monitor DEGRADED", `priority="default"`, tag `warning`.
  Also anchor the schedule to the wall clock (next = first + k ×
  interval) — observed drift: 09:00:08 → 09:01:26 over 97 days.
  *Done when:* unit tests cover healthy / muted / stalled / dead-worker
  stats; scheduling test shows no drift across simulated sends.
- **H-5 Aggregate overflow warnings.** The audio callback logs a WARNING
  per `input overflow` (644 lines in 97 days). Count overflows instead;
  log one INFO summary at most hourly when non-zero, feed the count to
  H-4. Other status flags still log immediately. (Root cause unknown —
  the evenly spread timing points away from daily load; memory pressure
  is an unverified hypothesis: the process sits ~83 MB in swap.)
  *Done when:* a test calling the callback with fake overflow statuses
  produces no per-call WARNING and one summary line.
- **H-6 Keep the topic out of the journal.** `httpx` logs the full request
  URL — including the secret topic — at INFO. Set
  `logging.getLogger("httpx").setLevel(logging.WARNING)` in `monitor.py`;
  `Notifier` logs its own line without the URL.
  *Done when:* a `caplog` test of a mocked send finds no topic string.
- **H-7 Optional ntfy access token.** `NTFY_TOKEN` env var → `Authorization:
  Bearer …` header on every request (send, and Batch 2's
  subscribe/upload). Commented entry in `.env.example`; README note on
  using it with an ntfy account or a self-hosted server with ACLs.
  *Done when:* MockTransport tests assert the header is present iff the
  env var is set.
- **H-8 T3-robust confirmation** *(needs D-1)*. A T3 alarm is 3 × 0.5 s
  beeps per 4 s cycle — 8 windows. When beeps align with window
  boundaries, only 3 of every 8 windows hit and 5-of-8 can never fire;
  nothing re-aligns them except clock jitter. Simulation (synthetic
  `tone.build_t3`, random phase, 200 trials, 30 s each):

  | Scenario | 5/8 (now) | 6/16 | 5/16 |
  |---|---|---|---|
  | exact T3 timing, noise σ 0.2 | 50 % | 100 % | 100 % |
  | ±10 % beep jitter, noise σ 0.2 | 98 % | 100 % | 100 % |
  | ±10 % jitter, 2 % dropped windows, noise σ 0.8 | 12 % | 100 % | 100 % |

  A 3 × 0.2 s beep burst peaks at 2 hits under every rule. The synthetic
  false-positive check (random 1 s in-band chunks) didn't discriminate
  between rules — validate on O-3's real recording. Worst-case floor at
  exact alignment is exactly 6/16, hence 5/16 recommended for margin.
  Implementation: config defaults + README "Tuning" text (the old "needs
  ~2.5 s of tone" becomes ~2.5 s within 8 s) + `tests/test_t3_confirmation.py`
  sweeping phase offsets 0–4 s (0.1 s steps) × noise {0, 0.2, 0.5}: must
  confirm within 20 s; the 3-beep burst and 60 s of noise must not.
  Note: a 16-window history means nothing can confirm in the first 8 s
  after start. Batch 3's `require_t3` stays the false-positive filter.
  *Done when:* that test passes and `--replay` of O-3's recording fires.
- **H-9 Survive a stream that fails to start.** `open_stream()` failures
  are retried, but an exception from `stream.start()` (the `with stream:`
  entry) escapes `supervise_stream` and kills the process. Treat it like
  an open failure (log, low-priority notify once, retry).
  *Done when:* a test with a fake stream whose `__enter__` raises once
  shows the supervisor retrying and then listening.
- **H-10 CI** *(needs D-3)*. `.github/workflows/test.yml`: on push/PR,
  ubuntu-latest, Python 3.14 (matches the venv),
  `sudo apt-get install -y libportaudio2` (sounddevice imports fail
  without it), `pip install -r requirements-dev.txt`, `pytest -q`.
  *Done when:* the workflow is green on its own PR.
- **H-11 systemd unit hardening** *(owner installs, sudo)*. In
  `smoke-monitor.service`: `Restart=always` (a clean exit of a safety
  monitor is still a failure), `NoNewPrivileges=yes`, `PrivateTmp=yes`,
  `ProtectSystem=strict`, `ProtectHome=read-only`,
  `ReadWritePaths=-%h/git/smoke-monitor/recordings` (create the dir before
  installing — with a read-only home the service can't create it). Add a
  README note that `User=` must be edited to the local account.
  *Done when:* the owner reinstalls the unit and the journal shows
  "Listening on …" plus a recorded test clip — add a manual-sheet case.
- **H-12 Recordings are private.** Create the recordings dir `0o700` and
  write WAVs `0o600` (room audio). *Done when:* a recorder test asserts
  the modes.
- **H-13 Dead-man's-switch ping** *(needs D-2)*. If `HEALTHCHECK_URL` is
  set, GET it every `healthcheck_interval_minutes` (default 5,
  `[notification]`) — only while H-4's stats say healthy — via the H-2
  sender. Unset → feature off, no network calls. README: how to set up the
  external check and its own phone alert.
  *Done when:* MockTransport tests show pings while healthy, none while
  degraded or unset.

## Batch 2 — Listen-in on ambiguous signals

Goal: when the detector isn't sure — or the human isn't — deliver the
actual audio to the phone instead of forcing a guess.

Prerequisites: H-2 (attachments go through the sender thread), H-7, O-4,
and D-1 decided (the near-miss definition depends on the history length).

- **Rolling pre-buffer** — move the deque out of `Recorder` into a small
  `RollingBuffer` (`recorder.py`) owned by `process_loop`, capacity
  `max(pre_seconds, listen_in_seconds)` (`[notification]
  listen_in_seconds = 10`), filled whenever recording, attachments **or**
  listen-in are enabled — today it fills only when `[recording] enabled`,
  so listen-in would return nothing. 10 s at 16 kHz float32 ≈ 640 KB.
  *Done when:* recorder tests still pass and a new test shows the buffer
  fills with recording off but listen-in on.
- **Near-miss definition** — in `[detection]`, add
  `ambiguous_windows = 3`: an *ambiguous event* fires when the rolling
  history reaches `ambiguous_windows` hits out of `confirm_out_of` but
  fails to reach `confirm_windows` before the history clears (all-miss
  window run). Expose it as a `WindowMetrics.ambiguous` field set by
  `analyze_window` (don't run a second analysis pass — the detector is
  stateful). Startup error unless `ambiguous_windows < confirm_windows`.
  Emit at most one ambiguous event per
  `ambiguous_cooldown_minutes` (default 30, `[notification]`). Ambiguous
  events are logged, recorded (Batch 1 recorder, label `nearmiss`), and
  optionally notified — they never fire the urgent smoke alert.
  *Done when:* a `--replay`/pytest of a short 2-beep burst triggers an
  ambiguous event but not an alarm; a sustained alarm still fires the
  urgent alert.
- **Audio clip attachment** — extend `Notifier.send` with an optional
  `attachment: bytes` + `filename` parameter using ntfy's `PUT` file
  upload (`Filename` header; docs: docs.ntfy.sh/publish/#attachments).
  Encode clips as WAV (stdlib; keep clips ≤ 15 s at 16 kHz mono ≈ 480 KB,
  well under ntfy.sh limits — skip Opus, no new dependency). Config in
  `[notification]`: `attach_on_alert = false`, `attach_on_ambiguous =
  true`. On failure to upload, fall back to sending the plain text
  notification. Privacy: an attachment is fetchable by anyone who can
  read the topic (until the server expires it) — say so in the README
  next to the config keys.
  *Done when:* MockTransport tests show a `PUT` with `Filename` and WAV
  bytes, and a text fallback on 413/5xx; physical check (the phone plays
  the clip) goes on a manual sheet.
- **On-demand listen-in** *(confirm-first carve-out — merge only on
  explicit owner approval; PR title must say "remote listen-in")* —
  subscribe (long-poll `GET {ntfy_url}/{topic}/json` via httpx, in a
  daemon thread) to a *command* topic loaded from the
  `NTFY_COMMAND_TOPIC` env var (unset = feature off). On receiving a
  message whose body is `listen`, record `listen_in_seconds` of audio
  (pre-buffer + live) and send it back as an attachment on the main
  topic. Ignore unknown commands with a log line. Reconnect the
  subscription with backoff on network errors. Security (D-5), all
  required:
  - refuse to enable (startup error) if the command topic equals the main
    topic or is shorter than 16 characters;
  - send H-7's token on the subscription too;
  - process each message id once, and ignore messages older than 60 s
    (a reconnect must never replay a cached `listen`);
  - `listen_max_per_hour = 4`; excess requests are refused and logged;
  - every request — served or refused — logs a WARNING and posts a
    low-priority "Listen-in requested" notice on the main topic, so a
    misuse is visible;
  - README: off by default; tell household members the room can be
    sampled remotely.
  *Done when:* MockTransport tests cover serve / unknown command / stale
  message / rate limit / duplicate id; the physical round trip
  (publishing "listen" from the phone returns a clip of the room within
  ~listen_in_seconds + a few seconds) goes on a manual sheet.
- *(Stretch — skip unless asked)* **Live stream** — a local HTTP endpoint
  streaming mic audio for true real-time listening. Needs auth (shared
  token) since it exposes a live mic; only build if clip-on-demand proves
  too slow in practice.

## Batch 3 — Detection quality & calibration

- **Alarm profiles** — new `[[profiles]]` array-of-tables in
  `config.toml`, each with `name`, `freq_low_hz`, `freq_high_hz`,
  `energy_ratio_threshold`; plus `[detection] profile = ""` to select one
  by name (explicit `[detection]` keys win over the selected profile —
  document the precedence in a comment). Ship 2–3 presets for common
  detector families (standard 3.1–3.4 kHz ionization/photoelectric, plus
  a wider fallback). Unknown profile name → clear startup error.
  *Done when:* selecting a profile by name changes detection bounds
  without editing raw thresholds, verified via `--replay`.
- **Calibration mode** (`--calibrate [seconds]`, default 30) — record for
  N seconds while the user presses the alarm's *test button* once, then
  print: the top 5 dominant frequency bands (200 Hz-wide bins) by peak
  energy ratio, and a suggested `freq_low_hz`, `freq_high_hz`, and
  `energy_ratio_threshold` (suggest threshold = 70% of the observed peak
  band ratio). Also write the recording to the recordings dir (if
  enabled) so it can be replayed later. No notifications.
  *Done when:* running it against `--play-tone` suggests a band
  containing 3200 Hz.
- **Temporal pattern matching** — smoke alarms beep in a T3 pattern
  (3 beeps ~0.5 s each, ~1.5 s pause). Add an optional second stage in
  `SmokeDetector`: track the on/off sequence of band-hits over the last
  ~8 s and require a beep–gap alternation consistent with T3 before
  confirming (`[detection] require_t3 = false`). Steady tones (kettle,
  appliance beep) hold the band continuously and must *not* match. Keep
  the implementation simple: count on→off transitions in the window and
  require ≥ 3 with plausible durations; do not build a full matcher.
  Builds on H-8 (which makes plain confirmation phase-robust); this stage
  is purely a false-positive filter, so measure it against O-3's real
  recording as well as `--play-tone` output.
  *Done when:* with `require_t3 = true`, `--replay` on a steady-tone
  recording reports no alarm, and a T3-cadence recording (from
  `--play-tone`) still fires.

## Batch 4 — Power monitoring

Existing pattern to follow: `power_monitor_loop` in `monitor.py` reads
`/sys/class/power_supply/AC/online`; battery state lives in
`/sys/class/power_supply/BAT0/capacity` (integer percent) — handle `BAT1`
as fallback and absence gracefully (log once, disable feature).

- **Low battery alert** — in the power loop, when on battery, check
  capacity each cycle. Notify at `low_battery_percent` (default 20,
  `[notification]`) with `priority="high"`, and again at 10% and 5% with
  `priority="urgent"` (hardcoded escalation steps are fine). At most one
  notification per threshold crossing per discharge (reset the sent-flags
  when AC returns).
  *Done when:* simulated capacity values (factor the read into a small
  function so a test/replay can inject values) produce exactly three
  escalating notifications on the way down and none on repeat reads.
- *(Host check 2026-10-18: `/sys/class/power_supply/` has `AC` and
  `BAT0`. The boot-time power-cooldown bug is H-1.)*
- **AC restored notification** — when `previous_ac` transitions
  False → True, send a low-priority "AC power restored" notification
  (tags `electric_plug,white_check_mark`). No cooldown needed — the
  power-loss cooldown already limits flapping pairs; but suppress the
  restored message if no loss alert was sent this session.
  *Done when:* a loss/restore cycle produces exactly two notifications in
  order.

## Batch 5 — Notification plumbing

Builds on H-2's `AlertSender` (every send already goes through it) and
H-7's token; a per-kind `token_env` key belongs next to `topic_env`.

- **Configurable priority and tags** — new `[notification.style]` tables:
  `smoke`, `power`, `heartbeat`, `device` (Batch 1 uses this), `analysis`
  (Batch 6 uses this), each with optional `priority` and `tags` keys that
  override the current hardcoded defaults. `Notifier` gains a
  `send(kind="smoke", ...)` parameter that looks up the style; explicit
  `priority`/`tags` arguments still win. Defaults must exactly match
  today's behavior when the section is absent.
- **Multiple topics** — allow per-kind topic override in the same
  `[notification.style]` tables (`topic` key, or `topic_env` naming an
  env var, preferred so topics stay out of the repo). Unset kinds fall
  back to the main topic. Document the phone-side benefit in README:
  different notification sounds/priority per severity.
  *Done when:* smoke alerts and heartbeats can land on two different
  topics with different priorities purely via config.

## Batch 6 — Sound understanding: narrative guesses for unusual noise

Deliberately last: this is the heaviest batch — ship everything above
first. Goal: when something unusual is heard, send a plain-language guess
of what it probably was ("repetitive metallic clicking, likely the gas
heater igniter") instead of just a frequency-band statistic.

Hardware reality check: this runs on a ThinkPad X220 (2-core Sandy Bridge
i5, 4 GB RAM, AVX but no AVX2). Measured 2026-10-18: ~2.6 GB available,
~1 GB of swap already in use host-wide — budget the local-LLM path against
that, not against the nominal 4 GB. A true audio-multimodal LLM (Qwen2-Audio
class, 7B+) does not fit. The workable design is a **two-stage pipeline**
— local classifier for *hearing*, then either a tiny local LLM or an
online LLM (OpenRouter) for *narration*. All of it must be strictly lower
priority (nice, single thread) than the detection loop, which must never
be starved. Implement in the order below; each step is shippable alone.

- **Unusual-noise trigger** — new `[analysis]` section, `enabled = false`
  (master switch, off by default). Wake the analyzer on: (a) ambiguous
  events from Batch 2, and (b) a loudness anomaly — RMS Z-score over a
  rolling baseline (e.g. 10-minute exponential moving average/variance)
  exceeding `anomaly_zscore = 4.0` for `anomaly_windows = 6` consecutive
  windows. Compute RMS in the existing processing thread (cheap); the
  analyzer itself runs in its own thread. Rate-limit with
  `analysis_cooldown_minutes = 30`. Never trigger during an active smoke
  alert or its cooldown.
- **Stage 1: audio event classifier** — run YAMNet (TFLite runtime
  `ai-edge-litert`/`tflite-runtime`, model ~4 MB, 521 AudioSet classes,
  16 kHz mono input — matches our capture format) over the buffered clip
  (pre-buffer + a few live seconds). Output top-k labels with scores
  (e.g. `Water tap 0.6, Hiss 0.3`). Wrap it behind a small
  `AudioClassifier` class (own file, `classifier.py`) so the model is
  swappable. Model file path in `[analysis] classifier_model_path`;
  download instructions in README (do not commit the model). Classifier-
  only mode is already useful: `narration = "off"` sends the raw labels
  as a normal-priority notification with the clip attached.
- **Stage 2: narration** — `[analysis] narration = "off" | "local" |
  "openrouter"`. Build the prompt from: classifier labels + scores,
  trigger stats (duration, RMS, dominant band), local time of day, and
  the `[surroundings]` description below. Ask for a 1–2 sentence guess;
  send it via `Notifier` (kind `analysis`, clip attached).
  - **`local`** — tiny instruct model via `llama-cpp-python` (llama.cpp
    runs on AVX-only CPUs). Target Qwen2.5-0.5B-Instruct Q4_K_M
    (~400 MB RAM); `[analysis.local] model_path`, `threads = 2`,
    `max_tokens = 120`. Lazy-load on first trigger, unload after
    `idle_unload_minutes = 10`, hard cap of one analysis at a time —
    skip (with a log line) rather than queue if one is running.
  - **`openrouter`** — POST to
    `https://openrouter.ai/api/v1/chat/completions` with httpx (OpenAI-
    compatible schema; no SDK dependency needed). API key from
    `OPENROUTER_API_KEY` env var (add to `.env.example`), model id in
    `[analysis.openrouter] model` (default a cheap small model, e.g.
    `anthropic/claude-haiku-4-5`), `max_tokens = 120`, `timeout = 20`.
    Text-only: send labels + stats, never audio. The `[surroundings]`
    description and time of day also leave the machine — say so in the
    README next to the setting. Pick a current cheap model id at
    implementation time; the one above is only an example.
    **Overuse guardrails (client-side):** `max_calls_per_day = 10` and
    `max_calls_per_hour = 3` enforced with persisted counters (small JSON
    state file in the working dir) so restarts don't reset them; when
    exhausted, fall back to classifier-only output and say so in the
    notification. On HTTP 402/429, back off for an hour and fall back
    likewise. **Server-side:** README note recommending a spend limit /
    provisioned key credit cap in the OpenRouter dashboard as the
    backstop.
- **`[surroundings]` config section** — `description = ""`: free-text
  description of the laptop's acoustic environment, e.g. `"kitchen
  counter; fridge 2 m away hums and clicks when the compressor cycles;
  gas heater with piezo igniter in the corner; water pipes in the wall
  gurgle after flushing"`. Optionally `[[surroundings.sources]]` entries
  with `name` and `sounds_like` for structured hints. Entirely optional —
  narration degrades gracefully to labels-only grounding when empty.
- **Resource guardrails** (applies to the whole batch) — analyzer thread
  runs at `os.nice(10)`; classifier and LLM limited to 1–2 threads;
  models lazy-loaded and unloaded when idle; one analysis at a time;
  never analyze during an active smoke alert. Detection latency must be
  unaffected — verify with the Batch 1 dashboard while an analysis runs.

## Ideas (unscheduled)

Not committed to; promote into a batch with a done-check before building.

- **End-to-end self-test reminder** — a monthly low-priority push asking
  the owner to press the alarm's test button within 10 minutes; the
  monitor reports "heard it ✓ (ratio, Hz)" or "did NOT hear it ✗". The only
  check that covers the real alarm → mic → detector → phone chain;
  everything else is synthetic.
- **Investigate input overflows** — ~6/day (H-5 makes them countable).
  Try a larger `blocksize`/explicit `latency` seconds, and correlate with
  swap activity before changing anything.
- **Pin dependencies** — `requirements.txt` uses `>=` only; a lock file
  (pip-tools) would make a redeploy reproducible. Low priority while the
  venv is long-lived.
- **Battery health in the heartbeat** — capacity % and charge cycles
  from `BAT0` (pairs with Batch 4).
- **Systemd user service** — if D-4 is declined now but redeploys keep
  lagging.
