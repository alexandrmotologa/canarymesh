"""REST endpoints for the CanaryMesh control plane."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from canarymesh.api.metrics import generate_prometheus_metrics
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager

router = APIRouter(prefix="/api/v1/canary")


class WeightUpdateRequest(BaseModel):
    weight: float = Field(..., ge=0.0, le=100.0, description="Target canary weight percentage")


class ScenarioLoadRequest(BaseModel):
    scenario_path: str = Field(..., description="Path to YAML scenario file")


def create_api_router(
    traffic_router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
    rollout: RolloutEngine,
) -> APIRouter:
    """Create and bind REST API router to operational components."""
    root_router = APIRouter()

    @root_router.get("/healthz")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "canarymesh-control-plane"}

    @root_router.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint() -> str:
        return generate_prometheus_metrics(traffic_router, telemetry, guard)

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
