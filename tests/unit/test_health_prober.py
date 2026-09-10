"""Unit tests for ActiveHealthProber and pre-flight health checks."""

import httpx
import pytest

from canarymesh.config import UpstreamConfig
from canarymesh.controller.health_prober import ActiveHealthProber


@pytest.fixture
def mock_health_transport():
    async def app_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "mock-stable" in url_str:
            return httpx.Response(200, json={"status": "ok"})
        elif "mock-canary" in url_str:
            if "fail" in url_str:
                return httpx.Response(503, json={"status": "unavailable"})
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    class CustomTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return await app_handler(request)

    return httpx.AsyncClient(transport=CustomTransport())


@pytest.mark.asyncio
async def test_prober_healthy_flow(mock_health_transport):
    stable_cfg = UpstreamConfig(name="stable", url="http://mock-stable")
    canary_cfg = UpstreamConfig(name="canary", url="http://mock-canary")

    prober = ActiveHealthProber(
        stable_cfg,
        canary_cfg,
        probe_interval_seconds=0.1,
        failure_threshold=2,
        http_client=mock_health_transport,
    )

    await prober.probe_all()
    assert prober.is_stable_healthy() is True
    assert prober.is_canary_healthy() is True
    assert prober.stable_health.consecutive_successes == 1
    assert prober.canary_health.consecutive_successes == 1


@pytest.mark.asyncio
async def test_prober_failure_threshold(mock_health_transport):
    stable_cfg = UpstreamConfig(name="stable", url="http://mock-stable")
    canary_cfg = UpstreamConfig(name="canary", url="http://mock-canary", health_path="/healthz-fail")

    prober = ActiveHealthProber(
        stable_cfg,
        canary_cfg,
        probe_interval_seconds=0.1,
        failure_threshold=2,
        http_client=mock_health_transport,
    )

    # First probe: 1 failure, threshold=2 so still technically healthy
    await prober.probe_all()
    assert prober.canary_health.consecutive_failures == 1
    assert prober.is_canary_healthy() is True

    # Second probe: reaches threshold=2, becomes UNHEALTHY
    await prober.probe_all()
    assert prober.canary_health.consecutive_failures == 2
    assert prober.is_canary_healthy() is False

    status = prober.get_status()
    assert status["canary"]["is_healthy"] is False
    assert "HTTP 503" in status["canary"]["last_error_message"]
