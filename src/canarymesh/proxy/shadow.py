"""Traffic shadowing / dark launch engine with response diffing and parity inspection."""

import datetime
import logging
import random
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from canarymesh.config import UpstreamConfig
from canarymesh.proxy.stats import TelemetryManager

logger = logging.getLogger("canarymesh.shadow")


@dataclass
class ShadowDiffSample:
    """Detailed comparison record between Stable and Canary responses on shadowed traffic."""
    timestamp: str
    method: str
    path: str
    stable_status: int | None
    canary_status: int
    status_match: bool
    stable_latency_ms: float | None
    canary_latency_ms: float
    latency_delta_ms: float | None


class ShadowEngine:
    """Mirrors asynchronous clones of client requests to the Canary upstream in the background with diff analysis."""

    def __init__(
        self,
        canary_target: UpstreamConfig,
        telemetry: TelemetryManager,
        enabled: bool = False,
        shadow_percentage: float = 100.0,
        http_client: httpx.AsyncClient | None = None,
        max_diff_history: int = 50,
    ):
        self.canary_target = canary_target
        self.telemetry = telemetry
        self.enabled = enabled
        self.shadow_percentage = max(0.0, min(100.0, float(shadow_percentage)))
        self._client = http_client or httpx.AsyncClient(timeout=canary_target.timeout_seconds)
        self._owns_client = http_client is None

        self.total_shadowed_requests = 0
        self.total_shadow_errors = 0
        self.total_status_matches = 0
        self.max_diff_history = max_diff_history
        self.diff_history: list[ShadowDiffSample] = []

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
        stable_status: int | None = None,
        stable_latency_ms: float | None = None,
    ) -> None:
        """Execute mirrored background request against Canary target and record diff analysis."""
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

            canary_status = resp.status_code
            if canary_status >= 500:
                self.total_shadow_errors += 1
                logger.debug("Shadow request to Canary returned HTTP %d", canary_status)

            status_match = (stable_status == canary_status) if stable_status is not None else True
            if status_match:
                self.total_status_matches += 1

            latency_delta = round(latency_ms - stable_latency_ms, 2) if stable_latency_ms is not None else None

            sample = ShadowDiffSample(
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                method=method,
                path=path,
                stable_status=stable_status,
                canary_status=canary_status,
                status_match=status_match,
                stable_latency_ms=round(stable_latency_ms, 2) if stable_latency_ms is not None else None,
                canary_latency_ms=round(latency_ms, 2),
                latency_delta_ms=latency_delta,
            )

            self.diff_history.append(sample)
            if len(self.diff_history) > self.max_diff_history:
                self.diff_history.pop(0)

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self.total_shadow_errors += 1
            self.telemetry.record("canary", 502, latency_ms)
            logger.debug("Shadow request to Canary failed: %s", exc)

            sample = ShadowDiffSample(
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                method=method,
                path=path,
                stable_status=stable_status,
                canary_status=502,
                status_match=False,
                stable_latency_ms=round(stable_latency_ms, 2) if stable_latency_ms is not None else None,
                canary_latency_ms=round(latency_ms, 2),
                latency_delta_ms=None,
            )
            self.diff_history.append(sample)
            if len(self.diff_history) > self.max_diff_history:
                self.diff_history.pop(0)

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
        parity_rate = (
            round((self.total_status_matches / self.total_shadowed_requests) * 100.0, 1)
            if self.total_shadowed_requests > 0
            else 100.0
        )

        return {
            "enabled": self.enabled,
            "shadow_percentage": self.shadow_percentage,
            "canary_url": self.canary_target.url,
            "total_shadowed_requests": self.total_shadowed_requests,
            "total_shadow_errors": self.total_shadow_errors,
            "parity_rate_percent": parity_rate,
            "recent_diffs": [asdict(d) for d in self.diff_history[-10:]],
        }

    async def close(self) -> None:
        """Close HTTP client if owned."""
        if self._owns_client and self._client:
            await self._client.aclose()
