"""Command Line Interface for CanaryMesh reverse proxy and controller."""

import asyncio
import logging

import httpx
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from canarymesh.api.app import create_control_app
from canarymesh.config import CanaryMeshConfig, SlaThresholds, UpstreamConfig
from canarymesh.controller.alert_dispatcher import AlertDispatcher
from canarymesh.controller.health_prober import ActiveHealthProber
from canarymesh.controller.post_mortem import PostMortemEngine
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.app import create_proxy_app
from canarymesh.proxy.forwarder import StreamingForwarder
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.shadow import ShadowEngine
from canarymesh.proxy.stats import TelemetryManager
from canarymesh.simulator.mock_services import run_mock_servers
from canarymesh.simulator.traffic_generator import run_traffic_simulation
from canarymesh.tui.app import run_dashboard

app = typer.Typer(
    name="canarymesh",
    help="Dynamic traffic splitting and automated rollback edge reverse proxy",
    add_completion=False,
)
console = Console()


@app.command()
def start(
    stable: str = typer.Option("http://127.0.0.1:8081", "--stable", "-s", help="Stable upstream URL (v1)"),
    canary: str = typer.Option("http://127.0.0.1:8082", "--canary", "-c", help="Canary upstream URL (v2)"),
    weight: float = typer.Option(0.0, "--weight", "-w", help="Initial canary traffic percentage (0-100)"),
    proxy_port: int = typer.Option(8080, "--proxy-port", help="Edge proxy listening port"),
    proxy_host: str = typer.Option("0.0.0.0", "--proxy-host", help="Edge proxy listening host"),
    control_port: int = typer.Option(8090, "--control-port", help="Control plane REST API port"),
    control_host: str = typer.Option("0.0.0.0", "--control-host", help="Control plane REST API host"),
    scenario: str | None = typer.Option(None, "--scenario", help="Path to progressive rollout YAML scenario"),
    dashboard: bool = typer.Option(False, "--dashboard", "-d", help="Run interactive split-screen TUI"),
    shadow: bool = typer.Option(False, "--shadow", help="Enable dark launch traffic shadowing to Canary"),
    shadow_percent: float = typer.Option(100.0, "--shadow-percent", help="Shadow traffic percentage"),
    max_error_rate: float = typer.Option(1.0, "--max-error-rate", help="Rollback threshold 5xx error rate %"),
    max_p99_ms: float = typer.Option(350.0, "--max-p99-ms", help="Rollback threshold p99 latency ms"),
    min_samples: int = typer.Option(10, "--min-samples", help="Min samples before evaluating rollback"),
    webhook: list[str] | None = typer.Option(None, "--webhook", help="Webhook notification URLs"),
):
    """Start CanaryMesh edge proxy, control plane, and automated rollback guard."""
    asyncio.run(
        _start_runtime(
            stable=stable,
            canary=canary,
            weight=weight,
            proxy_port=proxy_port,
            proxy_host=proxy_host,
            control_port=control_port,
            control_host=control_host,
            scenario=scenario,
            dashboard=dashboard,
            shadow=shadow,
            shadow_percent=shadow_percent,
            max_error_rate=max_error_rate,
            max_p99_ms=max_p99_ms,
            min_samples=min_samples,
            webhooks=webhook or [],
        )
    )


