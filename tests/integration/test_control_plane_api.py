"""Integration tests for CanaryMesh control plane REST API."""

import httpx
import pytest

from canarymesh.api.app import create_control_app
from canarymesh.config import CanaryMeshConfig, UpstreamConfig
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager


@pytest.fixture
def control_client():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=10.0,
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    guard = RollbackGuard(router=router, telemetry=telemetry, sla=cfg.sla)
    rollout = RolloutEngine(router=router, guard=guard)
    app = create_control_app(router, telemetry, guard, rollout)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_api_status_and_healthz(control_client):
    async with control_client as client:
        # Health check
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Status
        resp = await client.get("/api/v1/canary/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["weights"]["canary"] == 10.0
        assert data["weights"]["stable"] == 90.0
        assert data["guard"]["state"] == "HEALTHY"


@pytest.mark.asyncio
async def test_api_update_weight(control_client):
    async with control_client as client:
        resp = await client.post("/api/v1/canary/weight", json={"weight": 42.5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["canary_weight"] == 42.5
        assert data["stable_weight"] == 57.5

        # Check status reflects update
        resp = await client.get("/api/v1/canary/status")
        assert resp.json()["weights"]["canary"] == 42.5


@pytest.mark.asyncio
async def test_api_emergency_abort_and_promote(control_client):
    async with control_client as client:
        # Abort
        resp = await client.post("/api/v1/canary/abort")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "aborted"
        assert data["canary_weight"] == 0.0

        # Promote
        resp = await client.post("/api/v1/canary/promote")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "promoted"
        assert data["canary_weight"] == 100.0


@pytest.mark.asyncio
async def test_api_metrics_exposition(control_client):
    async with control_client as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        assert "canarymesh_traffic_weight" in text
        assert "canarymesh_requests_total" in text
        assert "canarymesh_guard_healthy" in text
