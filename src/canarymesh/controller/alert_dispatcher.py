"""Webhook alert dispatcher for incident notifications."""

import datetime
import logging
from typing import Any

import httpx

logger = logging.getLogger("canarymesh.alerts")


class AlertDispatcher:
    """Dispatches incident alert payloads to configured webhooks."""

    def __init__(self, webhook_urls: list[str] | None = None, http_client: httpx.AsyncClient | None = None):
        self.webhook_urls = webhook_urls or []
        self._client = http_client
        self._last_alert_time: float = 0.0

    async def dispatch_rollback_alert(
        self,
        reason: str,
        metrics: dict[str, Any],
        previous_weight: float,
    ) -> None:
        """Send incident alert payload to all configured webhook URLs."""
        if not self.webhook_urls:
            logger.info("Emergency rollback occurred: %s (no webhooks configured)", reason)
            return

        payload = {
            "event": "EMERGENCY_ROLLBACK",
            "service": "canarymesh",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "reason": reason,
            "previous_canary_weight": previous_weight,
            "current_canary_weight": 0.0,
            "metrics": metrics,
            # Format friendly message for Slack / Discord / Sentinel
            "text": f"🚨 [CanaryMesh Alert] Emergency Rollback Triggered: {reason}. Canary weight shifted from {previous_weight}% to 0%.",
        }

        client = self._client or httpx.AsyncClient(timeout=5.0)
        should_close = self._client is None

        try:
            for url in self.webhook_urls:
                try:
                    resp = await client.post(url, json=payload)
                    logger.info("Dispatched alert to %s, response status: %d", url, resp.status_code)
                except Exception as exc:
                    logger.warning("Failed to dispatch alert to %s: %s", url, exc)
        finally:
            if should_close:
                await client.aclose()
