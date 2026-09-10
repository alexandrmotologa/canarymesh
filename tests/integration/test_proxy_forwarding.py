"""Integration tests for edge proxy request forwarding and header propagation."""

import httpx
import pytest

from canarymesh.config import CanaryMeshConfig, HeaderRoutingRule, UpstreamConfig
from canarymesh.proxy.app import create_proxy_app
from canarymesh.proxy.forwarder import StreamingForwarder
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager
from canarymesh.simulator.mock_services import CanaryState, create_mock_v1_app, create_mock_v2_app


@pytest.fixture
def proxy_client():
    v1_app = create_mock_v1_app()
    canary_state = CanaryState()
    v2_app = create_mock_v2_app(canary_state)

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
        initial_canary_weight=0.0,
        header_rules=[
            HeaderRoutingRule(header_name="X-Team", header_pattern="^dev.*", target="canary")
        ],
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    forwarder = StreamingForwarder(router, telemetry, http_client=mock_client)
    proxy_app = create_proxy_app(forwarder)

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy_app), base_url="http://proxy")


@pytest.mark.asyncio
async def test_proxy_default_routes_to_stable(proxy_client):
    async with proxy_client as client:
        resp = await client.get("/api/v1/products")
        assert resp.status_code == 200
        assert resp.headers.get("x-canary-routed") == "stable"
        assert "x-canary-latency-ms" in resp.headers
        data = resp.json()
        assert data["version"] == "v1.0.0"


@pytest.mark.asyncio
async def test_proxy_custom_header_rule_routing(proxy_client):
    async with proxy_client as client:
        resp = await client.get("/api/v1/products", headers={"x-team": "dev-ops"})
        assert resp.status_code == 200
        assert resp.headers.get("x-canary-routed") == "canary"
        data = resp.json()
        assert data["version"] == "v2.0.0-rc1"


@pytest.mark.asyncio
async def test_proxy_query_param_routing(proxy_client):
    async with proxy_client as client:
        resp = await client.get("/api/v1/products?canary=1")
        assert resp.status_code == 200
        assert resp.headers.get("x-canary-routed") == "canary"
        data = resp.json()
        assert data["version"] == "v2.0.0-rc1"
