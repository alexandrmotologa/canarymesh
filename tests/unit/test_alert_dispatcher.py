"""Unit tests for multi-channel alert dispatcher."""

import httpx
import pytest

from canarymesh.controller.alert_dispatcher import AlertDispatcher
from canarymesh.controller.post_mortem import PostMortemEngine


@pytest.fixture
def mock_webhook_client():
    captured_payloads = {}

    async def app_handler(request: httpx.Request) -> httpx.Response:
        import json
        url_str = str(request.url)
        captured_payloads[url_str] = json.loads(request.content)
        return httpx.Response(200, json={"status": "received"})

    class CustomTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return await app_handler(request)

    client = httpx.AsyncClient(transport=CustomTransport())
    return client, captured_payloads


@pytest.mark.asyncio
async def test_alert_dispatcher_formatting(mock_webhook_client):
    client, payloads = mock_webhook_client

    discord_url = "https://discord.com/api/webhooks/123/token"
    slack_url = "https://hooks.slack.com/services/T00/B00/X00"
    generic_url = "https://sentinel.internal/webhook"

    post_mortem = PostMortemEngine()
    dispatcher = AlertDispatcher(
        webhook_urls=[discord_url, slack_url, generic_url],
        http_client=client,
        post_mortem_engine=post_mortem,
    )

    sample_metrics = {
        "error_rate_percent": 12.5,
        "p99_ms": 420.0,
        "total_requests": 80,
        "status_5xx": 10,
    }

    await dispatcher.dispatch_rollback_alert(
        reason="Error rate 12.5% breached threshold",
        metrics=sample_metrics,
        previous_weight=30.0,
    )

    # 1. Check Discord formatting
    discord_payload = payloads[discord_url]
    assert "embeds" in discord_payload
    assert discord_payload["embeds"][0]["color"] == 15673924
    assert len(discord_payload["embeds"][0]["fields"]) == 5

    # 2. Check Slack formatting
    slack_payload = payloads[slack_url]
    assert "blocks" in slack_payload
    assert slack_payload["blocks"][0]["type"] == "header"

    # 3. Check Generic formatting
    generic_payload = payloads[generic_url]
    assert generic_payload["event"] == "EMERGENCY_ROLLBACK"
    assert generic_payload["previous_canary_weight"] == 30.0

    # 4. Check Post-Mortem record
    assert len(post_mortem.incidents) == 1
    assert post_mortem.incidents[0].failed_requests_count == 10
    assert "Incident Post-Mortem" in post_mortem.incidents[0].markdown_summary
