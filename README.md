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
source .env && python monitor.py
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
