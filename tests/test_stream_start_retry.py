"""A stream that opens but fails to start is retried, not fatal (H-9)."""
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402
from test_hotplug_integration import _patch, FakeStream  # noqa: E402


class FailsToStartOnce(FakeStream):
    failures_left = 1
    closed = 0

    def __enter__(self):
        if FailsToStartOnce.failures_left:
            FailsToStartOnce.failures_left -= 1
            raise RuntimeError("Error starting stream: Unanticipated host error")
        return super().__enter__()

    def close(self):
        FailsToStartOnce.closed += 1


def test_start_failure_retries_then_listens(monkeypatch, caplog):
    _patch(monkeypatch)
    monkeypatch.setattr(monitor.sd, "InputStream", FailsToStartOnce)
    monkeypatch.setattr(monitor, "DEVICE_RETRY_SECONDS", 0.2)
    sends = []
    monkeypatch.setattr(monitor.Notifier, "send", lambda self, *a, **k: sends.append(k) or True)
    FakeStream.instances = 0
    FakeStream.silent = False
    caplog.set_level(logging.INFO)

    stop = threading.Event()
    t = threading.Thread(target=monitor.run, kwargs={"config_path": "x", "stop_event": stop},
                         daemon=True)
    t.start()
    time.sleep(2)
    assert t.is_alive(), "run() died on a stream start failure"
    stop.set()
    t.join(timeout=5)

    assert FakeStream.instances == 2
    assert FailsToStartOnce.closed == 1, "failed stream should be closed"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Could not open/start input device" in m for m in msgs)
    assert any(m.startswith("Listening on") for m in msgs)
    titles = [k.get("title") for k in sends]
    assert titles.count("Mic offline") == 1 and titles.count("Mic online") == 1, titles
