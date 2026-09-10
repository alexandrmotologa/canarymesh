"""Progressive canary rollout scheduler executing staged traffic promotions."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from canarymesh.config import SlaThresholds
from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.proxy.router import TrafficRouter

logger = logging.getLogger("canarymesh.rollout")


class RolloutState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"


@dataclass
class RolloutStep:
    weight: float
    duration_seconds: int


@dataclass
class RolloutScenario:
    name: str
    description: str = ""
    steps: list[RolloutStep] = field(default_factory=list)
    sla: SlaThresholds | None = None


class RolloutEngine:
    """Manages progression across configured canary rollout stages."""

    def __init__(self, router: TrafficRouter, guard: RollbackGuard):
        self.router = router
        self.guard = guard
        self.scenario: RolloutScenario | None = None
        self.state: RolloutState = RolloutState.IDLE
        self.current_step_index: int = 0
        self.step_elapsed_seconds: float = 0.0
        self.abort_reason: str | None = None

        self._task: asyncio.Task | None = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()

    def load_scenario(self, file_path_or_dict: Any) -> RolloutScenario:
        """Load and parse rollout scenario configuration."""
        if isinstance(file_path_or_dict, (str, Path)):
            with open(file_path_or_dict, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        elif isinstance(file_path_or_dict, dict):
            data = file_path_or_dict
        else:
            raise TypeError("Expected YAML filepath or dictionary")

        steps = [
            RolloutStep(weight=float(s["weight"]), duration_seconds=int(s.get("duration_seconds", 0)))
            for s in data.get("steps", [])
        ]
        sla_data = data.get("sla")
        sla = SlaThresholds(**sla_data) if sla_data else None

        self.scenario = RolloutScenario(
            name=data.get("name", "custom-rollout"),
            description=data.get("description", ""),
            steps=steps,
            sla=sla,
        )
        if sla:
            self.guard.sla = sla

        self.current_step_index = 0
        self.step_elapsed_seconds = 0.0
        self.state = RolloutState.IDLE
        logger.info("Loaded scenario '%s' with %d steps", self.scenario.name, len(steps))
        return self.scenario

    async def start(self) -> None:
        """Begin progressive rollout execution."""
        if not self.scenario or not self.scenario.steps:
            raise RuntimeError("No scenario loaded")
        if self.state == RolloutState.RUNNING:
            return

        self.guard.reset()
        self.state = RolloutState.RUNNING
        self.abort_reason = None
        self._pause_event.set()
        self._task = asyncio.create_task(self._run_steps())
        logger.info("Started rollout scenario: %s", self.scenario.name)

    def pause(self) -> None:
        """Pause the current rollout progression."""
        if self.state == RolloutState.RUNNING:
            self.state = RolloutState.PAUSED
            self._pause_event.clear()
            logger.info("Rollout paused at step %d", self.current_step_index)

    def resume(self) -> None:
        """Resume paused rollout progression."""
        if self.state == RolloutState.PAUSED:
            self.state = RolloutState.RUNNING
            self._pause_event.set()
            logger.info("Rollout resumed at step %d", self.current_step_index)

    async def abort(self, reason: str = "Manual abort requested") -> None:
        """Abort rollout immediately and set canary weight to zero."""
        self.state = RolloutState.ABORTED
        self.abort_reason = reason
        self.router.set_weight(0.0)
        if self._task and not self._task.done():
            self._task.cancel()
        logger.warning("Rollout aborted: %s", reason)

    def promote(self) -> None:
        """Immediately promote canary to 100% traffic and complete."""
        self.router.set_weight(100.0)
        self.state = RolloutState.COMPLETED
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Canary promoted to 100% traffic")

    async def _run_steps(self) -> None:
        """Iterate through defined rollout steps with soak validation."""
        try:
            while self.current_step_index < len(self.scenario.steps):
                step = self.scenario.steps[self.current_step_index]

                # Apply current step weight
                self.router.set_weight(step.weight)
                logger.info(
                    "Executing step %d/%d: weight=%.1f%%, duration=%ds",
                    self.current_step_index + 1,
                    len(self.scenario.steps),
                    step.weight,
                    step.duration_seconds,
                )

                self.step_elapsed_seconds = 0.0
                step_start = time.time()

                # Soak time loop
                while self.step_elapsed_seconds < step.duration_seconds:
                    await self._pause_event.wait()

                    # Verify rollback guard health
                    if self.guard.state == GuardState.TRIPPED:
                        await self.abort(
                            f"RollbackGuard tripped: {self.guard.last_trip_reason}"
                        )
                        return

                    await asyncio.sleep(0.5)
                    self.step_elapsed_seconds = time.time() - step_start

                self.current_step_index += 1

            # All steps completed successfully
            self.state = RolloutState.COMPLETED
            logger.info("Rollout scenario completed successfully")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Error executing rollout steps")
            await self.abort(f"Unexpected error: {exc}")

    def get_status(self) -> dict[str, Any]:
        """Return status payload for control plane API and UI."""
        total_steps = len(self.scenario.steps) if self.scenario else 0
        current_step = None
        if self.scenario and self.current_step_index < total_steps:
            s = self.scenario.steps[self.current_step_index]
            current_step = {
                "step_number": self.current_step_index + 1,
                "weight": s.weight,
                "duration_seconds": s.duration_seconds,
                "elapsed_seconds": round(self.step_elapsed_seconds, 1),
                "remaining_seconds": max(0, round(s.duration_seconds - self.step_elapsed_seconds, 1)),
            }

        return {
            "state": self.state.value,
            "scenario_name": self.scenario.name if self.scenario else None,
            "total_steps": total_steps,
            "current_step_index": self.current_step_index,
            "current_step": current_step,
            "canary_weight": self.router.canary_weight,
            "abort_reason": self.abort_reason,
        }
