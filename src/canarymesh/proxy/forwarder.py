"""Asynchronous streaming reverse proxy forwarder using HTTPX."""

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from canarymesh.proxy.router import RouteDecision, TrafficRouter
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager

# Standard hop-by-hop headers to strip before forwarding
HOP_BY_HOP_HEADERS: set[str] = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


class StreamingForwarder:
    """Forwards incoming HTTP requests to resolved upstream targets with telemetry interception."""

    def __init__(
        self,
        router: TrafficRouter,
        telemetry: TelemetryManager,
        http_client: httpx.AsyncClient | None = None,
        shadow_engine: ShadowEngine | None = None,
    ):
        self.router = router
        self.telemetry = telemetry
        self.shadow_engine = shadow_engine
        self._client = http_client or httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=100,
                max_connections=500,
                keepalive_expiry=30.0,
            ),
            follow_redirects=False,
        )

    async def close(self) -> None:
        """Close internal HTTP client resources."""
        if self.shadow_engine:
            await self.shadow_engine.close()
        await self._client.aclose()

    async def forward(self, request: Request) -> Response:
        """Stream request to upstream and stream response back to client."""
        headers_dict = {k.lower(): v for k, v in request.headers.items()}
        cookies_dict = dict(request.cookies)
        query_dict = dict(request.query_params)
        path = request.url.path
        query = request.url.query

        decision: RouteDecision = self.router.route(headers_dict, cookies_dict, query_dict, path=path)
        target_upstream = decision.target
        upstream_name = decision.upstream_name

        # Construct target URL
        target_url = f"{target_upstream.url.rstrip('/')}{path}"
        if query:
            target_url += f"?{query}"

        # Clean headers to forward
        forward_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }
        client_host = request.client.host if request.client else "unknown"
        forward_headers["x-forwarded-for"] = client_host
        forward_headers["x-forwarded-proto"] = request.url.scheme
        forward_headers["x-canary-routed"] = upstream_name

        start_time = time.perf_counter()

        try:
            # Handle payload for methods with body
            req_content = None
            body_bytes = None
            if request.method not in ("GET", "HEAD"):
                if self.shadow_engine and self.shadow_engine.should_shadow() and upstream_name == "stable":
                    body_bytes = await request.body()
                    req_content = body_bytes
                else:
                    req_content = request.stream()

            # Trigger background shadow mirroring if enabled
            if upstream_name == "stable" and self.shadow_engine and self.shadow_engine.should_shadow():
                asyncio.create_task(
                    self.shadow_engine.mirror_request(
                        method=request.method,
                        path=path,
                        query=query,
                        headers=forward_headers,
                        body_bytes=body_bytes,
                    )
                )

            upstream_response = await self._client.send(
                self._client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=forward_headers,
                    content=req_content,
                    timeout=target_upstream.timeout_seconds,
                ),
                stream=True,
            )

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            status_code = upstream_response.status_code

            # Record telemetry
            self.telemetry.record(upstream_name, status_code, latency_ms)

            # Build response headers, removing hop-by-hop headers
            response_headers: dict[str, str] = {
                k: v for k, v in upstream_response.headers.items()
                if k.lower() not in HOP_BY_HOP_HEADERS
            }
            response_headers["x-canary-routed"] = upstream_name
            response_headers["x-canary-latency-ms"] = f"{latency_ms:.2f}"

            async def body_stream() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream_response.aiter_bytes():
                        yield chunk
                finally:
                    await upstream_response.aclose()

            resp = StreamingResponse(
                body_stream(),
                status_code=status_code,
                headers=response_headers,
                media_type=upstream_response.headers.get("content-type"),
            )

            # Attach sticky session cookie if newly generated
            if decision.session_id and decision.is_new_session:
                resp.set_cookie(
                    key=self.router.config.sticky_cookie_name,
                    value=decision.session_id,
                    max_age=self.router.config.sticky_cookie_ttl_seconds,
                    path="/",
                    samesite="lax",
                )

            return resp

        except httpx.TimeoutException:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.telemetry.record(upstream_name, 504, latency_ms)
            return Response(
                content=b'{"error": "Gateway Timeout", "upstream": "' + upstream_name.encode() + b'"}',
                status_code=504,
                media_type="application/json",
                headers={"x-canary-routed": upstream_name},
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.telemetry.record(upstream_name, 502, latency_ms)
            return Response(
                content=b'{"error": "Bad Gateway", "details": "' + str(exc).encode() + b'"}',
                status_code=502,
                media_type="application/json",
                headers={"x-canary-routed": upstream_name},
            )
