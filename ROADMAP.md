# Roadmap

Planned features in rough priority order. Open an issue or PR to discuss any of these.

## Reliability

- ~~**Heartbeat notification**~~ — done: periodic "still alive" ping with configurable interval and first-fire time
- **Microphone disconnect detection** — alert if sustained zero-energy windows suggest the audio device has gone away

## Power monitoring

- **Low battery alert** — notify when battery drops below a configurable threshold (default 20%)
- **AC restored notification** — confirm when the laptop is back on mains power

## Smoke detection

- **Alarm profiles** — named frequency-band presets in `config.toml` for different detector models, selectable without editing raw thresholds
- **Calibration mode** (`--calibrate`) — listen for N seconds and print dominant frequency bands to help tune detection parameters

## Notifications

- **Configurable priority and tags** — move hardcoded ntfy `Priority` and `Tags` values into `config.toml`
- **Multiple topics** — route different alert types (power vs. smoke) to separate ntfy topics
