"""Unit tests for RollbackGuard and emergency abort triggers."""

import pytest

from canarymesh.config import CanaryMeshConfig, SlaThresholds, UpstreamConfig
from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager


class MockAlertDispatcher:
    def __init__(self):
        self.dispatched = []

    async def dispatch_rollback_alert(self, reason, metrics, previous_weight):
        self.dispatched.append({
            "reason": reason,
            "metrics": metrics,
            "previous_weight": previous_weight,
        })


@pytest.fixture
def setup_guard():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=20.0,
        sla=SlaThresholds(
            max_error_rate_percent=5.0,
            max_p99_latency_ms=200.0,
            min_sample_size=10,
        ),
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    mock_alerts = MockAlertDispatcher()
    guard = RollbackGuard(
        router=router,
        telemetry=telemetry,
        sla=cfg.sla,
        alert_dispatcher=mock_alerts,
        eval_interval_seconds=0.1,
    )
    return guard, router, telemetry, mock_alerts


@pytest.mark.asyncio
async def test_guard_ignores_below_sample_size(setup_guard):
    guard, router, telemetry, _ = setup_guard

    # Only 3 requests (below min_sample_size=10), even if all 500s
    for _ in range(3):
        telemetry.record("canary", 500, 50.0)

    trip_event = await guard.evaluate()
    assert trip_event is None
    assert guard.state == GuardState.HEALTHY
    assert router.canary_weight == 20.0


@pytest.mark.asyncio
async def test_guard_trips_on_high_error_rate(setup_guard):
    guard, router, telemetry, mock_alerts = setup_guard

    # Record 10 requests: 8 are 200, 2 are 500 (20% error rate > 5% threshold)
    for _ in range(8):
        telemetry.record("canary", 200, 20.0)
    for _ in range(2):
        telemetry.record("canary", 500, 25.0)

    trip_event = await guard.evaluate()
    assert trip_event is not None
    assert guard.state == GuardState.TRIPPED
    assert router.canary_weight == 0.0
    assert "error rate" in trip_event.reason.lower()
    assert len(mock_alerts.dispatched) == 1
    assert mock_alerts.dispatched[0]["previous_weight"] == 20.0


@pytest.mark.asyncio
async def test_guard_trips_on_high_latency(setup_guard):
    guard, router, telemetry, _ = setup_guard

    # Record 10 requests: all 200, but with high latency > 200ms
    for _ in range(10):
        telemetry.record("canary", 200, 300.0)

    trip_event = await guard.evaluate()
    assert trip_event is not None
    assert guard.state == GuardState.TRIPPED
    assert router.canary_weight == 0.0
    assert "p99 latency" in trip_event.reason.lower()


@pytest.mark.asyncio
async def test_guard_reset(setup_guard):
    guard, _router, telemetry, _ = setup_guard

    for _ in range(10):
        telemetry.record("canary", 500, 10.0)

    await guard.evaluate()
    assert guard.state == GuardState.TRIPPED

    guard.reset()
    assert guard.state == GuardState.HEALTHY
    assert guard.last_trip_reason is None
