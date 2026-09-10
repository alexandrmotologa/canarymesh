"""Asynchronous traffic generator simulating client requests against CanaryMesh."""

import asyncio
import random
import time

import httpx
from rich.console import Console

console = Console()


async def run_traffic_simulation(
    target_url: str = "http://127.0.0.1:8080",
    requests_per_second: int = 30,
    duration_seconds: int = 30,
    concurrency: int = 5,
    user_pool_size: int = 20,
) -> dict[str, int]:
    """Generate concurrent HTTP requests against the target proxy."""
    console.print(
        f"[bold cyan]Starting CanaryMesh Traffic Simulation[/bold cyan] -> {target_url} "
        f"({requests_per_second} req/s, duration: {duration_seconds}s)"
    )

    stats = {
        "total": 0,
        "status_200": 0,
        "status_500": 0,
        "status_other": 0,
        "routed_stable": 0,
        "routed_canary": 0,
    }

    user_sessions = [f"sim-user-{i:03d}" for i in range(user_pool_size)]
    endpoints = ["/api/v1/orders", "/api/v1/products", "/api/v1/cart", "/checkout"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        stop_time = time.time() + duration_seconds
        sleep_between = 1.0 / max(1, requests_per_second)

        while time.time() < stop_time:
            session = random.choice(user_sessions)
            path = random.choice(endpoints)
            url = f"{target_url.rstrip('/')}{path}"
            cookies = {"canary_session": session}

            try:
                resp = await client.get(url, cookies=cookies)
                stats["total"] += 1

                if resp.status_code == 200:
                    stats["status_200"] += 1
                elif resp.status_code == 500:
                    stats["status_500"] += 1
                else:
                    stats["status_other"] += 1

                routed = resp.headers.get("x-canary-routed", "unknown")
                if routed == "canary":
                    stats["routed_canary"] += 1
                elif routed == "stable":
                    stats["routed_stable"] += 1

                # Visual heartbeat
                status_color = "green" if resp.status_code == 200 else "red"
                routed_color = "yellow" if routed == "canary" else "blue"
                console.print(
                    f"[{status_color}]HTTP {resp.status_code}[/{status_color}] "
                    f"[{routed_color}]{routed.upper()}[/{routed_color}] -> {path} "
                    f"({resp.headers.get('x-canary-latency-ms', '?')}ms)",
                    end="\r",
                )

            except Exception:
                stats["total"] += 1
                stats["status_other"] += 1

            await asyncio.sleep(sleep_between)

    console.print("\n[bold green]Simulation Completed![/bold green]")
    console.print(f"Total Requests: {stats['total']}")
    console.print(f"200 OK: {stats['status_200']} | 500 Error: {stats['status_500']}")
    console.print(f"Routed Stable: {stats['routed_stable']} | Routed Canary: {stats['routed_canary']}")

    return stats
