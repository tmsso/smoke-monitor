# Roadmap

Work is organized into batches. Each batch is independently developable and
ordered by priority — pick up the topmost unfinished batch and implement it
completely before moving on. The heavy sound-understanding work is
deliberately last: everything before it is small, well-specified, and should
be finished first.

Items are written to be implementable as-is: they name the files to touch,
the config keys to add, and what "done" looks like. Current code layout:
`monitor.py` (audio stream, worker threads, CLI), `detector.py`
(`SmokeDetector`, FFT band-energy detection), `notifier.py` (`Notifier`,
ntfy push), `config.toml` (all settings), `README.md` (keep in sync when
adding user-facing features or config keys).

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

## Batch 2 — Listen-in on ambiguous signals

Goal: when the detector isn't sure — or the human isn't — deliver the
actual audio to the phone instead of forcing a guess.

- **Rolling pre-buffer** — a `collections.deque` of recent raw windows in
  the processing thread, sized by `[recording] pre_seconds` (shared with
  Batch 1's recorder; if Batch 1 shipped, this exists — just extend it to
  `listen_in_seconds` capacity, default 10).
- **Near-miss definition** — in `[detection]`, add
  `ambiguous_windows = 3`: an *ambiguous event* fires when the rolling
  history reaches `ambiguous_windows` hits out of `confirm_out_of` but
  fails to reach `confirm_windows` before the history clears (all-miss
  window run). Emit at most one ambiguous event per
  `ambiguous_cooldown_minutes` (default 30, `[notification]`). Ambiguous
  events are logged, recorded (Batch 1 recorder), and optionally notified
  — they never fire the urgent smoke alert.
  *Done when:* a short 2-beep burst triggers an ambiguous event but not
  an alarm; a sustained alarm still fires the urgent alert.
- **Audio clip attachment** — extend `Notifier.send` with an optional
  `attachment: bytes` + `filename` parameter using ntfy's `PUT` file
  upload (`Filename` header; docs: docs.ntfy.sh/publish/#attachments).
  Encode clips as WAV (stdlib; keep clips ≤ 15 s at 16 kHz mono ≈ 480 KB,
  well under ntfy.sh limits — skip Opus, no new dependency). Config in
  `[notification]`: `attach_on_alert = false`, `attach_on_ambiguous =
  true`. On failure to upload, fall back to sending the plain text
  notification.
  *Done when:* an ambiguous event's push notification plays the actual
  sound on the phone.
- **On-demand listen-in** — subscribe (long-poll `GET
  {ntfy_url}/{topic}/json` via httpx, in a daemon thread) to a *command*
  topic, `[notification] command_topic` (empty = feature off, loaded from
  `NTFY_COMMAND_TOPIC` env var like the main topic). On receiving a
  message whose body is `listen`, record `listen_in_seconds` of audio
  (pre-buffer + live) and send it back as an attachment on the main
  topic. Ignore unknown commands with a log line. Reconnect the
  subscription with backoff on network errors.
  *Done when:* publishing "listen" from the phone returns a clip of the
  room within ~listen_in_seconds + a few seconds.
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
- **AC restored notification** — when `previous_ac` transitions
  False → True, send a low-priority "AC power restored" notification
  (tags `electric_plug,white_check_mark`). No cooldown needed — the
  power-loss cooldown already limits flapping pairs; but suppress the
  restored message if no loss alert was sent this session.
  *Done when:* a loss/restore cycle produces exactly two notifications in
  order.

## Batch 5 — Notification plumbing

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
i5, 4 GB RAM, AVX but no AVX2). A true audio-multimodal LLM (Qwen2-Audio
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
    Text-only: send labels + stats, never audio.
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
