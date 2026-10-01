"""Multi-channel alert dispatcher supporting Discord, Slack, Telegram, PagerDuty, and generic webhooks."""

import datetime
import logging
import urllib.parse
from typing import Any

import httpx

from canarymesh.controller.post_mortem import PostMortemEngine

logger = logging.getLogger("canarymesh.alerts")


class AlertDispatcher:
    """Dispatches formatted incident notifications to Discord, Slack, Telegram, PagerDuty, and webhook endpoints."""

    def __init__(
        self,
        webhook_urls: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        post_mortem_engine: PostMortemEngine | None = None,
    ):
        self.webhook_urls = webhook_urls or []
        self._client = http_client
        self.post_mortem_engine = post_mortem_engine or PostMortemEngine()
        self._last_alert_time: float = 0.0

    async def dispatch_rollback_alert(
        self,
        reason: str,
        metrics: dict[str, Any],
        previous_weight: float,
    ) -> None:
        """Format and dispatch incident alert payload to all registered webhook URLs."""
        # Record post-mortem report
        self.post_mortem_engine.record_incident(reason, previous_weight, metrics)

        if not self.webhook_urls:
            logger.info("Emergency rollback occurred: %s (no webhooks configured)", reason)
            return

        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        client = self._client or httpx.AsyncClient(timeout=5.0)
        should_close = self._client is None

        try:
            for url in self.webhook_urls:
                payload = self._build_payload(url, reason, previous_weight, metrics, now_iso)
                try:
                    resp = await client.post(url, json=payload)
                    logger.info("Dispatched alert to %s (status: %d)", url, resp.status_code)
                except Exception as exc:
                    logger.warning("Failed to dispatch alert to %s: %s", url, exc)
        finally:
            if should_close:
                await client.aclose()

    @staticmethod
    def _build_payload(
        url: str,
        reason: str,
        previous_weight: float,
        metrics: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        """Format payload specifically tailored for destination platform."""
        err_rate = metrics.get("error_rate_percent", 0.0)
        p99 = metrics.get("p99_ms", 0.0)
        total_reqs = metrics.get("total_requests", 0)

        # 1. Discord Webhook
        if "discord.com/api/webhooks" in url:
            return {
                "embeds": [
                    {
                        "title": "🚨 CanaryMesh Emergency Rollback",
                        "description": f"**Breach Reason**: {reason}\nCanary traffic has been immediately zeroed out.",
                        "color": 15673924,  # Bright Red
                        "fields": [
                            {"name": "Previous Weight", "value": f"{previous_weight:.1f}%", "inline": True},
                            {"name": "Current Weight", "value": "0.0%", "inline": True},
                            {"name": "5xx Error Rate", "value": f"{err_rate:.2f}%", "inline": True},
                            {"name": "p99 Latency", "value": f"{p99:.1f} ms", "inline": True},
                            {"name": "Sample Requests", "value": str(total_reqs), "inline": True},
                        ],
                        "footer": {"text": "CanaryMesh Edge Supervisor"},
                        "timestamp": timestamp,
                    }
                ]
            }

        # 2. Slack Block Kit Webhook
        if "hooks.slack.com" in url:
            return {
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "🚨 CanaryMesh Emergency Rollback", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*Reason:* {reason}\n*Action:* Shifted from *{previous_weight:.1f}%* to *0.0%*"},
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*5xx Error Rate:*\n{err_rate:.2f}%"},
                            {"type": "mrkdwn", "text": f"*p99 Latency:*\n{p99:.1f} ms"},
                            {"type": "mrkdwn", "text": f"*Sample Requests:*\n{total_reqs}"},
                            {"type": "mrkdwn", "text": f"*Timestamp:*\n{timestamp}"},
                        ],
                    },
                ]
            }

        # 3. Telegram Bot API
        if "api.telegram.org/bot" in url:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            chat_id = params.get("chat_id", [""])[0]
            tg_text = (
                f"🚨 <b>CanaryMesh Emergency Rollback</b>\n\n"
                f"<b>Reason:</b> {reason}\n"
                f"<b>Traffic Shift:</b> {previous_weight:.1f}% → 0.0%\n"
                f"<b>5xx Errors:</b> {err_rate:.2f}%\n"
                f"<b>p99 Latency:</b> {p99:.1f} ms\n"
                f"<b>Samples:</b> {total_reqs} requests\n"
                f"<i>Timestamp: {timestamp}</i>"
            )
            return {
                "chat_id": chat_id,
                "text": tg_text,
                "parse_mode": "HTML",
            }

        # 4. PagerDuty Events API v2
        if "events.pagerduty.com" in url:
            return {
                "routing_key": url.split("/")[-1] if "/" in url else "canarymesh",
                "event_action": "trigger",
                "payload": {
                    "summary": f"CanaryMesh Emergency Rollback: {reason}",
                    "severity": "critical",
                    "source": "canarymesh-edge",
                    "timestamp": timestamp,
                    "custom_details": {
                        "reason": reason,
                        "previous_weight": previous_weight,
                        "error_rate_percent": err_rate,
                        "p99_latency_ms": p99,
                        "total_requests": total_reqs,
                    },
                },
            }

        # 5. Generic JSON Webhook (Sentinel / Custom Receiver)
        return {
            "event": "EMERGENCY_ROLLBACK",
            "service": "canarymesh",
            "timestamp": timestamp,
            "reason": reason,
            "previous_canary_weight": previous_weight,
            "current_canary_weight": 0.0,
            "metrics": metrics,
            "text": f"🚨 [CanaryMesh Alert] Emergency Rollback: {reason}. Canary weight shifted from {previous_weight:.1f}% to 0.0%.",
        }
