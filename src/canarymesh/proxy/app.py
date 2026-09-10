"""FastAPI application factory for the edge reverse proxy data plane."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from canarymesh.proxy.forwarder import StreamingForwarder


def create_proxy_app(forwarder: StreamingForwarder) -> FastAPI:
    """Instantiate and configure the edge streaming reverse proxy data plane application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await forwarder.close()

    app = FastAPI(
        title="CanaryMesh Edge Proxy",
        description="High-throughput asynchronous streaming reverse proxy",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def proxy_catch_all(request: Request, full_path: str) -> Response:
        return await forwarder.forward(request)

    return app
