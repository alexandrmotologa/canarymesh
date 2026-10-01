"""FastAPI application factory for the edge reverse proxy data plane."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket

from canarymesh.proxy.forwarder import StreamingForwarder

logger = logging.getLogger("canarymesh.proxy")


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

    @app.websocket("/{full_path:path}")
    async def proxy_websocket(websocket: WebSocket, full_path: str):
        headers_dict = {k.lower(): v for k, v in websocket.headers.items()}
        cookies_dict = dict(websocket.cookies)
        query_dict = dict(websocket.query_params)
        path = f"/{full_path}"

        decision = forwarder.router.route(headers_dict, cookies_dict, query_dict, path=path)
        target_upstream = decision.target
        upstream_ws = target_upstream.url.replace("http://", "ws://").replace("https://", "wss://")
        target_ws_url = f"{upstream_ws.rstrip('/')}{path}"
        if websocket.url.query:
            target_ws_url += f"?{websocket.url.query}"

        await websocket.accept()

        try:
            import websockets
            async with websockets.connect(target_ws_url) as server_ws:
                async def client_to_server():
                    try:
                        while True:
                            data = await websocket.receive()
                            if "text" in data:
                                await server_ws.send(data["text"])
                            elif "bytes" in data:
                                await server_ws.send(data["bytes"])
                    except Exception as exc:
                        logger.debug("WebSocket client-to-server disconnected: %s", exc)

                async def server_to_client():
                    try:
                        async for msg in server_ws:
                            if isinstance(msg, str):
                                await websocket.send_text(msg)
                            else:
                                await websocket.send_bytes(msg)
                    except Exception as exc:
                        logger.debug("WebSocket server-to-client disconnected: %s", exc)

                await asyncio.gather(client_to_server(), server_to_client())
        except Exception as exc:
            logger.debug("WebSocket upstream connection failed: %s", exc)
        finally:
            try:
                await websocket.close()
            except Exception as exc:
                logger.debug("Error closing websocket: %s", exc)

    return app
