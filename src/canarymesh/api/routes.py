"""REST endpoints for the CanaryMesh control plane."""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from canarymesh.api.metrics import generate_prometheus_metrics
from canarymesh.config import PathRoutingRule
from canarymesh.controller.health_prober import ActiveHealthProber
from canarymesh.controller.post_mortem import PostMortemEngine
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager


class WeightUpdateRequest(BaseModel):
    weight: float = Field(..., ge=0.0, le=100.0, description="Target canary weight percentage")


class ScenarioLoadRequest(BaseModel):
    scenario_path: str = Field(..., description="Path to YAML scenario file")


class ShadowUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="Toggle traffic shadowing to Canary")
    percentage: float = Field(default=100.0, ge=0.0, le=100.0, description="Mirror traffic percentage")


class PathRuleCreateRequest(BaseModel):
    path_prefix: str = Field(..., description="URL path prefix e.g. /api/v2/")
    target: str = Field(default="canary", description="Upstream target: canary or stable")


def create_api_router(
    traffic_router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
    rollout: RolloutEngine,
    health_prober: ActiveHealthProber | None = None,
    shadow_engine: ShadowEngine | None = None,
    post_mortem: PostMortemEngine | None = None,
) -> APIRouter:
    """Create and bind REST API router to operational components."""
    root_router = APIRouter()
    router = APIRouter(prefix="/api/v1/canary")
    static_dir = Path(__file__).parent / "static"
    index_html_path = static_dir / "index.html"

    index_content = (
        index_html_path.read_text(encoding="utf-8")
        if index_html_path.exists()
        else "<h1>CanaryMesh UI not found</h1>"
    )

    @root_router.get("/healthz")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "canarymesh-control-plane"}

    @root_router.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return generate_prometheus_metrics(traffic_router, telemetry, guard)

    @root_router.get("/ui", response_class=HTMLResponse)
    async def web_ui() -> HTMLResponse:
        """Serve embedded single-page operations dashboard."""
        return HTMLResponse(content=index_content)

    @router.get("/status")
    async def get_status() -> dict[str, Any]:
        return {
            "weights": {
                "canary": traffic_router.canary_weight,
                "stable": 100.0 - traffic_router.canary_weight,
            },
            "guard": guard.get_status(),
            "rollout": rollout.get_status(),
            "telemetry": telemetry.get_snapshot(),
            "shadow": shadow_engine.get_status() if shadow_engine else None,
            "health": health_prober.get_status() if health_prober else None,
        }

    @router.post("/weight")
    async def update_weight(payload: WeightUpdateRequest) -> dict[str, Any]:
        traffic_router.set_weight(payload.weight)
        return {
            "status": "success",
            "canary_weight": traffic_router.canary_weight,
            "stable_weight": 100.0 - traffic_router.canary_weight,
        }

    @router.post("/abort")
    async def abort_canary() -> dict[str, Any]:
        trip_event = await guard.trip("Manual emergency abort triggered via control API")
        await rollout.abort("Manual emergency abort triggered via control API")
        return {
            "status": "aborted",
            "canary_weight": 0.0,
            "event": trip_event,
        }

    @router.post("/promote")
    async def promote_canary() -> dict[str, Any]:
        rollout.promote()
        traffic_router.set_weight(100.0)
        return {
            "status": "promoted",
            "canary_weight": 100.0,
        }

    @router.post("/guard/reset")
    async def reset_guard() -> dict[str, Any]:
        guard.reset()
        return {"status": "guard_reset_healthy"}

    @router.post("/shadow")
    async def update_shadow(payload: ShadowUpdateRequest) -> dict[str, Any]:
        if not shadow_engine:
            raise HTTPException(status_code=400, detail="Shadow engine is not configured")
        shadow_engine.update_config(payload.enabled, payload.percentage)
        return shadow_engine.get_status()

    @router.get("/shadow")
    async def get_shadow() -> dict[str, Any]:
        if not shadow_engine:
            return {"enabled": False, "configured": False}
        return shadow_engine.get_status()

    @router.get("/rules")
    async def get_rules() -> dict[str, Any]:
        return traffic_router.get_rules()

    @router.post("/rules/path")
    async def add_path_rule(payload: PathRuleCreateRequest) -> dict[str, Any]:
        rule = PathRoutingRule(path_prefix=payload.path_prefix, target=payload.target)
        rule_id = traffic_router.add_path_rule(rule)
        return {"status": "rule_added", "id": rule_id, "rule": rule.model_dump()}

    @router.delete("/rules/path/{rule_id}")
    async def delete_path_rule(rule_id: str) -> dict[str, Any]:
        removed = traffic_router.remove_path_rule(rule_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Path rule not found")
        return {"status": "rule_deleted", "id": rule_id}

    @router.get("/incidents")
    async def get_incidents() -> dict[str, Any]:
        if post_mortem:
            return {"incidents": post_mortem.get_incidents()}
        return {"incidents": []}

    @router.get("/health")
    async def get_upstream_health() -> dict[str, Any]:
        if health_prober:
            return health_prober.get_status()
        return {"configured": False}

    @router.post("/rollout/start")
    async def start_rollout(payload: ScenarioLoadRequest | None = None) -> dict[str, Any]:
        if payload and payload.scenario_path:
            rollout.load_scenario(payload.scenario_path)
        await rollout.start()
        return {"status": "rollout_started", "state": rollout.get_status()}

    @router.post("/rollout/pause")
    async def pause_rollout() -> dict[str, Any]:
        rollout.pause()
        return {"status": "rollout_paused"}

    @router.post("/rollout/resume")
    async def resume_rollout() -> dict[str, Any]:
        rollout.resume()
        return {"status": "rollout_resumed"}

    @router.get("/live")
    async def live_stream():
        """Server-Sent Events streaming telemetry snapshot every second."""
        async def event_generator():
            while True:
                data = {
                    "canary_weight": traffic_router.canary_weight,
                    "guard": guard.get_status(),
                    "rollout": rollout.get_status(),
                    "telemetry": {
                        k: {
                            "total_requests": m.total_requests,
                            "rps": m.rps,
                            "status_2xx": m.status_2xx,
                            "status_5xx": m.status_5xx,
                            "error_rate_percent": m.error_rate_percent,
                            "p50_ms": m.p50_ms,
                            "p99_ms": m.p99_ms,
                        }
                        for k, m in telemetry.get_snapshot().items()
                    },
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    root_router.include_router(router)
    return root_router
