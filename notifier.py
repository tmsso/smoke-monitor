import httpx
import logging

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config):
        ntfy = config["notification"]
        self.url = ntfy["ntfy_url"].rstrip("/") + "/" + ntfy["ntfy_topic"]
        self.cooldown_minutes = ntfy["cooldown_minutes"]

    def send(self, message: str = "Smoke alarm detected on intermouse!"):
        try:
            resp = httpx.post(
                self.url,
                content=message,
                headers={
                    "Title": "SMOKE ALARM",
                    "Priority": "urgent",
                    "Tags": "rotating_light,fire",
                },
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Notification sent: %s", message)
        except Exception as e:
            logger.error("Failed to send notification: %s", e)
