"""Dead-man's-switch ping (H-13): only while healthy, off when unset."""
import logging
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402
from notifier import Notifier  # noqa: E402
from test_hotplug_integration import BASE_CONFIG, FakeStream, _patch  # noqa: E402

URL = "https://hc-ping.example/3f1c-secret-uuid"
CFG = {**BASE_CONFIG, "notification": {**BASE_CONFIG["notification"],
                                       "healthcheck_interval_minutes": 0.5 / 60}}


def _run(monkeypatch, seconds, analyze=None):
    _patch(monkeypatch)
    monkeypatch.setattr(monitor, "load_config", lambda *_a, **_k: CFG)
    pings = []
    monkeypatch.setattr(monitor.Notifier, "ping", lambda self, url: pings.append(url) or True)
    if analyze is not None:
        monkeypatch.setattr(monitor.SmokeDetector, "analyze_window", analyze)
    FakeStream.silent = False
    stop = threading.Event()
    t = threading.Thread(target=monitor.run, kwargs={"config_path": "x", "stop_event": stop},
                         daemon=True)
    t.start()
    time.sleep(seconds)
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()
    return pings


def test_pings_while_healthy(monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_URL", URL)
    pings = _run(monkeypatch, 2.2)
    assert 3 <= len(pings) <= 5 and set(pings) == {URL}, pings


def test_no_ping_while_degraded(monkeypatch, caplog):
    monkeypatch.setenv("HEALTHCHECK_URL", URL)
    caplog.set_level(logging.WARNING)

    def broken(self, x):  # every window fails → nothing analysed → degraded
        raise ValueError("broken")

    monkeypatch.setattr(monitor, "STREAM_STALL_SECONDS", 30)  # keep H-3 from exiting first
    pings = _run(monkeypatch, 1.8, analyze=broken)
    assert pings == []
    assert any("ping skipped" in r.getMessage() for r in caplog.records)


def test_unset_means_no_pings(monkeypatch):
    monkeypatch.delenv("HEALTHCHECK_URL", raising=False)
    assert _run(monkeypatch, 1.5) == []


def test_ping_request_has_no_ntfy_token_and_url_is_not_logged(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("NTFY_TOKEN", "tk_secret")
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200 if len(seen) == 1 else 500)

    n = Notifier({"notification": {"ntfy_url": "https://ntfy.example", "cooldown_minutes": 10}},
                 transport=httpx.MockTransport(handler))
    caplog.set_level(logging.DEBUG)
    assert n.ping(URL) is True
    assert n.ping(URL) is False
    assert seen[0].method == "GET" and str(seen[0].url) == URL
    assert "Authorization" not in seen[0].headers
    assert not [r for r in caplog.records if "3f1c-secret-uuid" in r.getMessage()]


def test_health_problems_matches_heartbeat():
    ok = {"device": "d", "windows": 5, "overflows": 0, "peak_ratio": 0.1,
          "silent": False, "stalled": False, "worker_alive": True}
    assert monitor.health_problems(ok) == []
    assert monitor.health_problems({**ok, "silent": True})
    assert monitor.heartbeat_status({**ok, "windows": 0})[0] == "Smoke Monitor DEGRADED"
