"""Mock upstream HTTP services (v1 stable and v2 canary with fault injection)."""

import asyncio
import random
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_mock_v1_app() -> FastAPI:
    """Create a healthy v1 stable upstream application."""
    app = FastAPI(title="Mock Stable Service v1")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": "v1.0.0", "healthy": True}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def handle_request(request: Request, path: str):
        # Simulate realistic 10-25ms database / backend processing delay
        delay = random.uniform(0.010, 0.025)
        await asyncio.sleep(delay)
        return {
            "service": "order-service",
            "version": "v1.0.0",
            "upstream": "stable",
            "path": f"/{path}",
            "method": request.method,
            "status": "healthy",
            "timestamp": time.time(),
        }

    return app


class CanaryState:
    def __init__(self):
        self.inject_errors: bool = False
        self.error_rate_percent: float = 30.0
        self.latency_jitter_ms: float = 0.0


def create_mock_v2_app(state: CanaryState) -> FastAPI:
    """Create a v2 canary upstream application with controllable fault injection."""
    app = FastAPI(title="Mock Canary Service v2")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": "v2.0.0-rc1", "canary": True}

    @app.post("/fault/enable")
    async def enable_faults(error_rate: float = 30.0, jitter_ms: float = 0.0):
        state.inject_errors = True
        state.error_rate_percent = error_rate
        state.latency_jitter_ms = jitter_ms
        return {
            "status": "faults_enabled",
            "error_rate_percent": state.error_rate_percent,
            "jitter_ms": state.latency_jitter_ms,
        }

    @app.post("/fault/disable")
    async def disable_faults():
        state.inject_errors = False
        return {"status": "faults_disabled"}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def handle_request(request: Request, path: str):
        base_delay = random.uniform(0.008, 0.020)
        if state.latency_jitter_ms > 0:
            base_delay += state.latency_jitter_ms / 1000.0

        await asyncio.sleep(base_delay)

        # Inject 500 error if fault condition matches
        if state.inject_errors:
            roll = random.uniform(0.0, 100.0)
            if roll < state.error_rate_percent:
                return JSONResponse(
                    content={
                        "service": "order-service",
                        "version": "v2.0.0-rc1",
                        "upstream": "canary",
                        "error": "InternalServerError: NullPointerException in payment gateway adapter",
                        "code": 500,
                    },
                    status_code=500,
                )

        return {
            "service": "order-service",
            "version": "v2.0.0-rc1",
            "upstream": "canary",
            "path": f"/{path}",
            "method": request.method,
            "status": "healthy",
            "timestamp": time.time(),
        }

    return app


async def run_mock_servers(
    port_v1: int = 8081,
    port_v2: int = 8082,
    inject_errors: bool = False,
    error_rate: float = 30.0,
):
    """Run both mock upstreams concurrently."""
    v1_app = create_mock_v1_app()
    canary_state = CanaryState()
    canary_state.inject_errors = inject_errors
    canary_state.error_rate_percent = error_rate
    v2_app = create_mock_v2_app(canary_state)

    config_v1 = uvicorn.Config(v1_app, host="127.0.0.1", port=port_v1, log_level="warning")
    config_v2 = uvicorn.Config(v2_app, host="127.0.0.1", port=port_v2, log_level="warning")

    server_v1 = uvicorn.Server(config_v1)
    server_v2 = uvicorn.Server(config_v2)

    await asyncio.gather(server_v1.serve(), server_v2.serve())
