"""Unit tests for traffic shadowing and dark launching."""

import httpx
import pytest

from canarymesh.config import UpstreamConfig
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager


@pytest.fixture
def mock_shadow_transport():
    shadow_records = []

    async def app_handler(request: httpx.Request) -> httpx.Response:
        shadow_records.append({
            "url": str(request.url),
            "headers": dict(request.headers),
        })
        return httpx.Response(200, json={"status": "shadow_ok"})

    class CustomTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return await app_handler(request)

    client = httpx.AsyncClient(transport=CustomTransport())
    return client, shadow_records


@pytest.mark.asyncio
async def test_shadow_engine_mirroring(mock_shadow_transport):
    client, records = mock_shadow_transport
    canary_cfg = UpstreamConfig(name="canary", url="http://mock-canary")
    telemetry = TelemetryManager(window_size_seconds=60)

    shadow = ShadowEngine(
        canary_target=canary_cfg,
        telemetry=telemetry,
        enabled=True,
        shadow_percentage=100.0,
        http_client=client,
    )

    assert shadow.should_shadow() is True

    await shadow.mirror_request(
        method="POST",
        path="/api/v1/orders",
        query="ref=123",
        headers={"user-agent": "test-runner", "host": "proxy"},
        body_bytes=b'{"item": "book"}',
    )

    assert len(records) == 1
    assert records[0]["url"] == "http://mock-canary/api/v1/orders?ref=123"
    assert records[0]["headers"]["x-canary-shadow"] == "true"
    assert shadow.total_shadowed_requests == 1

    # Verify telemetry was recorded under canary
    snap = telemetry.canary.snapshot()
    assert snap.total_requests == 1
    assert snap.status_2xx == 1


def test_shadow_disabled_check():
    canary_cfg = UpstreamConfig(name="canary", url="http://mock-canary")
    telemetry = TelemetryManager()
    shadow = ShadowEngine(canary_target=canary_cfg, telemetry=telemetry, enabled=False)

    assert shadow.should_shadow() is False
    shadow.update_config(enabled=True, percentage=0.0)
    assert shadow.should_shadow() is False