async def _start_runtime(
    stable: str,
    canary: str,
    weight: float,
    proxy_port: int,
    proxy_host: str,
    control_port: int,
    control_host: str,
    scenario: str | None,
    dashboard: bool,
    shadow: bool,
    shadow_percent: float,
    max_error_rate: float,
    max_p99_ms: float,
    min_samples: int,
    webhooks: list[str],
):
    # Configure logging level
    logging.basicConfig(level=logging.WARNING if dashboard else logging.INFO)

    cfg = CanaryMeshConfig(
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        control_host=control_host,
        control_port=control_port,
        stable=UpstreamConfig(name="stable", url=stable),
        canary=UpstreamConfig(name="canary", url=canary),
        initial_canary_weight=weight,
        alert_webhooks=webhooks,
        sla=SlaThresholds(
            max_error_rate_percent=max_error_rate,
            max_p99_latency_ms=max_p99_ms,
            min_sample_size=min_samples,
        ),
    )

    # Core components
    router = TrafficRouter(cfg)
    telemetry = TelemetryManager(window_size_seconds=cfg.window_size_seconds)
    post_mortem = PostMortemEngine()
    alert_dispatcher = AlertDispatcher(webhook_urls=cfg.alert_webhooks, post_mortem_engine=post_mortem)
    health_prober = ActiveHealthProber(cfg.stable, cfg.canary)
    shadow_engine = ShadowEngine(
        canary_target=cfg.canary,
        telemetry=telemetry,
        enabled=shadow,
        shadow_percentage=shadow_percent,
    )
    forwarder = StreamingForwarder(router, telemetry, shadow_engine=shadow_engine)
    guard = RollbackGuard(
        router=router,
        telemetry=telemetry,
        sla=cfg.sla,
        alert_dispatcher=alert_dispatcher,
        health_prober=health_prober,
        eval_interval_seconds=cfg.eval_interval_seconds,
    )
    rollout = RolloutEngine(router=router, guard=guard, health_prober=health_prober)

    if scenario:
        rollout.load_scenario(scenario)

    # Instantiate FastAPI apps
    proxy_app = create_proxy_app(forwarder)
    control_app = create_control_app(
        traffic_router=router,
        telemetry=telemetry,
        guard=guard,
        rollout=rollout,
        health_prober=health_prober,
        shadow_engine=shadow_engine,
        post_mortem=post_mortem,
    )

    proxy_server = uvicorn.Server(
        uvicorn.Config(proxy_app, host=proxy_host, port=proxy_port, log_level="warning")
    )
    control_server = uvicorn.Server(
        uvicorn.Config(control_app, host=control_host, port=control_port, log_level="warning")
    )

    stop_event = asyncio.Event()

    # Start background tasks
    await health_prober.start()
    await guard.start()
    if scenario:
        await rollout.start()

    tasks = [
        asyncio.create_task(proxy_server.serve()),
        asyncio.create_task(control_server.serve()),
    ]

    config_dict = {
        "proxy_port": proxy_port,
        "control_port": control_port,
        "stable_url": stable,
        "canary_url": canary,
    }

    if not dashboard:
        console.print(
            f"[bold green]CanaryMesh Started[/bold green] | Proxy: http://{proxy_host}:{proxy_port} | "
            f"Control: http://{control_host}:{control_port}"
        )
        console.print(
            f"Routing: [bold blue]Stable ({100.0 - weight:.1f}%)[/bold blue] -> {stable} | "
            f"[bold yellow]Canary ({weight:.1f}%)[/bold yellow] -> {canary}"
        )
        console.print(f"Web Console: [bold cyan]http://{control_host}:{control_port}/ui[/bold cyan]")

    try:
        if dashboard:
            dashboard_task = asyncio.create_task(
                run_dashboard(config_dict, router, telemetry, guard, rollout, stop_event)
            )
            tasks.append(dashboard_task)

        # Wait until stop event is triggered or interrupted
        while not stop_event.is_set():
            await asyncio.sleep(0.5)

    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop_event.set()
        await health_prober.stop()
        await guard.stop()
        proxy_server.should_exit = True
        control_server.should_exit = True
        for t in tasks:
            t.cancel()
        await forwarder.close()
        console.print("\n[dim]CanaryMesh shutdown complete.[/dim]")


