"""Continuous rollback guard monitoring telemetry and triggering instant rollbacks."""

import asyncio
import datetime
import logging
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from canarymesh.config import SlaThresholds
from canarymesh.controller.alert_dispatcher import AlertDispatcher
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager, WindowMetrics

logger = logging.getLogger("canarymesh.guard")


class GuardState(str, Enum):
    HEALTHY = "HEALTHY"
    TRIPPED = "TRIPPED"
    DISABLED = "DISABLED"


@dataclass
class TripEvent:
    """Historical record of an automated rollback event."""
    timestamp: str
    reason: str
    previous_weight: float
    error_rate_percent: float
    p99_ms: float
    total_requests: int


class RollbackGuard:
    """Monitors canary sliding-window metrics and trips emergency rollback if SLA is violated."""

    def __init__(
        self,
        router: TrafficRouter,
        telemetry: TelemetryManager,
        sla: SlaThresholds,
        alert_dispatcher: AlertDispatcher | None = None,
        eval_interval_seconds: float = 1.0,
    ):
        self.router = router
        self.telemetry = telemetry
        self.sla = sla
        self.alert_dispatcher = alert_dispatcher or AlertDispatcher()
        self.eval_interval = eval_interval_seconds

        self.state: GuardState = GuardState.HEALTHY
        self.trip_history: list[TripEvent] = []
        self._task: asyncio.Task | None = None
        self._running: bool = False
        self.last_eval_time: float | None = None
        self.last_trip_reason: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("RollbackGuard background loop started (interval: %.1fs)", self.eval_interval)

    async def stop(self) -> None:
        """Stop the background monitoring loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RollbackGuard stopped")

    async def _run_loop(self) -> None:
        """Periodic loop evaluating canary health."""
        while self._running:
            try:
                await self.evaluate()
            except Exception:
                logger.exception("Unexpected error in RollbackGuard loop")
            await asyncio.sleep(self.eval_interval)

    async def evaluate(self) -> TripEvent | None:
        """Perform a single SLA health check against the canary upstream."""
        self.last_eval_time = time.time()
        current_weight = self.router.canary_weight

        # Only evaluate active canary traffic
        if current_weight <= 0.0 or self.state == GuardState.TRIPPED:
            return None

        metrics: WindowMetrics = self.telemetry.canary.snapshot()

        # Check sample size threshold to avoid false alarms on minimal traffic
        if metrics.total_requests < self.sla.min_sample_size:
            return None

        breaches: list[str] = []

        # 1. Error rate check
        if metrics.error_rate_percent > self.sla.max_error_rate_percent:
            breaches.append(
                f"Canary 5xx error rate ({metrics.error_rate_percent}%) exceeded threshold ({self.sla.max_error_rate_percent}%)"
            )

        # 2. p99 latency check
        if metrics.p99_ms > self.sla.max_p99_latency_ms:
            breaches.append(
                f"Canary p99 latency ({metrics.p99_ms}ms) exceeded threshold ({self.sla.max_p99_latency_ms}ms)"
            )

        if breaches:
            reason = " | ".join(breaches)
            return await self.trip(reason, metrics)

        return None

    async def trip(self, reason: str, metrics: WindowMetrics | None = None) -> TripEvent:
        """Trigger emergency rollback: zero out canary traffic and notify alert endpoints."""
        prev_weight = self.router.canary_weight
        self.router.set_weight(0.0)
        self.state = GuardState.TRIPPED
        self.last_trip_reason = reason

        if metrics is None:
            metrics = self.telemetry.canary.snapshot()

        trip_event = TripEvent(
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
            reason=reason,
            previous_weight=prev_weight,
            error_rate_percent=metrics.error_rate_percent,
            p99_ms=metrics.p99_ms,
            total_requests=metrics.total_requests,
        )
        self.trip_history.append(trip_event)
        logger.critical("EMERGENCY ROLLBACK TRIPPED! Reason: %s", reason)

        # Dispatch async notification alert
        await self.alert_dispatcher.dispatch_rollback_alert(
            reason=reason,
            metrics=asdict(metrics),
            previous_weight=prev_weight,
        )

        return trip_event

    def reset(self) -> None:
        """Reset guard state back to HEALTHY."""
        self.state = GuardState.HEALTHY
        self.last_trip_reason = None
        logger.info("RollbackGuard reset to HEALTHY")

    def get_status(self) -> dict[str, Any]:
        """Return comprehensive status for monitoring and APIs."""
        return {
            "state": self.state.value,
            "running": self._running,
            "canary_weight": self.router.canary_weight,
            "last_eval_time": self.last_eval_time,
            "last_trip_reason": self.last_trip_reason,
            "total_trips": len(self.trip_history),
            "recent_trips": [asdict(t) for t in self.trip_history[-5:]],
            "sla": {
                "max_error_rate_percent": self.sla.max_error_rate_percent,
                "max_p99_latency_ms": self.sla.max_p99_latency_ms,
                "min_sample_size": self.sla.min_sample_size,
            },
        }
