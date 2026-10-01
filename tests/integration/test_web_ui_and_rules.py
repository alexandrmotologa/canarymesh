"""Integration tests for Web UI endpoint, dynamic path/header rules, SLA config, and shadow API."""

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
    return client, post_mortem, shadow_engine, router, guard


@pytest.mark.asyncio
async def test_web_ui_html_endpoint(api_test_client):
    client, _, _, _, _ = api_test_client
    async with client as c:
        resp = await c.get("/ui")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "CanaryMesh Console" in resp.text
        assert "telemetryChart" in resp.text


@pytest.mark.asyncio
async def test_dynamic_path_and_header_rules_api(api_test_client):
    client, _, _, _router, _ = api_test_client
    async with client as c:
        # 1. Add path rule
        resp = await c.post("/api/v1/canary/rules/path", json={"path_prefix": "/checkout", "target": "canary"})
        assert resp.status_code == 200
        data = resp.json()
        path_rule_id = data["id"]
        assert data["rule"]["path_prefix"] == "/checkout"

        # 2. Add header rule
        h_resp = await c.post(
            "/api/v1/canary/rules/header",
            json={"header_name": "x-user-tier", "header_pattern": "beta.*", "target": "canary"},
        )
        assert h_resp.status_code == 200
        h_data = h_resp.json()
        header_rule_id = h_data["id"]
        assert h_data["rule"]["header_name"] == "x-user-tier"

        # 3. Verify rules in router
        rules_resp = await c.get("/api/v1/canary/rules")
        assert rules_resp.status_code == 200
        rules_data = rules_resp.json()
        assert any(r["id"] == path_rule_id for r in rules_data["path_rules"])
        assert any(r["id"] == header_rule_id for r in rules_data["header_rules"])

        # 4. Delete header rule and path rule
        del_h = await c.delete(f"/api/v1/canary/rules/header/{header_rule_id}")
        assert del_h.status_code == 200
        assert del_h.json()["status"] == "header_rule_deleted"

        del_p = await c.delete(f"/api/v1/canary/rules/path/{path_rule_id}")
        assert del_p.status_code == 200
        assert del_p.json()["status"] == "rule_deleted"


@pytest.mark.asyncio
async def test_sla_config_api(api_test_client):
    client, _, _, _, guard = api_test_client
    async with client as c:
        # Get SLA
        resp = await c.get("/api/v1/canary/sla")
        assert resp.status_code == 200
        data = resp.json()
        assert "max_error_rate_percent" in data

        # Update SLA
        update_resp = await c.post(
            "/api/v1/canary/sla",
            json={
                "max_error_rate_percent": 2.5,
                "max_p99_latency_ms": 400.0,
                "max_relative_latency_ratio": 2.5,
            },
        )
        assert update_resp.status_code == 200
        assert guard.sla.max_error_rate_percent == 2.5
        assert guard.sla.max_p99_latency_ms == 400.0
        assert guard.sla.max_relative_latency_ratio == 2.5


@pytest.mark.asyncio
async def test_shadow_and_diff_api(api_test_client):
    client, _, shadow_engine, _, _ = api_test_client
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

        # Check diff endpoint
        diff_resp = await c.get("/api/v1/canary/shadow/diff")
        assert diff_resp.status_code == 200
        assert "parity_rate_percent" in diff_resp.json()


@pytest.mark.asyncio
async def test_incidents_and_download_api(api_test_client):
    client, post_mortem, _, _, _ = api_test_client
    report = post_mortem.record_incident("Test SLA breach", 20.0, {"error_rate_percent": 15.0, "p99_ms": 220.0})

    async with client as c:
        # List incidents
        resp = await c.get("/api/v1/canary/incidents")
        assert resp.status_code == 200
        incidents = resp.json()["incidents"]
        assert len(incidents) == 1
        assert incidents[0]["previous_canary_weight"] == 20.0

        # View specific incident
        inc_resp = await c.get(f"/api/v1/canary/incidents/{report.incident_id}")
        assert inc_resp.status_code == 200
        assert inc_resp.json()["incident"]["incident_id"] == report.incident_id

        # Download markdown
        dl_resp = await c.get(f"/api/v1/canary/incidents/{report.incident_id}/download")
        assert dl_resp.status_code == 200
        assert "text/markdown" in dl_resp.headers["content-type"]
        assert "Incident Post-Mortem" in dl_resp.text
