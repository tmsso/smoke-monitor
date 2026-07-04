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

**Run manually:**
```bash
python monitor.py            # .env is loaded automatically
python monitor.py --debug    # also log the per-window band energy ratio
python monitor.py --test     # fire on a single detected window (skip confirmation)
python monitor.py --notify   # send one test notification and exit
```

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
