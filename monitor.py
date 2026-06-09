#!/usr/bin/env python3
import logging
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


def run(config_path: str = "config.toml"):
    config = load_config(config_path)
    detector = SmokeDetector(config)
    notifier = Notifier(config)

    sample_rate = config["audio"]["sample_rate"]
    window_size = int(sample_rate * config["audio"]["window_seconds"])
    device = resolve_device(config["audio"].get("device", ""))
    cooldown_seconds = config["notification"]["cooldown_minutes"] * 60

    last_alert_time = 0.0

    logger.info(
        "Starting smoke monitor | device=%s | window=%.1fs | freq=%d-%dHz",
        device or "default",
        config["audio"]["window_seconds"],
        config["detection"]["freq_low_hz"],
        config["detection"]["freq_high_hz"],
    )

    def audio_callback(indata, frames, time_info, status):
        nonlocal last_alert_time
        if status:
            logger.warning("Audio status: %s", status)

        samples = indata[:, 0].astype(np.float32)
        if detector.process_window(samples):
            now = time.monotonic()
            if now - last_alert_time >= cooldown_seconds:
                last_alert_time = now
                logger.warning("ALARM DETECTED — sending notification")
                notifier.send()
            else:
                remaining = int(cooldown_seconds - (now - last_alert_time))
                logger.info("Alarm detected but in cooldown (%ds remaining)", remaining)

    with sd.InputStream(
        samplerate=sample_rate,
        blocksize=window_size,
        device=device,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    ):
        logger.info("Listening… press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopped by user")


if __name__ == "__main__":
    import sys
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    run(cfg)
