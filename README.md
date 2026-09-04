# smoke-monitor

Listens to a microphone for smoke alarm sounds and sends a push notification via [ntfy.sh](https://ntfy.sh).

Runs as a systemd service on an always-on PC. Conservative detection: requires 5 of 8 consecutive 0.5s audio windows to show dominant energy in the 3000–3600 Hz band before alerting. 10-minute cooldown between notifications.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set NTFY_TOPIC to your private ntfy topic
```

**List available audio devices:**
```bash
python -c "import sounddevice; print(sounddevice.query_devices())"
```

**Picking a microphone.** Set `device` in `config.toml [audio]` to a name substring
or index for a fixed mic. For a mic that isn't always connected (e.g. a USB mic),
use `device_priority` instead — an ordered list of name substrings / indices, tried
in order, first connected match wins:

```toml
[audio]
device_priority = ["USB", "default"]   # USB mic if present, else system default
```

`device_priority` is checked before `device`; an empty list falls back to `device`.
The chosen device name and index are logged at startup.

**Hotplug recovery.** The audio stream runs under a supervisor: if the mic stops
delivering audio (unplugged, driver hiccup) or delivers only pure silence for
`hotplug_silence_seconds` (default 60), the stream is closed and reopened on the
best available device. While running, `device_priority` is re-checked every
`device_poll_seconds` (default 30) so plugging in a higher-priority mic switches
over without a restart. Every loss, recovery, and switch sends a low-priority
ntfy notification. Set `hotplug_silence_seconds = 0` to disable the silence
trigger (a full stall is still detected).

**Run manually:**
```bash
python monitor.py            # .env is loaded automatically
python monitor.py --debug    # also log the per-window band energy ratio
python monitor.py --test     # fire on a single detected window (skip confirmation)
python monitor.py --notify   # send one test notification and exit
```

**Test without the real alarm.** `--play-tone` plays a synthetic 3200 Hz T3
alarm pattern through the speakers, then exits — no stream, no notifications:

```bash
python monitor.py --play-tone            # 15 s at 3200 Hz
python monitor.py --play-tone 30         # 30 s
python monitor.py --play-tone --tone-hz 2900
```

Run it in one terminal against `python monitor.py --test` in another for an
end-to-end check through the actual mic. `--test` fires on a single in-band
window; a non-`--test` run needs sustained tone across the confirmation window,
so `--play-tone`'s beep/gap cadence drives `--test` but not a full run.

**Live tuning dashboard.** `--dashboard` shows a terminal UI (needs `rich`;
works over SSH), refreshed per window: the band-energy ratio as a meter with
the threshold marked, dominant frequency, per-window hit/miss, the rolling
confirmation state (`hits/seen, need N`), the active input device and the
input-overflow count. No notifications — a tuning aid, not a run mode.

```bash
python monitor.py --dashboard
# in another terminal, drive it:
python monitor.py --play-tone 30
```

**Replay a recording.** `--replay path.wav` runs the detector over a saved WAV
(e.g. one written by the event recorder) and prints the per-window band ratio,
dominant frequency and hit/miss, then whether the alarm would have fired — no
stream, no notifications. The WAV's sample rate must match `[audio] sample_rate`
(no resampling). Edit `energy_ratio_threshold` / the band in `config.toml` and
re-run to see a tuning change land:

```bash
python monitor.py --replay recordings/20260904-143012-hit.wav
```

## Event recording

Set `[recording] enabled = true` in `config.toml` to save a WAV around every
confirmed detection. Each clip includes `pre_seconds` of audio from *before*
the alarm confirmed (a rolling in-memory pre-buffer) plus `post_seconds` after:

```toml
[recording]
enabled = false
dir = "recordings"        # created on first write; git-ignored
max_files = 50            # oldest files past this are deleted
pre_seconds = 5
post_seconds = 10
```

Files are named `YYYYmmdd-HHMMSS-hit.wav` (mono, 16-bit, `sample_rate` Hz). A
sustained alarm produces one file, not one per window — a new clip only starts
once confirmation has dropped and re-triggered. When `enabled = false` nothing
is buffered or written.

## Install as systemd service

```bash
sudo cp smoke-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smoke-monitor
sudo journalctl -u smoke-monitor -f
```

## Phone setup

1. Install the [ntfy app](https://ntfy.sh) on your phone
2. Subscribe to the topic you set in `config.toml`

## Tuning

If the alarm is missed or false positives occur, adjust in `config.toml`:

- `energy_ratio_threshold` — lower = more sensitive, higher = more conservative
- `freq_low_hz` / `freq_high_hz` — narrow to match your detector's exact frequency
- `confirm_windows` / `confirm_out_of` — raise both for more confirmation required

## Heartbeat

The monitor sends a daily low-priority "still alive" notification so silence is never mistaken for normal operation. Configure in `config.toml`:

```toml
[notification]
heartbeat_interval_hours = 24   # set to 0 to disable
heartbeat_time = "09:00"        # first heartbeat fires at or after this local time
```

Subsequent pings follow every `heartbeat_interval_hours` from the first. Setting `heartbeat_time` prevents overnight notifications when the service (re)starts.

## Troubleshooting

**The alarm never triggers / no hits even when beeping at the mic.**

First check the mic is actually capturing audio. Run with `--debug` and watch the
per-window band ratio — it should jump toward 1.0 when the alarm sounds:

```bash
sudo systemctl stop smoke-monitor        # release the mic
python monitor.py --debug --test         # --test fires on a single hit
```

- **`ratio` rises when you beep** → the mic works; a real (sustained) alarm will
  confirm. Short test chirps are filtered by design (needs ~2.5s of tone).
- **`ratio` stays ~0** → the mic is delivering silence. See below.

**Microphone muted (delivers pure silence).** A muted mic returns exactly-zero
samples, so detection is impossible. The monitor now logs a loud warning after
~10s of pure silence: `Microphone appears muted or disconnected`. On laptops the
mic-mute is a codec-level `Capture Switch`; without a desktop environment the
mic-mute key has no handler, so the switch can stay muted (the mic-mute LED stays
lit). Confirm and fix with ALSA:

```bash
# Confirm silence — RMS/peak of 0.0 means muted or dead:
python -c "import numpy as np, sounddevice as sd; r=sd.rec(32000,samplerate=16000,channels=1); sd.wait(); print('peak', float(np.max(np.abs(r))))"

# Fix (requires alsa-utils):
sudo apt install -y alsa-utils
amixer -c 0 sset Capture cap        # unmute + enable capture
amixer -c 0 sset Capture 80%        # sane capture level
sudo alsactl store                  # persist across reboots
```
