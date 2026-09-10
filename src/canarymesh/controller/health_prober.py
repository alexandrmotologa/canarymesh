"""Active health probing loop inspecting upstream /healthz endpoints."""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from canarymesh.config import UpstreamConfig

logger = logging.getLogger("canarymesh.prober")


@dataclass
class UpstreamHealth:
    """Current health state of an individual upstream target."""
    name: str
    target_url: str
    health_path: str
    is_healthy: bool = True
    last_status_code: int | None = None
    last_latency_ms: float = 0.0
    last_checked_timestamp: float | None = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error_message: str | None = None


class ActiveHealthProber:
    """Continuously probes upstream health endpoints in the background."""

    def __init__(
        self,
        stable_config: UpstreamConfig,
        canary_config: UpstreamConfig,
        probe_interval_seconds: float = 2.0,
        failure_threshold: int = 3,
        probe_timeout_seconds: float = 3.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.stable_config = stable_config
        self.canary_config = canary_config
        self.probe_interval = probe_interval_seconds
        self.failure_threshold = failure_threshold
        self.probe_timeout = probe_timeout_seconds
        self._client = http_client
        self._owns_client = http_client is None

        self.stable_health = UpstreamHealth(
            name="stable",
            target_url=stable_config.url,
            health_path=stable_config.health_path,
        )
        self.canary_health = UpstreamHealth(
            name="canary",
            target_url=canary_config.url,
            health_path=canary_config.health_path,
        )

        self._running: bool = False
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def is_canary_healthy(self) -> bool:
        return self.canary_health.is_healthy

    def is_stable_healthy(self) -> bool:
        return self.stable_health.is_healthy

    async def start(self) -> None:
        """Start the background active health polling loop."""
        if self._running:
            return
        if self._owns_client and self._client is None:
            self._client = httpx.AsyncClient(timeout=self.probe_timeout)

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ActiveHealthProber started (interval: %.1fs)", self.probe_interval)

    async def stop(self) -> None:
        """Stop active health polling."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._owns_client and self._client:
            await self._client.aclose()
            self._client = None
        logger.info("ActiveHealthProber stopped")

    async def _run_loop(self) -> None:
        """Execute probing cycles."""
        while self._running:
            try:
                await self.probe_all()
            except Exception:
                logger.exception("Error during active health probing cycle")
            await asyncio.sleep(self.probe_interval)

    async def probe_all(self) -> None:
        """Probe both stable and canary upstreams concurrently."""
        await asyncio.gather(
            self.probe_target(self.stable_config, self.stable_health),
            self.probe_target(self.canary_config, self.canary_health),
        )

    async def probe_target(self, config: UpstreamConfig, health: UpstreamHealth) -> None:
        """Probe a single upstream health endpoint and update records."""
        url = f"{config.url.rstrip('/')}{config.health_path}"
        client = self._client or httpx.AsyncClient(timeout=self.probe_timeout)
        start_time = time.perf_counter()

        try:
            resp = await client.get(url)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            health.last_checked_timestamp = time.time()
            health.last_latency_ms = round(latency_ms, 2)
            health.last_status_code = resp.status_code

            if 200 <= resp.status_code < 400:
                health.consecutive_successes += 1
                health.consecutive_failures = 0
                health.is_healthy = True
                health.last_error_message = None
            else:
                health.consecutive_failures += 1
                health.consecutive_successes = 0
                health.last_error_message = f"HTTP {resp.status_code}"
                if health.consecutive_failures >= self.failure_threshold:
                    health.is_healthy = False
                    logger.warning(
                        "Upstream %s marked UNHEALTHY after %d failures (HTTP %d)",
                        health.name,
                        health.consecutive_failures,
                        resp.status_code,
                    )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            health.last_checked_timestamp = time.time()
            health.last_latency_ms = round(latency_ms, 2)
            health.last_status_code = 0
            health.consecutive_failures += 1
            health.consecutive_successes = 0
            health.last_error_message = str(exc)

            if health.consecutive_failures >= self.failure_threshold:
                health.is_healthy = False
                logger.warning(
                    "Upstream %s marked UNHEALTHY after %d connection errors: %s",
                    health.name,
                    health.consecutive_failures,
                    exc,
                )

    def get_status(self) -> dict[str, Any]:
        """Return serialized health information."""
        return {
            "running": self._running,
            "probe_interval_seconds": self.probe_interval,
            "failure_threshold": self.failure_threshold,
            "stable": asdict(self.stable_health),
            "canary": asdict(self.canary_health),
        }
