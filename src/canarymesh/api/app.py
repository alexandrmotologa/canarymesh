"""FastAPI factory for the CanaryMesh control plane."""


from fastapi import FastAPI

from canarymesh.api.routes import create_api_router
from canarymesh.controller.health_prober import ActiveHealthProber
from canarymesh.controller.post_mortem import PostMortemEngine
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager


def create_control_app(
    traffic_router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
    rollout: RolloutEngine,
    health_prober: ActiveHealthProber | None = None,
    shadow_engine: ShadowEngine | None = None,
    post_mortem: PostMortemEngine | None = None,
) -> FastAPI:
    """Instantiate and configure the FastAPI control plane application."""
    app = FastAPI(
        title="CanaryMesh Control Plane",
        description="Dynamic traffic splitting and automated rollback controller API",
        version="0.1.0",
    )

    api_router = create_api_router(
        traffic_router=traffic_router,
        telemetry=telemetry,
        guard=guard,
        rollout=rollout,
        health_prober=health_prober,
        shadow_engine=shadow_engine,
        post_mortem=post_mortem,
    )
    app.include_router(api_router)
    return app
