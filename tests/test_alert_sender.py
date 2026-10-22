"""AlertSender — non-blocking enqueue, smoke retries, cooldown at delivery (H-2)."""
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notifier import AlertSender, Notifier  # noqa: E402

CONFIG = {"notification": {"ntfy_url": "https://example.invalid", "ntfy_topic": "t",
                           "cooldown_minutes": 10}}


class Server:
    """MockTransport handler: replies from a scripted status list (last repeats)."""

    def __init__(self, statuses, delay=0.0):
        self.statuses = list(statuses)
        self.delay = delay
        self.requests = []

    def __call__(self, request):
        if self.delay:
            time.sleep(self.delay)
        self.requests.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(status)


def _sender(server, cooldown=600.0, backoff=(0.01,), other_retry=0.01, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.delenv("NTFY_TOPIC", raising=False)
    notifier = Notifier(CONFIG, transport=httpx.MockTransport(server))
    stop = threading.Event()
    sender = AlertSender(notifier, stop, cooldown, smoke_backoff=backoff,
                         other_retry_seconds=other_retry).start()
    return sender, stop


def _wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def _stop(sender, stop):
    stop.set()
    sender.join(timeout=2)
    assert not sender._thread.is_alive()


def test_smoke_retries_until_delivered_exactly_once(monkeypatch):
    server = Server([500, 503, 200])
    sender, stop = _sender(server, monkeypatch=monkeypatch)
    assert sender.smoke() == "queued"
    assert _wait_for(lambda: len(server.requests) == 3)
    time.sleep(0.1)  # no further attempts after the 200
    assert len(server.requests) == 3
    assert all(r.headers["Priority"] == "urgent" for r in server.requests)
    assert sender.smoke() == "cooldown"
    _stop(sender, stop)


def test_enqueue_does_not_wait_for_the_network(monkeypatch):
    server = Server([200], delay=0.5)
    sender, stop = _sender(server, monkeypatch=monkeypatch)
    t0 = time.perf_counter()
    sender.smoke()
    sender.send(message="m", title="t", tags="x", priority="low")
    assert time.perf_counter() - t0 < 0.010
    _stop(sender, stop)


def test_confirmations_while_pending_do_not_duplicate(monkeypatch):
    server = Server([500, 500, 200])
    sender, stop = _sender(server, backoff=(0.05,), monkeypatch=monkeypatch)
    assert sender.smoke() == "queued"
    for _ in range(10):
        assert sender.smoke() == "pending"
    assert _wait_for(lambda: len(server.requests) == 3)
    time.sleep(0.1)
    assert len(server.requests) == 3
    _stop(sender, stop)


def test_cooldown_starts_at_delivery_not_detection(monkeypatch):
    # Delivery succeeds only on the 3rd try; the cooldown must count from then.
    server = Server([500, 500, 200])
    sender, stop = _sender(server, backoff=(0.1,), monkeypatch=monkeypatch)
    sender.smoke()
    assert _wait_for(lambda: len(server.requests) == 3)
    delivered_at = sender._smoke_delivered_at
    assert delivered_at is not None
    assert sender.cooldown_remaining(delivered_at) == 600
    _stop(sender, stop)


def test_smoke_gives_up_after_cooldown_window_then_can_requeue(monkeypatch):
    server = Server([500])
    sender, stop = _sender(server, cooldown=0.2, backoff=(0.05,), monkeypatch=monkeypatch)
    sender.smoke()
    assert _wait_for(lambda: not sender._smoke_pending)
    n = len(server.requests)
    assert 2 <= n <= 6
    time.sleep(0.1)
    assert len(server.requests) == n  # gave up, no more attempts
    assert sender.smoke() == "queued"  # nothing delivered → no cooldown
    _stop(sender, stop)


def test_other_kinds_get_exactly_one_retry(monkeypatch):
    server = Server([500])
    sender, stop = _sender(server, monkeypatch=monkeypatch)
    sender.send(message="Laptop lost AC power!", title="POWER ALERT", tags="x")
    assert _wait_for(lambda: len(server.requests) == 2)
    time.sleep(0.1)
    assert len(server.requests) == 2
    _stop(sender, stop)


def test_smoke_overtakes_queued_routine_messages(monkeypatch):
    server = Server([200], delay=0.05)
    sender, stop = _sender(server, monkeypatch=monkeypatch)
    for i in range(3):
        sender.send(message=f"routine {i}", title="t", tags="x", priority="low")
    sender.smoke()
    assert _wait_for(lambda: len(server.requests) == 4)
    # The first routine message may already be in flight; smoke is next.
    order = [r.headers["Priority"] for r in server.requests]
    assert order.index("urgent") <= 1, order
    _stop(sender, stop)


def test_stop_interrupts_backoff(monkeypatch):
    server = Server([500])
    sender, stop = _sender(server, backoff=(30,), monkeypatch=monkeypatch)
    sender.smoke()
    assert _wait_for(lambda: len(server.requests) == 1)
    t0 = time.monotonic()
    _stop(sender, stop)
    assert time.monotonic() - t0 < 1.0


def test_notifier_send_reports_success(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert Notifier(CONFIG, transport=httpx.MockTransport(Server([200]))).send()
    assert not Notifier(CONFIG, transport=httpx.MockTransport(Server([500]))).send()
