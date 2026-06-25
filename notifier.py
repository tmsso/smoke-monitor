import httpx
import logging
import os

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config):
        ntfy = config["notification"]
        topic = os.environ.get("NTFY_TOPIC") or ntfy.get("ntfy_topic", "")
        if not topic:
            raise ValueError("NTFY_TOPIC env var is not set")
        self.url = ntfy["ntfy_url"].rstrip("/") + "/" + topic
        self.cooldown_minutes = ntfy["cooldown_minutes"]

    def send(self, message: str = "Smoke alarm detected on intermouse!", title: str = "SMOKE ALARM", tags: str = "rotating_light,fire", priority: str = "urgent"):
        try:
            resp = httpx.post(
                self.url,
                content=message,
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": tags,
                },
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Notification sent: %s", message)
        except Exception as e:
            logger.error("Failed to send notification: %s", e)
