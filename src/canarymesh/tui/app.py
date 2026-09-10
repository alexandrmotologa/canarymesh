"""Interactive Rich Live split-screen dashboard runner."""

import asyncio
import os
from typing import Any

from rich.console import Console
from rich.live import Live

from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager
from canarymesh.tui.widgets import build_dashboard_layout

console = Console()


def check_keyboard_input() -> str | None:
    """Non-blocking keyboard check supporting Windows and POSIX."""
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                return ch.decode("utf-8", errors="ignore")
            except Exception:
                return None
    return None


async def run_dashboard(
    config_dict: dict[str, Any],
    router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
    rollout: RolloutEngine,
    stop_event: asyncio.Event,
) -> None:
    """Live updating split-screen TUI loop."""
    with Live(
        build_dashboard_layout(config_dict, router, telemetry, guard, rollout),
        console=console,
        screen=True,
        refresh_per_second=4,
    ) as live:
        while not stop_event.is_set():
            # Check keyboard input
            key = check_keyboard_input()
            if key:
                key_lower = key.lower()
                if key_lower == "q":
                    stop_event.set()
                    break
                elif key_lower == "a":
                    await guard.trip("Manual emergency abort via TUI keypress")
                    await rollout.abort("Manual emergency abort via TUI keypress")
                elif key_lower == "p":
                    rollout.promote()
                    router.set_weight(100.0)
                elif key_lower == "r":
                    guard.reset()
                elif key in ("+", "="):
                    router.set_weight(router.canary_weight + 5.0)
                elif key in ("-", "_"):
                    router.set_weight(router.canary_weight - 5.0)

            # Update layout
            layout = build_dashboard_layout(config_dict, router, telemetry, guard, rollout)
            live.update(layout)
            await asyncio.sleep(0.25)
