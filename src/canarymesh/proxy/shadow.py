"""Traffic shadowing / dark launch engine for zero-risk pre-testing on Canary."""

import logging
import random
import time
from typing import Any

import httpx

from canarymesh.config import UpstreamConfig
from canarymesh.proxy.stats import TelemetryManager

logger = logging.getLogger("canarymesh.shadow")


class ShadowEngine:
    """Mirrors asynchronous clones of client requests to the Canary upstream in the background."""

    def __init__(
        self,
        canary_target: UpstreamConfig,
        telemetry: TelemetryManager,
        enabled: bool = False,
        shadow_percentage: float = 100.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.canary_target = canary_target
        self.telemetry = telemetry
        self.enabled = enabled
        self.shadow_percentage = max(0.0, min(100.0, float(shadow_percentage)))
        self._client = http_client or httpx.AsyncClient(timeout=canary_target.timeout_seconds)
        self._owns_client = http_client is None

        self.total_shadowed_requests = 0
        self.total_shadow_errors = 0

    def should_shadow(self) -> bool:
        """Determine if an incoming request should be mirrored to Canary."""
        if not self.enabled or self.shadow_percentage <= 0.0:
            return False
        if self.shadow_percentage >= 100.0:
            return True
        return random.uniform(0.0, 100.0) < self.shadow_percentage

    async def mirror_request(
        self,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body_bytes: bytes | None = None,
    ) -> None:
        """Execute mirrored background request against Canary target."""
        target_url = f"{self.canary_target.url.rstrip('/')}{path}"
        if query:
            target_url += f"?{query}"

        # Clean headers and mark as shadow
        shadow_headers = {
            k: v for k, v in headers.items()
            if k.lower() not in ("host", "content-length", "connection")
        }
        shadow_headers["x-canary-shadow"] = "true"
        shadow_headers["x-canary-routed"] = "canary-shadow"

        start_time = time.perf_counter()
        self.total_shadowed_requests += 1

        try:
            resp = await self._client.request(
                method=method,
                url=target_url,
                headers=shadow_headers,
                content=body_bytes,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.telemetry.record("canary", resp.status_code, latency_ms)

            if resp.status_code >= 500:
                self.total_shadow_errors += 1
                logger.debug("Shadow request to Canary returned HTTP %d", resp.status_code)

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.total_shadow_errors += 1
            self.telemetry.record("canary", 502, latency_ms)
            logger.debug("Shadow request to Canary failed: %s", exc)

    def update_config(self, enabled: bool, percentage: float = 100.0) -> None:
        """Dynamically update shadow settings."""
        self.enabled = enabled
        self.shadow_percentage = max(0.0, min(100.0, float(percentage)))
        logger.info(
            "Traffic shadowing updated: enabled=%s, percentage=%.1f%%",
            self.enabled,
            self.shadow_percentage,
        )

    def get_status(self) -> dict[str, Any]:
        """Return status payload for monitoring and APIs."""
        return {
            "enabled": self.enabled,
            "shadow_percentage": self.shadow_percentage,
            "canary_url": self.canary_target.url,
            "total_shadowed_requests": self.total_shadowed_requests,
            "total_shadow_errors": self.total_shadow_errors,
        }

    async def close(self) -> None:
        """Close HTTP client if owned."""
        if self._owns_client and self._client:
            await self._client.aclose()
