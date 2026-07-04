# Roadmap

Work is organized into batches. Each batch is independently developable and
roughly ordered by priority — pick up the topmost unfinished batch. Items
within a batch are ordered so earlier ones unblock later ones. Open an issue
or PR to discuss any of these.

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

- **Device priority list** — replace the single `device` setting with an
  ordered list of preferred devices (by name substring or index) in
  `config.toml`. On startup, pick the first available; log which one was
  chosen. An empty list keeps today's behavior (system default).
- **Hotplug handling** — detect when the active input device disappears
  (stream error or sustained zero-energy windows), re-enumerate devices,
  and restart the stream on the best available device. Plugging in an
  external USB mic while running should switch to it seamlessly if it
  ranks higher in the priority list. Send a low-priority notification on
  device switch/loss so a dead mic is never silent. This subsumes the old
  "microphone disconnect detection" item.
- **Live tuning dashboard** (`--dashboard`) — interactive terminal view
  showing, per window: band energy ratio vs. the configured threshold
  (as a bar/meter), dominant frequency, hit/miss verdict, and the rolling
  confirmation state (e.g. `3/8, need 5`). Also show the active input
  device and stream status (overflows). This gives rich real-time feedback
  so threshold tuning is observable instead of trial-and-error. Plain
  curses or `rich` — must work over SSH.
- **Synthetic alarm tone** (`--play-tone`) — play an alarm-like beep
  pattern (default 3.2 kHz, T3 cadence, configurable) through the
  speakers to exercise the full mic → detector → notification pipeline
  without touching the real smoke alarm. Combine with `--dashboard` in a
  second terminal for end-to-end verification.
- **Event recorder** — optionally save a short WAV around every hit *and*
  near-miss (see Batch 2 for the near-miss definition) to a bounded
  directory (oldest deleted first). These recordings become the corpus
  for replay-based tuning.
- **Replay mode** (`--replay path.wav`) — run the detector offline against
  a recorded file and print per-window verdicts (dashboard-style output).
  Lets threshold changes be validated against past real events with zero
  live experimentation.

## Batch 2 — Listen-in on ambiguous signals

Goal: when the detector isn't sure — or the human isn't — deliver the
actual audio to the phone instead of forcing a guess.

- **Rolling pre-buffer** — keep the last N seconds (default 10) of audio
  in memory so any clip includes the sound *leading up to* the trigger,
  not just what follows it.
- **Near-miss / ambiguous signal definition** — a configurable band below
  the alert threshold (e.g. `ambiguous_windows = 3` of 8, or band energy
  ratio within X% of threshold). Ambiguous events are logged and recorded
  (Batch 1 event recorder) but don't fire the urgent alert.
- **Audio clip attachment** — on alert and (optionally) on ambiguous
  events, attach a short compressed clip (OGG/Opus keeps it small) to the
  ntfy notification so the sound can be heard directly from the push.
  ntfy.sh supports attachments; make attach-on-alert and
  attach-on-ambiguous independently configurable.
- **On-demand listen-in** — subscribe to a command topic (ntfy supports
  publishing from the phone) or use notification action buttons; on
  request, record a clip of configurable length and send it back as an
  attachment. This answers "what does it sound like right now?" remotely.
- *(Stretch)* **Live stream** — a local HTTP endpoint streaming mic audio
  (e.g. Opus over Icecast-style chunked response) for true real-time
  listening. Needs auth (shared token) since it exposes a live mic; only
  worth it if clip-on-demand proves too slow in practice.

## Batch 3 — Sound understanding: narrative guesses for unusual noise

Goal: when something unusual is heard, send a plain-language guess of what
it probably was ("repetitive metallic clicking, likely the gas heater
igniter") instead of just a frequency-band statistic.

Hardware reality check: this runs on a ThinkPad X220 (2-core Sandy Bridge
i5, 4 GB RAM, AVX but no AVX2). A true audio-multimodal LLM (Qwen2-Audio
class, 7B+) does not fit. The workable design is a **two-stage pipeline**,
and both stages must be strictly lower priority (nice/ionice, single
thread) than the detection loop, which must never be starved.

- **Unusual-noise trigger** — define what wakes the analyzer: sustained
  energy anomaly outside the alarm band (e.g. loudness Z-score over a
  rolling baseline for M consecutive windows), plus the ambiguous events
  from Batch 2. Configurable sensitivity; off by default.
- **Stage 1: audio event classifier** — run a lightweight pretrained
  tagger over the buffered clip. YAMNet (TFLite, ~4 MB, 521 AudioSet
  classes, comfortably real-time on this CPU) is the reference choice;
  keep the interface pluggable (PANNs CNN6 as an alternative). Output:
  top-k labels with confidences (e.g. `water tap 0.6, hiss 0.3`).
- **Stage 2: tiny local text LLM for narration** — feed the classifier
  labels, the trigger stats (duration, band, loudness), the time of day,
  and the user-authored surroundings description into a small instruct
  model via llama.cpp (works on AVX-only CPUs). Qwen2.5-0.5B-Instruct
  Q4 (~400 MB RAM) is the target size; 1.5B Q4 (~1.1 GB) as an opt-in if
  RAM allows. It writes a 1–2 sentence guess sent as a normal-priority
  notification with the clip attached.
- **`[surroundings]` config section** — free-text description of the
  laptop's acoustic environment, e.g. `"kitchen counter; fridge 2 m away
  hums and clicks when the compressor cycles; gas heater with piezo
  igniter in the corner; water pipes in the wall gurgle after flushing"`.
  This grounds the guesses. Support several named noise sources with
  optional typical-sound hints; entirely optional — the pipeline degrades
  gracefully to classifier labels alone.
- **Configurability & fallbacks** — master switch (off by default),
  classifier-only mode (skip the LLM, send raw labels — useful if 4 GB is
  tight), and an optional remote-API mode (send labels + surroundings to
  a hosted LLM) for anyone who prefers zero local inference. Model paths
  and thread count in `config.toml`.
- **Resource guardrails** — lazy-load models on first trigger, unload
  after an idle timeout, hard cap of one analysis at a time, and skip
  (with a log line) rather than queue if a previous analysis is still
  running. Never analyze during an active smoke alert.

## Batch 4 — Detection quality & calibration

- **Alarm profiles** — named frequency-band presets in `config.toml` for
  different detector models (e.g. `profile = "first-alert-sa511"`),
  selectable without editing raw thresholds. Ship a small library of
  common profiles.
- **Calibration mode** (`--calibrate`) — listen for N seconds while the
  user triggers the alarm's *test button* once, then print the dominant
  frequency bands and a suggested `freq_low_hz`/`freq_high_hz`/threshold.
  Pairs with the Batch 1 dashboard and replay mode.
- **Temporal pattern matching** — smoke alarms beep in a T3 pattern
  (3 beeps, pause). Checking the on/off cadence in addition to the
  frequency band would cut false positives from steady tones (kettles,
  appliance beeps) and allow a lower energy threshold.

## Batch 5 — Power monitoring

- **Low battery alert** — notify when battery drops below a configurable
  threshold (default 20%), with escalating priority as it falls further.
- **AC restored notification** — confirm when the laptop is back on mains
  power (closes the loop on the existing power-loss alert).

## Batch 6 — Notification plumbing

- **Configurable priority and tags** — move hardcoded ntfy `Priority` and
  `Tags` values into `config.toml`, per alert type.
- **Multiple topics** — route different alert types (smoke vs. power vs.
  heartbeat vs. sound-analysis) to separate ntfy topics so phone-side
  notification settings can differ per severity.
