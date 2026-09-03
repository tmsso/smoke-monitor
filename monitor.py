#!/usr/bin/env python3
import logging
import os
import queue
import threading
import time
import tomllib
from datetime import datetime, timedelta
import numpy as np
import sounddevice as sd
from pathlib import Path

from audio_devices import describe_device, select_input_device
from detector import SmokeDetector
from notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=value pairs from a .env file without overriding existing env vars.

    Keeps parity with systemd's EnvironmentFile so manual runs work too. Values
    already set in the environment (e.g. by systemd or the shell) take precedence.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def resolve_device(device_setting):
    """Return None (system default) or the configured device name/index."""
    if device_setting == "" or device_setting is None:
        return None
    try:
        return int(device_setting)
    except (ValueError, TypeError):
        return device_setting


AC_STATUS_PATH = Path("/sys/class/power_supply/AC/online")


def _read_ac_online() -> bool | None:
    """Return True if on AC power, False if on battery, None if unreadable."""
    try:
        return AC_STATUS_PATH.read_text().strip() == "1"
    except OSError:
        return None


def run(config_path: str = "config.toml", testing: bool = False):
    config = load_config(config_path)
    detector = SmokeDetector(config, testing=testing)
    notifier = Notifier(config)

    sample_rate = config["audio"]["sample_rate"]
    window_size = int(sample_rate * config["audio"]["window_seconds"])
    device = resolve_device(config["audio"].get("device", ""))

    # device_priority (ordered name substrings / indices) wins over the plain
    # `device` setting. Empty/absent list → unchanged behavior.
    priority = config["audio"].get("device_priority", []) or []
    devices = sd.query_devices()
    if priority:
        picked = select_input_device(devices, priority)
        if picked is not None:
            device = picked[0]
            logger.info("Selected input device %d: %s (matched device_priority)", *picked)
        else:
            logger.warning(
                "No device_priority entry %s matched an input device — falling back to %s",
                priority, describe_device(devices, device),
            )

    cooldown_seconds = config["notification"]["cooldown_minutes"] * 60
    power_cooldown_seconds = config["notification"].get("power_loss_cooldown_minutes", 30) * 60

    last_alert_time = 0.0
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=16)

    logger.info(
        "Starting smoke monitor | device=%s | window=%.1fs | freq=%d-%dHz%s",
        describe_device(devices, device),
        config["audio"]["window_seconds"],
        config["detection"]["freq_low_hz"],
        config["detection"]["freq_high_hz"],
        " | TESTING MODE" if testing else "",
    )

    def audio_callback(indata, frames, time_info, status):
        if status:
            logger.warning("Audio status: %s", status)
        try:
            audio_queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # drop the window rather than block the audio thread

    silence_warn_after = int(10 / config["audio"]["window_seconds"])  # ~10s of pure silence

    def process_loop():
        nonlocal last_alert_time
        silent_windows = 0
        silence_warned = False
        while True:
            samples = audio_queue.get()
            if samples is None:
                break
            # A muted or disconnected mic delivers exactly-zero samples; a live mic
            # always carries some noise/DC offset. Warn so silence isn't mistaken
            # for "all quiet" — otherwise a muted mic never alerts and looks healthy.
            if not np.any(samples):
                silent_windows += 1
                if silent_windows >= silence_warn_after and not silence_warned:
                    logger.warning(
                        "Microphone appears muted or disconnected — %.0fs of pure "
                        "silence. No smoke alarm can be detected! Check the mic mute "
                        "(see README: Troubleshooting).",
                        silent_windows * config["audio"]["window_seconds"],
                    )
                    silence_warned = True
            else:
                if silence_warned:
                    logger.warning("Microphone signal restored — resuming detection")
                silent_windows = 0
                silence_warned = False
            if detector.process_window(samples.astype(np.float32)):
                now = time.monotonic()
                if now - last_alert_time >= cooldown_seconds:
                    last_alert_time = now
                    logger.warning("ALARM DETECTED — sending notification")
                    notifier.send()
                else:
                    remaining = int(cooldown_seconds - (now - last_alert_time))
                    logger.info("Alarm detected but in cooldown (%ds remaining)", remaining)

    stop_event = threading.Event()

    def power_monitor_loop():
        last_power_alert_time = 0.0
        previous_ac = _read_ac_online()
        if previous_ac is None:
            logger.warning("Power supply status unavailable — power loss monitoring disabled")
            return
        if not previous_ac:
            logger.warning("Started on battery power — sending notification")
            last_power_alert_time = time.monotonic()
            notifier.send(
                message="Laptop lost AC power!",
                title="POWER ALERT",
                tags="electric_plug,warning",
            )
        while not stop_event.wait(30):
            ac_online = _read_ac_online()
            if ac_online is None:
                continue
            if previous_ac and not ac_online:
                now = time.monotonic()
                if now - last_power_alert_time >= power_cooldown_seconds:
                    last_power_alert_time = now
                    logger.warning("AC power lost — sending notification")
                    notifier.send(
                        message="Laptop lost AC power!",
                        title="POWER ALERT",
                        tags="electric_plug,warning",
                    )
                else:
                    remaining = int(power_cooldown_seconds - (now - last_power_alert_time))
                    logger.info("Power loss detected but in cooldown (%ds remaining)", remaining)
            previous_ac = ac_online

    def heartbeat_loop():
        notif = config["notification"]
        interval_hours = notif.get("heartbeat_interval_hours", 24)
        if interval_hours <= 0:
            return
        time_str = notif.get("heartbeat_time", "09:00")
        try:
            hh, mm = (int(p) for p in time_str.split(":")[:2])
        except ValueError:
            logger.error("Invalid heartbeat_time %r — expected HH:MM, heartbeat disabled", time_str)
            return

        now = datetime.now()
        first = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if first <= now:
            first += timedelta(days=1)
        wait = (first - now).total_seconds()
        logger.info("First heartbeat scheduled at %s (%.0fs from now)", first.strftime("%H:%M"), wait)

        if stop_event.wait(wait):
            return
        notifier.send(
            message="Smoke monitor is running normally.",
            title="Smoke Monitor OK",
            tags="white_check_mark",
            priority="low",
        )
        logger.info("Heartbeat sent")

        interval_seconds = interval_hours * 3600
        while not stop_event.wait(interval_seconds):
            notifier.send(
                message="Smoke monitor is running normally.",
                title="Smoke Monitor OK",
                tags="white_check_mark",
                priority="low",
            )
            logger.info("Heartbeat sent")

    worker = threading.Thread(target=process_loop, daemon=True)
    worker.start()

    power_worker = threading.Thread(target=power_monitor_loop, daemon=True)
    power_worker.start()

    heartbeat_worker = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_worker.start()

    with sd.InputStream(
        samplerate=sample_rate,
        blocksize=window_size,
        device=device,
        channels=1,
        dtype="float32",
        latency="high",
        callback=audio_callback,
    ):
        logger.info("Listening… press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
    stop_event.set()
    audio_queue.put(None)
    worker.join()
    power_worker.join()
    heartbeat_worker.join()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Smoke alarm audio monitor")
    parser.add_argument(
        "--config", default="config.toml", metavar="PATH",
        help="Path to config file (default: config.toml)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Testing mode: notify on first detection event, skip confirmation window",
    )
    parser.add_argument(
        "--notify", action="store_true",
        help="Send a test notification immediately and exit",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Log the per-window band energy ratio to diagnose detection",
    )
    args = parser.parse_args()
    load_dotenv()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.notify:
        config = load_config(args.config)
        Notifier(config).send("Test notification from smoke-monitor")
    else:
        run(config_path=args.config, testing=args.test)
