import httpx
import itertools
import logging
import os
import queue
import socket
import threading
import time

logger = logging.getLogger(__name__)

_HOSTNAME = socket.gethostname()

# Retry delays (s) for an undelivered smoke alert; the last one repeats until
# the alert is `cooldown_minutes` old, then it's dropped with an error.
SMOKE_BACKOFF = (5, 10, 20, 40, 60)
# Every other kind (power, mic, heartbeat) gets one retry after this delay.
OTHER_RETRY_SECONDS = 5


class Notifier:
    def __init__(self, config, transport: httpx.BaseTransport | None = None):
        ntfy = config["notification"]
        topic = os.environ.get("NTFY_TOPIC") or ntfy.get("ntfy_topic", "")
        if not topic:
            raise ValueError("NTFY_TOPIC env var is not set")
        self.url = ntfy["ntfy_url"].rstrip("/") + "/" + topic
        self._topic = topic
        self.cooldown_minutes = ntfy["cooldown_minutes"]
        # Optional access token for a protected topic (ntfy account or a
        # self-hosted server with ACLs). Sent on every request.
        headers = {}
        token = os.environ.get("NTFY_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # `transport` lets tests swap in httpx.MockTransport; None = real network.
        self._client = httpx.Client(transport=transport, timeout=10, headers=headers)

    def _redact(self, text: str) -> str:
        """The topic is the secret on ntfy.sh — keep it out of log lines
        (httpx error messages embed the full request URL)."""
        return text.replace(self._topic, "<topic>")

    def send(self, message: str = "", title: str = "SMOKE ALARM", tags: str = "rotating_light,fire", priority: str = "urgent") -> bool:
        """POST one notification. Returns True on a 2xx, False on any failure."""
        if not message:
            message = f"Smoke alarm detected on {_HOSTNAME}!"
        try:
            resp = self._client.post(
                self.url,
                content=message,
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": tags,
                },
            )
            resp.raise_for_status()
            logger.info("Notification sent: %s", message)
            return True
        except Exception as e:
            logger.error("Failed to send notification: %s", self._redact(str(e)))
            return False


class AlertSender:
    """Delivers notifications from a daemon thread so callers never block.

    The audio-processing thread only enqueues: a send can take up to the 10 s
    HTTP timeout, about as long as the ~8 s audio queue lasts, so sending
    inline dropped audio mid-alarm. Smoke alerts own the alarm cooldown here,
    because the cooldown must start at *successful delivery* — starting it at
    detection meant one network blip lost the alert and suppressed retries.
    """

    def __init__(self, notifier: Notifier, stop_event: threading.Event,
                 cooldown_seconds: float, smoke_backoff=SMOKE_BACKOFF,
                 other_retry_seconds=OTHER_RETRY_SECONDS):
        self._notifier = notifier
        self._stop = stop_event
        self._cooldown = cooldown_seconds
        self._backoff = smoke_backoff
        self._other_retry = other_retry_seconds
        # (rank, seq, kwargs): smoke (rank 0) overtakes queued routine messages;
        # seq keeps FIFO order within a rank and avoids comparing dicts.
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._smoke_pending = False
        self._smoke_delivered_at: float | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def smoke(self, now: float | None = None) -> str:
        """Queue the urgent smoke alert. Returns "queued", "pending" (one is
        already being delivered) or "cooldown" (one was delivered recently)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._smoke_pending:
                return "pending"
            last = self._smoke_delivered_at
            if last is not None and now - last < self._cooldown:
                return "cooldown"
            self._smoke_pending = True
        self._queue.put((0, next(self._seq), {"_smoke": now}))
        return "queued"

    def cooldown_remaining(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        last = self._smoke_delivered_at
        return 0 if last is None else max(0, int(self._cooldown - (now - last)))

    def send(self, **kwargs) -> None:
        """Queue a non-smoke notification (Notifier.send kwargs); one retry."""
        self._queue.put((1, next(self._seq), kwargs))

    def join(self, timeout: float | None = None):
        """Wake the worker and wait for it; call after setting stop_event."""
        self._queue.put((2, next(self._seq), None))
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _loop(self):
        while not self._stop.is_set():
            _, _, item = self._queue.get()
            if item is None:
                break
            if "_smoke" in item:
                self._deliver_smoke(item["_smoke"])
            elif not self._notifier.send(**item):
                if self._stop.wait(self._other_retry):
                    break
                self._notifier.send(**item)

    def _deliver_smoke(self, queued_at: float):
        attempt = 0
        try:
            while True:
                if self._notifier.send():
                    with self._lock:
                        self._smoke_delivered_at = time.monotonic()
                    return
                delay = self._backoff[min(attempt, len(self._backoff) - 1)]
                attempt += 1
                if time.monotonic() + delay - queued_at > self._cooldown:
                    logger.error("Smoke alert undelivered after %d attempts — giving up", attempt)
                    return
                logger.warning("Smoke alert not delivered — retry %d in %ss", attempt, delay)
                if self._stop.wait(delay):
                    return
        finally:
            with self._lock:
                self._smoke_pending = False
