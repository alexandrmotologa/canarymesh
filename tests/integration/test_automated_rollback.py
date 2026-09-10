"""Integration tests verifying automated rollback upon canary fault injection."""

import httpx
import pytest

from canarymesh.config import CanaryMeshConfig, SlaThresholds, UpstreamConfig
from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.proxy.app import create_proxy_app
from canarymesh.proxy.forwarder import StreamingForwarder
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager
from canarymesh.simulator.mock_services import CanaryState, create_mock_v1_app, create_mock_v2_app


@pytest.fixture
def test_environment():
    # Setup mock apps
    v1_app = create_mock_v1_app()
    canary_state = CanaryState()
    v2_app = create_mock_v2_app(canary_state)

    # In-memory transports for mock apps
    v1_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=v1_app), base_url="http://mock-stable")
    v2_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=v2_app), base_url="http://mock-canary")

    class CombinedMockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if "mock-canary" in str(request.url):
                return await v2_client.send(request, stream=True)
            return await v1_client.send(request, stream=True)

    mock_client = httpx.AsyncClient(transport=CombinedMockTransport())

    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://mock-stable"),
        canary=UpstreamConfig(name="canary", url="http://mock-canary"),
        initial_canary_weight=50.0,
        sla=SlaThresholds(
            max_error_rate_percent=10.0,
            max_p99_latency_ms=250.0,
            min_sample_size=5,
        ),
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    forwarder = StreamingForwarder(router, telemetry, http_client=mock_client)
    guard = RollbackGuard(router, telemetry, cfg.sla)
    proxy_app = create_proxy_app(forwarder)

    return {
        "router": router,
        "telemetry": telemetry,
        "forwarder": forwarder,
        "guard": guard,
        "canary_state": canary_state,
        "proxy_app": proxy_app,
        "mock_client": mock_client,
        "v1_client": v1_client,
        "v2_client": v2_client,
    }


@pytest.mark.asyncio
async def test_automated_rollback_end_to_end(test_environment):
    env = test_environment
    router: TrafficRouter = env["router"]
    guard: RollbackGuard = env["guard"]
    canary_state: CanaryState = env["canary_state"]
    proxy_app = env["proxy_app"]

    # Initial state: 50% canary weight
    assert router.canary_weight == 50.0

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy_app), base_url="http://proxy"
    ) as client:
        # 1. Send 10 healthy requests directly forced to canary
        for _ in range(10):
            resp = await client.get("/api/v1/orders", headers={"x-canary": "true"})
            assert resp.status_code == 200
            assert resp.headers.get("x-canary-routed") == "canary"

        # Guard evaluate should be healthy
        await guard.evaluate()
        assert guard.state == GuardState.HEALTHY
        assert router.canary_weight == 50.0

        # 2. Inject faults into Canary (100% error rate on canary)
        canary_state.inject_errors = True
        canary_state.error_rate_percent = 100.0

        # Send 10 requests to canary
        for _ in range(10):
            resp = await client.get("/api/v1/orders", headers={"x-canary": "true"})
            assert resp.status_code == 500
            assert resp.headers.get("x-canary-routed") == "canary"

        # 3. Guard evaluates telemetry
        trip_event = await guard.evaluate()
        assert trip_event is not None
        assert guard.state == GuardState.TRIPPED

        # 4. Assert emergency rollback took effect immediately
        assert router.canary_weight == 0.0

        # 5. Subsequent normal requests (without forced headers) route 100% to Stable
        for i in range(20):
            resp = await client.get("/api/v1/orders", cookies={"canary_session": f"user-{i}"})
            assert resp.status_code == 200
            assert resp.headers.get("x-canary-routed") == "stable"

    await env["mock_client"].aclose()
    await env["v1_client"].aclose()
    await env["v2_client"].aclose()
