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

from audio_devices import (
    better_device,
    describe_device,
    diagnose_stream,
    select_input_device,
)
from detector import SmokeDetector
from notifier import Notifier

# No audio window for this long ⇒ the device stopped delivering (unplug that
# PortAudio didn't raise on). ~10 missed 0.5 s windows; not user-configurable.
STREAM_STALL_SECONDS = 5.0
# How often the supervised loop re-checks the priority list for a better mic
# and how often it retries opening a device after a loss.
DEVICE_RETRY_SECONDS = 5.0

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

    def pick_device():
        """Resolve the device to open now and the fresh device list: the top
        `device_priority` match if any, else the plain `device` setting."""
        devs = sd.query_devices()
        if priority:
            picked = select_input_device(devs, priority)
            if picked is not None:
                return picked[0], devs
            logger.warning(
                "No device_priority entry %s matched an input device — falling back to %s",
                priority, describe_device(devs, device),
            )
        return device, devs

    current_device, devices = pick_device()

    cooldown_seconds = config["notification"]["cooldown_minutes"] * 60
    power_cooldown_seconds = config["notification"].get("power_loss_cooldown_minutes", 30) * 60

    window_seconds = config["audio"]["window_seconds"]
    hotplug_silence_seconds = config["audio"].get("hotplug_silence_seconds", 60)
    silence_windows_limit = int(hotplug_silence_seconds / window_seconds) if hotplug_silence_seconds > 0 else 0
    device_poll_seconds = config["audio"].get("device_poll_seconds", 30)

    last_alert_time = 0.0
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=16)

    # Shared, coarse stream-health signals: the audio callback stamps when a
    # window last arrived; process_loop publishes the run of all-zero windows.
    # Single-writer each, read by the supervisor — GIL-atomic, no lock needed.
    class _Health:
        last_window_ts = None
        consecutive_silent = 0

        @classmethod
        def reset(cls):
            cls.last_window_ts = time.monotonic()
            cls.consecutive_silent = 0

    health = _Health

    logger.info(
        "Starting smoke monitor | device=%s | window=%.1fs | freq=%d-%dHz%s",
        describe_device(devices, current_device),
        config["audio"]["window_seconds"],
        config["detection"]["freq_low_hz"],
        config["detection"]["freq_high_hz"],
        " | TESTING MODE" if testing else "",
    )

    def audio_callback(indata, frames, time_info, status):
        if status:
            logger.warning("Audio status: %s", status)
        health.last_window_ts = time.monotonic()
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
                health.consecutive_silent = silent_windows
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
                health.consecutive_silent = 0
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

    def open_stream(dev):
        return sd.InputStream(
            samplerate=sample_rate,
            blocksize=window_size,
            device=dev,
            channels=1,
            dtype="float32",
            latency="high",
            callback=audio_callback,
        )

    def supervise_stream():
        """Keep an input stream alive across device loss and hot-swaps.

        Replaces the old single `with sd.InputStream` block: on a lost device
        (stream error, a stall, or a long run of all-zero windows) it closes
        the stream, re-enumerates every few seconds, and reopens on the best
        available device; while healthy it re-checks `device_priority` every
        `device_poll_seconds` and switches to a higher-priority mic if one
        appeared. Every loss / recovery / switch sends a low-priority ntfy.
        """
        nonlocal current_device
        announced_loss = False
        while not stop_event.is_set():
            try:
                stream = open_stream(current_device)
            except Exception as e:
                logger.error(
                    "Could not open input device %s: %s — retrying in %.0fs",
                    describe_device(sd.query_devices(), current_device), e, DEVICE_RETRY_SECONDS,
                )
                if not announced_loss:
                    notifier.send(
                        message=f"Smoke monitor lost its microphone ({e}). Retrying…",
                        title="Mic offline", tags="microphone,warning", priority="low",
                    )
                    announced_loss = True
                if stop_event.wait(DEVICE_RETRY_SECONDS):
                    break
                current_device, _ = pick_device()
                continue

            with stream:
                health.reset()
                reset_ts = health.last_window_ts
                confirmed_healthy = False
                desc = describe_device(sd.query_devices(), current_device)
                logger.info("Listening on %s… press Ctrl+C to stop", desc)

                last_poll = time.monotonic()
                while not stop_event.is_set():
                    if stop_event.wait(1):
                        break
                    now = time.monotonic()
                    # First window on a fresh stream ⇒ the device really works;
                    # only then announce a recovery (avoids flapping on a device
                    # that opens but delivers nothing).
                    if not confirmed_healthy and health.last_window_ts != reset_ts:
                        confirmed_healthy = True
                        if announced_loss:
                            logger.warning("Input device recovered: %s", desc)
                            notifier.send(
                                message=f"Smoke monitor microphone is back ({desc}).",
                                title="Mic online", tags="microphone,white_check_mark",
                                priority="low",
                            )
                            announced_loss = False
                    verdict = diagnose_stream(
                        now, health.last_window_ts, health.consecutive_silent,
                        STREAM_STALL_SECONDS, silence_windows_limit,
                    )
                    if verdict != "ok":
                        logger.warning(
                            "Input device %s looks lost (%s) — reconnecting", desc, verdict,
                        )
                        if not announced_loss:
                            notifier.send(
                                message=f"Smoke monitor lost its microphone ({verdict}). Reconnecting…",
                                title="Mic offline", tags="microphone,warning", priority="low",
                            )
                            announced_loss = True
                        current_device, _ = pick_device()
                        break
                    if priority and now - last_poll >= device_poll_seconds:
                        last_poll = now
                        current_index = current_device if isinstance(current_device, int) else None
                        upgrade = better_device(sd.query_devices(), priority, current_index)
                        if upgrade is not None:
                            logger.info(
                                "Higher-priority input device available: %d %s — switching",
                                *upgrade,
                            )
                            notifier.send(
                                message=f"Smoke monitor switched microphone to {upgrade[1]}.",
                                title="Mic switched", tags="microphone", priority="low",
                            )
                            current_device = upgrade[0]
                            break

    try:
        supervise_stream()
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
