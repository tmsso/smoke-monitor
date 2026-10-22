"""Honest heartbeat (H-4) and aggregated overflow warnings (H-5)."""
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402
from test_hotplug_integration import BASE_CONFIG, FAKE_DEVICES, FakeStream, _patch  # noqa: E402

HEALTHY = {"device": "fake-mic", "windows": 172800, "overflows": 6, "peak_ratio": 0.12,
           "silent": False, "stalled": False, "worker_alive": True}


# --- heartbeat_status ------------------------------------------------------

def test_healthy_heartbeat_is_low_priority_ok_with_stats():
    title, msg, prio, tags = monitor.heartbeat_status(HEALTHY)
    assert (title, prio, tags) == ("Smoke Monitor OK", "low", "white_check_mark")
    assert "fake-mic" in msg and "172800 windows" in msg and "0.12" in msg and "6 input" in msg


def _degraded(**over):
    title, msg, prio, tags = monitor.heartbeat_status({**HEALTHY, **over})
    assert (title, prio, tags) == ("Smoke Monitor DEGRADED", "default", "warning")
    return msg


def test_muted_mic_is_degraded():
    assert "pure silence" in _degraded(silent=True)


def test_stalled_stream_is_degraded():
    assert "no audio arriving" in _degraded(stalled=True)


def test_dead_worker_is_degraded():
    assert "worker is dead" in _degraded(worker_alive=False)


def test_nothing_analysed_is_degraded():
    assert "no audio analysed" in _degraded(windows=0)


# --- schedule --------------------------------------------------------------

DAY = timedelta(days=1)


def test_schedule_does_not_drift_across_sends():
    first = datetime(2026, 7, 14, 9, 0)
    target = first
    for k in range(97):
        sent_at = target + timedelta(seconds=0.8)   # send latency each time
        target = monitor.next_heartbeat(first, DAY, sent_at)
        assert target == first + (k + 1) * DAY
    assert target.time() == first.time()


def test_schedule_skips_slots_missed_during_suspend():
    first = datetime(2026, 7, 14, 9, 0)
    woke = datetime(2026, 7, 17, 14, 0)            # 3+ days asleep
    assert monitor.next_heartbeat(first, DAY, woke) == datetime(2026, 7, 18, 9, 0)


def test_schedule_before_first():
    first = datetime(2026, 7, 14, 9, 0)
    assert monitor.next_heartbeat(first, DAY, first - timedelta(hours=3)) == first


def test_wait_until_survives_dst_fall_back():
    # Budapest leaves CEST on 2026-10-25 at 03:00 → 02:00. A single 24 h
    # monotonic wait from Saturday 09:00 would fire at 08:00 local on Sunday.
    real = [0.0]                                    # seconds elapsed on a monotonic clock
    start = datetime(2026, 10, 24, 9, 0, 1)
    switch = datetime(2026, 10, 25, 3, 0)

    def local_now():
        t = start + timedelta(seconds=real[0])
        return t if t < switch else t - timedelta(hours=1)

    def fake_wait(seconds):
        real[0] += seconds
        return False

    target = datetime(2026, 10, 25, 9, 0)
    assert monitor.wait_until(target, local_now, fake_wait) is False
    assert local_now() >= target
    assert local_now() - target < timedelta(seconds=61)
    assert abs(real[0] - 25 * 3600) < 61           # the day really had 25 h


def test_wait_until_reports_stop():
    assert monitor.wait_until(datetime(2099, 1, 1), datetime.now, lambda s: True) is True


# --- overflow aggregation --------------------------------------------------

def test_is_overflow_only():
    f = sd.CallbackFlags()
    assert not monitor.is_overflow_only(f)
    f.input_overflow = True
    assert monitor.is_overflow_only(f)
    f.input_underflow = True
    assert not monitor.is_overflow_only(f)


class OverflowingStream(FakeStream):
    def _pump(self):
        flags = sd.CallbackFlags()
        flags.input_overflow = True
        while self._run:
            frame = (__import__("numpy").random.randn(self._blocksize, 1) * 0.05).astype("float32")
            self._callback(frame, self._blocksize, None, flags)
            time.sleep(self._interval)


def _run_for(seconds):
    stop = threading.Event()
    t = threading.Thread(target=monitor.run, kwargs={"config_path": "x", "stop_event": stop},
                         daemon=True)
    t.start()
    time.sleep(seconds)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_overflows_are_counted_not_logged_per_call(monkeypatch, caplog):
    _patch(monkeypatch)
    monkeypatch.setattr(monitor.sd, "InputStream", OverflowingStream)
    monkeypatch.setattr(monitor, "OVERFLOW_SUMMARY_SECONDS", 1.5)
    caplog.set_level(logging.INFO)
    _run_for(2.6)
    msgs = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert not [m for lvl, m in msgs if lvl >= logging.WARNING and "overflow" in m], msgs
    summaries = [m for _, m in msgs if m.startswith("Audio input overflows")]
    assert len(summaries) == 1, summaries
    assert int(summaries[0].rsplit(" ", 1)[1]) > 10   # ~30 windows/1.5 s at 0.05 s windows


# --- heartbeat wiring ------------------------------------------------------

def test_heartbeat_reports_real_stats(monkeypatch):
    _patch(monkeypatch)
    cfg = {**BASE_CONFIG, "notification": {**BASE_CONFIG["notification"],
                                           "heartbeat_interval_hours": 24}}
    monkeypatch.setattr(monitor, "load_config", lambda *_a, **_k: cfg)
    sends = []
    monkeypatch.setattr(monitor.Notifier, "send", lambda self, *a, **k: sends.append(k) or True)
    calls = []

    def fake_wait_until(target, now_fn, wait_fn, max_chunk=60.0):
        calls.append(target)
        if len(calls) == 1:
            time.sleep(1.0)          # let ~20 windows flow, then "it's 09:00"
            return False
        return wait_fn(10)           # second slot: just wait for stop

    monkeypatch.setattr(monitor, "wait_until", fake_wait_until)
    FakeStream.silent = False
    _run_for(1.8)

    beats = [k for k in sends if k.get("title", "").startswith("Smoke Monitor")]
    assert len(beats) == 1, sends
    assert beats[0]["title"] == "Smoke Monitor OK", beats[0]
    assert "fake-mic" in beats[0]["message"] or "default" in beats[0]["message"]
    assert len(calls) == 2 and calls[1] - calls[0] == timedelta(hours=24)
