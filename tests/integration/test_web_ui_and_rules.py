"""Integration tests for Web UI endpoint, dynamic path rules, and shadow API."""

import httpx
import pytest

from canarymesh.api.app import create_control_app
from canarymesh.config import CanaryMeshConfig, UpstreamConfig
from canarymesh.controller.health_prober import ActiveHealthProber
from canarymesh.controller.post_mortem import PostMortemEngine
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager


@pytest.fixture
def api_test_client():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=0.0,
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    post_mortem = PostMortemEngine()
    health_prober = ActiveHealthProber(cfg.stable, cfg.canary)
    shadow_engine = ShadowEngine(cfg.canary, telemetry, enabled=False)
    guard = RollbackGuard(router=router, telemetry=telemetry, sla=cfg.sla, health_prober=health_prober)
    rollout = RolloutEngine(router=router, guard=guard, health_prober=health_prober)

    app = create_control_app(
        traffic_router=router,
        telemetry=telemetry,
        guard=guard,
        rollout=rollout,
        health_prober=health_prober,
        shadow_engine=shadow_engine,
        post_mortem=post_mortem,
    )

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, post_mortem, shadow_engine, router


@pytest.mark.asyncio
async def test_web_ui_html_endpoint(api_test_client):
    client, _, _, _ = api_test_client
    async with client as c:
        resp = await c.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "CanaryMesh Console" in resp.text
        assert "telemetryChart" in resp.text


@pytest.mark.asyncio
async def test_dynamic_path_rules_api(api_test_client):
    client, _, _, _router = api_test_client
    async with client as c:
        # 1. Add path rule
        resp = await c.post("/api/v1/canary/rules/path", json={"path_prefix": "/checkout", "target": "canary"})
        assert resp.status_code == 200
        data = resp.json()
        rule_id = data["id"]
        assert data["rule"]["path_prefix"] == "/checkout"

        # 2. Verify rule in router
        rules_resp = await c.get("/api/v1/canary/rules")
        assert rules_resp.status_code == 200
        rules_data = rules_resp.json()
        assert any(r["id"] == rule_id for r in rules_data["path_rules"])

        # 3. Delete path rule
        del_resp = await c.delete(f"/api/v1/canary/rules/path/{rule_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "rule_deleted"


@pytest.mark.asyncio
async def test_shadow_api(api_test_client):
    client, _, shadow_engine, _ = api_test_client
    async with client as c:
        # Check initial shadow status
        resp = await c.get("/api/v1/canary/shadow")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Enable shadow
        resp = await c.post("/api/v1/canary/shadow", json={"enabled": True, "percentage": 50.0})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True
        assert resp.json()["shadow_percentage"] == 50.0
        assert shadow_engine.enabled is True


@pytest.mark.asyncio
async def test_incidents_and_health_api(api_test_client):
    client, post_mortem, _, _ = api_test_client
    post_mortem.record_incident("Test SLA breach", 20.0, {"error_rate_percent": 15.0})

    async with client as c:
        # Incidents
        resp = await c.get("/api/v1/canary/incidents")
        assert resp.status_code == 200
        incidents = resp.json()["incidents"]
        assert len(incidents) == 1
        assert incidents[0]["previous_canary_weight"] == 20.0

        # Health
        h_resp = await c.get("/api/v1/canary/health")
        assert h_resp.status_code == 200
        assert "stable" in h_resp.json()