@app.command()
def set_weight(
    weight: float = typer.Argument(..., help="New canary traffic percentage (0-100)"),
    control_url: str = typer.Option("http://127.0.0.1:8090", "--control-url", help="Control plane URL"),
):
    """Update canary weight on a running CanaryMesh instance."""
    resp = httpx.post(f"{control_url.rstrip('/')}/api/v1/canary/weight", json={"weight": weight})
    if resp.status_code == 200:
        data = resp.json()
        console.print(
            f"[bold green]Updated Weight:[/bold green] Canary: [yellow]{data['canary_weight']}%[/yellow], "
            f"Stable: [blue]{data['stable_weight']}%[/blue]"
        )
    else:
        console.print(f"[bold red]Failed to update weight:[/bold red] {resp.text}")


@app.command()
def abort(
    control_url: str = typer.Option("http://127.0.0.1:8090", "--control-url", help="Control plane URL"),
):
    """Trigger an emergency rollback on a running CanaryMesh instance."""
    resp = httpx.post(f"{control_url.rstrip('/')}/api/v1/canary/abort")
    if resp.status_code == 200:
        console.print("[bold red]EMERGENCY ROLLBACK EXECUTED:[/bold red] Canary weight set to 0.0%")
    else:
        console.print(f"[bold red]Failed to abort canary:[/bold red] {resp.text}")


@app.command()
def promote(
    control_url: str = typer.Option("http://127.0.0.1:8090", "--control-url", help="Control plane URL"),
):
    """Promote canary to 100% traffic on a running CanaryMesh instance."""
    resp = httpx.post(f"{control_url.rstrip('/')}/api/v1/canary/promote")
    if resp.status_code == 200:
        console.print("[bold green]CANARY PROMOTED:[/bold green] Canary weight set to 100.0%")
    else:
        console.print(f"[bold red]Failed to promote canary:[/bold red] {resp.text}")


@app.command()
def status(
    control_url: str = typer.Option("http://127.0.0.1:8090", "--control-url", help="Control plane URL"),
):
    """Query and display active status from running CanaryMesh instance."""
    try:
        resp = httpx.get(f"{control_url.rstrip('/')}/api/v1/canary/status")
        resp.raise_for_status()
        data = resp.json()

        table = Table(title="CanaryMesh Status", show_header=True)
        table.add_column("Component", style="bold cyan")
        table.add_column("Value")

        table.add_row("Canary Weight", f"{data['weights']['canary']:.1f}%")
        table.add_row("Stable Weight", f"{data['weights']['stable']:.1f}%")
        table.add_row("Guard State", data["guard"]["state"])
        table.add_row("Rollout Stage", data["rollout"]["state"])
        table.add_row("Total Incidents", str(data["guard"]["total_trips"]))

        console.print(table)
    except Exception as exc:
        console.print(f"[bold red]Could not connect to control plane at {control_url}:[/bold red] {exc}")


@app.command()
def mock(
    port_v1: int = typer.Option(8081, "--port-v1", help="Port for mock v1 stable service"),
    port_v2: int = typer.Option(8082, "--port-v2", help="Port for mock v2 canary service"),
    inject_errors: bool = typer.Option(False, "--inject-errors", help="Inject 500 errors into v2 canary"),
    error_rate: float = typer.Option(30.0, "--error-rate", help="Injected error rate percentage"),
):
    """Start local mock v1 and v2 services for testing."""
    console.print(f"[bold green]Starting Mock Services[/bold green] -> Stable :{port_v1}, Canary :{port_v2}")
    if inject_errors:
        console.print(f"[yellow]Fault injection enabled on Canary with {error_rate}% error rate[/yellow]")
    asyncio.run(run_mock_servers(port_v1, port_v2, inject_errors, error_rate))


@app.command()
def simulate(
    target: str = typer.Option("http://127.0.0.1:8080", "--target", "-t", help="Target proxy URL"),
    rate: int = typer.Option(30, "--rate", "-r", help="Requests per second"),
    duration: int = typer.Option(20, "--duration", help="Simulation duration in seconds"),
):
    """Run concurrent synthetic traffic against CanaryMesh proxy."""
    asyncio.run(run_traffic_simulation(target_url=target, requests_per_second=rate, duration_seconds=duration))


if __name__ == "__main__":
    app()
