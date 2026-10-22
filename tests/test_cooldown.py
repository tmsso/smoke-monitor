"""Cooldowns start "never fired" (H-1).

`time.monotonic()` counts from boot on Linux and the service starts seconds
after boot, so a cooldown timestamp initialised to 0.0 swallowed any alarm in
the first `cooldown_minutes` after a reboot.
"""
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402
from test_hotplug_integration import _patch, FakeStream  # noqa: E402


def test_first_alert_always_allowed():
    assert monitor.cooldown_elapsed(None, 30.0, 600)
    assert monitor.cooldown_elapsed(None, 0.0, 600)


def test_inside_and_after_cooldown():
    assert not monitor.cooldown_elapsed(30.0, 31.0, 600)
    assert not monitor.cooldown_elapsed(30.0, 629.9, 600)
    assert monitor.cooldown_elapsed(30.0, 630.0, 600)


def test_alarm_30s_after_boot_is_sent_once(monkeypatch):
    _patch(monkeypatch)
    sends = []
    monkeypatch.setattr(monitor.Notifier, "send", lambda self, *a, **k: sends.append(k) or True)
    # Every window confirms, so the loop sees a confirmation ~20×/s.
    monkeypatch.setattr(monitor.SmokeDetector, "analyze_window",
                        lambda self, x: SimpleNamespace(confirmed=True, ratio=0.9))
    # Pretend the machine booted 30 s ago: monotonic() reads 30.0 at start.
    real = time.monotonic
    start = real()
    monkeypatch.setattr(monitor.time, "monotonic", lambda: real() - start + 30.0)
    FakeStream.silent = False

    stop = threading.Event()
    t = threading.Thread(target=monitor.run, kwargs={"config_path": "x", "stop_event": stop},
                         daemon=True)
    t.start()
    time.sleep(2)
    stop.set()
    t.join(timeout=5)

    smoke = [k for k in sends if k.get("priority", "urgent") == "urgent"]
    assert len(smoke) == 1, f"expected exactly one smoke alert, got {len(smoke)}"
