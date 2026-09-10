"""Unit tests for progressive rollout engine."""

import asyncio

import pytest

from canarymesh.config import CanaryMeshConfig, UpstreamConfig
from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine, RolloutState
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager


@pytest.fixture
def setup_engine():
    cfg = CanaryMeshConfig(
        stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
        canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
        initial_canary_weight=0.0,
    )
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=60)
    guard = RollbackGuard(router=router, telemetry=telemetry, sla=cfg.sla)
    engine = RolloutEngine(router=router, guard=guard)
    return engine, router, guard


@pytest.mark.asyncio
async def test_rollout_engine_execution(setup_engine):
    engine, router, _ = setup_engine

    scenario_dict = {
        "name": "fast-test",
        "steps": [
            {"weight": 10.0, "duration_seconds": 1},
            {"weight": 50.0, "duration_seconds": 1},
            {"weight": 100.0, "duration_seconds": 0},
        ],
    }
    engine.load_scenario(scenario_dict)
    assert engine.scenario.name == "fast-test"
    assert len(engine.scenario.steps) == 3

    await engine.start()
    assert engine.state == RolloutState.RUNNING

    # Wait for completion of steps
    await asyncio.sleep(2.5)

    assert engine.state == RolloutState.COMPLETED
    assert router.canary_weight == 100.0


@pytest.mark.asyncio
async def test_rollout_engine_abort_on_guard_trip(setup_engine):
    engine, router, guard = setup_engine

    scenario_dict = {
        "name": "guard-abort-test",
        "steps": [
            {"weight": 25.0, "duration_seconds": 5},
            {"weight": 100.0, "duration_seconds": 0},
        ],
    }
    engine.load_scenario(scenario_dict)
    await engine.start()

    # Simulate guard tripping during step execution
    guard.state = GuardState.TRIPPED
    guard.last_trip_reason = "Error threshold breached"

    await asyncio.sleep(1.0)

    assert engine.state == RolloutState.ABORTED
    assert router.canary_weight == 0.0
    assert "RollbackGuard tripped" in engine.abort_reason
