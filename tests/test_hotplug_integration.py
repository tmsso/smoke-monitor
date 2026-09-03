"""Integration test for the supervised stream loop against a fake InputStream.

Exercises the real run() / process_loop / supervise_stream / diagnose_stream
wiring — no audio hardware — to pin the reconnect cadence when a device
delivers only silence. Guards the regression where a stale per-thread silent
counter re-tripped the hotplug limit every supervisor tick (~1 s) instead of
once per `hotplug_silence_seconds`.
"""
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402

SR = 16000
WIN_S = 0.05
BLOCK = int(SR * WIN_S)

FAKE_DEVICES = [
    {"index": 0, "name": "fake-mic", "max_input_channels": 1, "max_output_channels": 0},
    {"index": 1, "name": "default", "max_input_channels": 128, "max_output_channels": 128},
]

BASE_CONFIG = {
    "audio": {
        "sample_rate": SR, "window_seconds": WIN_S, "device": "",
        "device_priority": [], "hotplug_silence_seconds": 3, "device_poll_seconds": 999,
    },
    "detection": {
        "freq_low_hz": 3000, "freq_high_hz": 3600, "energy_ratio_threshold": 0.35,
        "confirm_windows": 5, "confirm_out_of": 8,
    },
    "notification": {
        "ntfy_url": "https://example.invalid", "ntfy_topic": "test-topic",
        "cooldown_minutes": 10, "power_loss_cooldown_minutes": 30,
        "heartbeat_interval_hours": 0,
    },
}


class FakeStream:
    """Minimal sd.InputStream stand-in that pumps fixed frames on a thread."""

    instances = 0
    silent = False

    def __init__(self, *, samplerate, blocksize, device, channels, dtype, latency, callback):
        FakeStream.instances += 1
        self._callback = callback
        self._blocksize = blocksize
        # Deliver a window every blocksize/samplerate seconds, exactly as a real
        # InputStream with blocksize = sample_rate * window_seconds does.
        self._interval = blocksize / samplerate
        self._run = False

    def __enter__(self):
        self._run = True
        self._thr = threading.Thread(target=self._pump, daemon=True)
        self._thr.start()
        return self

    def __exit__(self, *exc):
        self._run = False
        self._thr.join(timeout=1)

    def _pump(self):
        while self._run:
            if FakeStream.silent:
                frame = np.zeros((self._blocksize, 1), dtype="float32")
            else:
                frame = (np.random.randn(self._blocksize, 1) * 0.05).astype("float32")
            self._callback(frame, self._blocksize, None, None)
            time.sleep(self._interval)


def _patch(monkeypatch):
    monkeypatch.setattr(monitor, "load_config", lambda *_a, **_k: BASE_CONFIG)
    monkeypatch.setattr(monitor.sd, "InputStream", FakeStream)
    monkeypatch.setattr(monitor.sd, "query_devices", lambda *a, **k: FAKE_DEVICES)
    monkeypatch.setattr(monitor.Notifier, "send", lambda *a, **k: None)


def _run_run(seconds):
    stop = threading.Event()
    t = threading.Thread(
        target=monitor.run,
        kwargs={"config_path": "x", "stop_event": stop},
        daemon=True,
    )
    t.start()
    time.sleep(seconds)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive(), "run() did not stop on stop_event"


def test_silent_device_reconnects_once_per_hotplug_interval(monkeypatch):
    _patch(monkeypatch)
    FakeStream.instances = 0
    FakeStream.silent = True
    _run_run(11)
    n = FakeStream.instances
    # hotplug_silence_seconds=3 over ~11 s ⇒ ~3-4 opens. The regression (stale
    # per-thread counter) made this ~10, one per 1 s supervisor tick.
    assert 2 <= n <= 6, f"expected a reconnect roughly every 3 s, got {n} opens in 11 s"


def test_healthy_device_never_reconnects(monkeypatch):
    _patch(monkeypatch)
    FakeStream.instances = 0
    FakeStream.silent = False
    _run_run(8)
    assert FakeStream.instances == 1, (
        f"healthy mic should open exactly once, opened {FakeStream.instances}×"
    )


def test_tight_recovery_config_holds_cadence(monkeypatch):
    # window_seconds 0.5 + hotplug_silence_seconds 5 → silence limit of 10, below
    # the audio_queue depth (16). Regression guard for #8 at a low limit, and for
    # the queue drained on reset() (a stale pre-loss backlog must not add reopens).
    cfg = {
        **BASE_CONFIG,
        "audio": {**BASE_CONFIG["audio"], "window_seconds": 0.5,
                  "hotplug_silence_seconds": 5},
    }
    monkeypatch.setattr(monitor, "load_config", lambda *_a, **_k: cfg)
    monkeypatch.setattr(monitor.sd, "InputStream", FakeStream)
    monkeypatch.setattr(monitor.sd, "query_devices", lambda *a, **k: FAKE_DEVICES)
    monkeypatch.setattr(monitor.Notifier, "send", lambda *a, **k: None)
    FakeStream.instances = 0
    FakeStream.silent = True
    _run_run(18)
    n = FakeStream.instances
    # ~3 legit reopens (one per 5 s). Was ~18 before #8 (one per 1 s tick).
    assert n <= 5, f"tight config thrashed: {n} opens in 18 s (expected ~3)"
