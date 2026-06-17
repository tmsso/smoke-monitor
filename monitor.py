#!/usr/bin/env python3
import logging
import queue
import threading
import time
import tomllib
import numpy as np
import sounddevice as sd
from pathlib import Path

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


def resolve_device(device_setting):
    """Return None (system default) or the configured device name/index."""
    if device_setting == "" or device_setting is None:
        return None
    try:
        return int(device_setting)
    except (ValueError, TypeError):
        return device_setting


def run(config_path: str = "config.toml", testing: bool = False):
    config = load_config(config_path)
    detector = SmokeDetector(config, testing=testing)
    notifier = Notifier(config)

    sample_rate = config["audio"]["sample_rate"]
    window_size = int(sample_rate * config["audio"]["window_seconds"])
    device = resolve_device(config["audio"].get("device", ""))
    cooldown_seconds = config["notification"]["cooldown_minutes"] * 60

    last_alert_time = 0.0
    audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=16)

    logger.info(
        "Starting smoke monitor | device=%s | window=%.1fs | freq=%d-%dHz%s",
        device or "default",
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

    def process_loop():
        nonlocal last_alert_time
        while True:
            samples = audio_queue.get()
            if samples is None:
                break
            if detector.process_window(samples.astype(np.float32)):
                now = time.monotonic()
                if now - last_alert_time >= cooldown_seconds:
                    last_alert_time = now
                    logger.warning("ALARM DETECTED — sending notification")
                    notifier.send()
                else:
                    remaining = int(cooldown_seconds - (now - last_alert_time))
                    logger.info("Alarm detected but in cooldown (%ds remaining)", remaining)

    worker = threading.Thread(target=process_loop, daemon=True)
    worker.start()

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
    audio_queue.put(None)
    worker.join()


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
    args = parser.parse_args()
    if args.notify:
        config = load_config(args.config)
        Notifier(config).send("Test notification from smoke-monitor")
    else:
        run(config_path=args.config, testing=args.test)
