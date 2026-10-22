"""A crashed or stuck processing worker must not look healthy (H-3)."""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402
from test_hotplug_integration import _patch, FakeStream  # noqa: E402


class _ThreadKiller(BaseException):
    """Not an Exception, so the per-window guard lets it end the thread."""


def test_worker_verdict():
    v = monitor.worker_verdict
    assert v(True, 100.0, None, None, 5) == "ok"          # not started yet
    assert v(True, 100.0, 99.5, 99.5, 5) == "ok"
    assert v(False, 100.0, 99.5, 99.5, 5) == "dead"
    assert v(True, 100.0, 99.5, 89.0, 5) == "stuck"       # windows arrive, none processed
    assert v(True, 100.0, 90.0, 89.0, 5) == "ok"          # no windows at all: stream stall,
                                                          # diagnose_stream's job


def _start_run(stop):
    result = {}

    def target():
        try:
            monitor.run(config_path="x", stop_event=stop)
            result["exc"] = None
        except BaseException as e:  # noqa: BLE001 — the test inspects it
            result["exc"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, result


def test_one_failing_window_does_not_stop_processing(monkeypatch):
    _patch(monkeypatch)
    FakeStream.silent = False
    calls = []

    def flaky(self, x):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        return False

    monkeypatch.setattr(monitor.SmokeDetector, "process_window", flaky)
    stop = threading.Event()
    t, result = _start_run(stop)
    time.sleep(1.5)
    assert t.is_alive(), f"run() exited early: {result}"
    stop.set()
    t.join(timeout=5)
    assert result["exc"] is None
    assert len(calls) > 10, f"worker stopped after the error ({len(calls)} windows)"


def test_dead_worker_makes_run_raise(monkeypatch):
    _patch(monkeypatch)
    FakeStream.silent = False

    def die(self, x):
        raise _ThreadKiller()

    monkeypatch.setattr(monitor.SmokeDetector, "process_window", die)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)  # quiet the dying thread
    stop = threading.Event()
    t, result = _start_run(stop)
    t.join(timeout=5)
    assert not t.is_alive(), "run() kept going with a dead worker"
    assert isinstance(result["exc"], monitor.WorkerDied)
    assert str(result["exc"]) == "dead"


def test_worker_failing_every_window_makes_run_raise(monkeypatch):
    _patch(monkeypatch)
    FakeStream.silent = False
    monkeypatch.setattr(monitor, "STREAM_STALL_SECONDS", 0.5)

    def always_fail(self, x):
        raise ValueError("broken detector")

    monkeypatch.setattr(monitor.SmokeDetector, "process_window", always_fail)
    stop = threading.Event()
    t, result = _start_run(stop)
    t.join(timeout=6)
    assert not t.is_alive(), "run() kept going while nothing was analyzed"
    assert isinstance(result["exc"], monitor.WorkerDied)
    assert str(result["exc"]) == "stuck"
