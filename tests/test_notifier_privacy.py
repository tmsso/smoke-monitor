"""The topic stays out of logs (H-6); optional NTFY_TOKEN header (H-7)."""
import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monitor  # noqa: E402,F401 — importing it applies the httpx log level
from notifier import Notifier  # noqa: E402

TOPIC = "secret-topic-Zq8x"
CONFIG = {"notification": {"ntfy_url": "https://ntfy.example", "cooldown_minutes": 10}}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", TOPIC)
    monkeypatch.delenv("NTFY_TOKEN", raising=False)
    return monkeypatch


def _notifier(status, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status)
    return Notifier(CONFIG, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status", [200, 500])
def test_no_topic_in_any_log_record(env, caplog, status):
    caplog.set_level(logging.DEBUG, logger="notifier")
    caplog.set_level(logging.INFO)  # root: what the service journal sees
    _notifier(status).send(message="hello")
    assert caplog.records, "expected the notifier to log its own line"
    for rec in caplog.records:
        assert TOPIC not in rec.getMessage(), f"{rec.name}: {rec.getMessage()}"


def test_error_line_is_redacted_but_informative(env, caplog):
    caplog.set_level(logging.INFO)
    _notifier(503).send(message="hello")
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and "503" in errors[0] and "<topic>" in errors[0]


def test_token_header_sent_when_set(env):
    env.setenv("NTFY_TOKEN", "tk_abc123")
    seen = []
    assert _notifier(200, seen).send(message="x")
    assert seen[0].headers["Authorization"] == "Bearer tk_abc123"


def test_no_auth_header_without_token(env):
    seen = []
    assert _notifier(200, seen).send(message="x")
    assert "Authorization" not in seen[0].headers
