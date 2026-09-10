"""Rich UI widgets and layout builders for the live split-screen dashboard."""

from typing import Any

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager, WindowMetrics


def create_header(config_data: dict[str, Any], canary_weight: float) -> Panel:
    """Render top summary banner."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="right", ratio=1)

    title_text = Text.assemble(
        ("CANARY", "bold yellow"),
        ("MESH", "bold cyan"),
        ("  v0.1.0", "dim"),
    )
    ports_text = Text.assemble(
        ("Proxy: ", "dim"),
        (f":{config_data.get('proxy_port', 8080)}", "bold white"),
        ("  Control: ", "dim"),
        (f":{config_data.get('control_port', 8090)}", "bold white"),
    )
    weight_text = Text.assemble(
        ("Stable: ", "bold blue"),
        (f"{100.0 - canary_weight:.1f}%", "bold white"),
        ("  |  Canary: ", "bold yellow"),
        (f"{canary_weight:.1f}%", "bold white"),
    )

    grid.add_row(title_text, ports_text, weight_text)
    return Panel(grid, style="on grey11", height=3)


def create_upstream_panel(
    name: str,
    url: str,
    weight: float,
    metrics: WindowMetrics,
    lifetime_requests: int,
    is_canary: bool = False,
    is_tripped: bool = False,
) -> Panel:
    """Render comprehensive telemetry panel for an upstream service."""
    color = "yellow" if is_canary else "blue"
    border_style = "bold red" if is_tripped else color

    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(justify="left", style="bold")
    table.add_column(justify="right")

    # Target info
    table.add_row("Target URL:", f"[dim]{url}[/dim]")
    table.add_row("Traffic Share:", f"[bold {color}]{weight:.1f}%[/bold {color}]")
    table.add_row("Lifetime Requests:", f"{lifetime_requests:,}")
    table.add_row("", "")

    # Window metrics
    table.add_row("[underline]Active Window (60s)[/underline]", "")
    table.add_row("Throughput:", f"[bold]{metrics.rps:.1f}[/bold] req/s ({metrics.total_requests} reqs)")

    # Status breakdown
    table.add_row("Status 2xx (Success):", f"[green]{metrics.status_2xx}[/green]")
    table.add_row("Status 4xx (Client):", f"[yellow]{metrics.status_4xx}[/yellow]")

    err_style = "bold red" if metrics.error_rate_percent > 0 else "dim"
    table.add_row("Status 5xx (Errors):", f"[{err_style}]{metrics.status_5xx}[/{err_style}]")

    err_rate_color = "red" if metrics.error_rate_percent > 1.0 else ("yellow" if metrics.error_rate_percent > 0 else "green")
    table.add_row("5xx Error Rate:", f"[{err_rate_color}]{metrics.error_rate_percent:.2f}%[/{err_rate_color}]")
    table.add_row("", "")

    # Latency quantiles
    table.add_row("[underline]Latency Distribution[/underline]", "")
    table.add_row("p50 (Median):", f"{metrics.p50_ms:.1f} ms")
    table.add_row("p90:", f"{metrics.p90_ms:.1f} ms")
    p99_color = "red" if metrics.p99_ms > 350.0 else "white"
    table.add_row("p99 (Tail):", f"[{p99_color}]{metrics.p99_ms:.1f} ms[/{p99_color}]")
    table.add_row("Max Observed:", f"{metrics.max_ms:.1f} ms")

    title = f"[{color}]● {name.upper()}[/{color}]"
    if is_tripped:
        title += " [bold red](TRIPPED / 0% TRAFFIC)[/bold red]"

    return Panel(table, title=title, border_style=border_style, padding=(1, 2))


def create_guard_and_rollout_panel(guard: RollbackGuard, rollout: RolloutEngine) -> Panel:
    """Render guard status and progressive rollout progress."""
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    # Left: Guard Status
    guard_table = Table.grid(padding=(0, 1))
    guard_table.add_column(style="bold")
    guard_table.add_column()

    state_style = "bold green" if guard.state == GuardState.HEALTHY else "bold red on black"
    guard_table.add_row("Guard State:", f"[{state_style}]{guard.state.value}[/{state_style}]")
    guard_table.add_row(
        "SLA Thresholds:",
        f"max err: [bold]{guard.sla.max_error_rate_percent}%[/bold], max p99: [bold]{guard.sla.max_p99_latency_ms}ms[/bold]",
    )
    guard_table.add_row("Total Incidents:", f"{len(guard.trip_history)}")
    if guard.last_trip_reason:
        guard_table.add_row("Last Breach:", f"[red]{guard.last_trip_reason}[/red]")

    # Right: Rollout Status
    rollout_table = Table.grid(padding=(0, 1))
    rollout_table.add_column(style="bold")
    rollout_table.add_column()

    r_status = rollout.get_status()
    r_state = r_status["state"]
    r_color = "green" if r_state in ("RUNNING", "COMPLETED") else ("yellow" if r_state == "PAUSED" else "dim")
    rollout_table.add_row("Rollout Stage:", f"[{r_color}]{r_state}[/{r_color}]")
    rollout_table.add_row("Active Scenario:", f"{r_status['scenario_name'] or 'None (Manual Weight)'}")

    step = r_status.get("current_step")
    if step:
        rollout_table.add_row(
            "Current Step:",
            f"Step {step['step_number']}/{r_status['total_steps']} ({step['weight']}% weight, {step['remaining_seconds']}s remaining)",
        )
    else:
        rollout_table.add_row("Step Info:", "Manual Control Active")

    grid.add_row(
        Panel(guard_table, title="[bold]Automated Rollback Guard[/bold]", border_style="grey37"),
        Panel(rollout_table, title="[bold]Progressive Rollout Engine[/bold]", border_style="grey37"),
    )
    return Panel(grid, border_style="dim", height=7)


def create_footer() -> Panel:
    """Render keyboard shortcuts help bar."""
    shortcuts = (
        "[bold cyan][A][/bold cyan] Emergency Abort  "
        "[bold cyan][P][/bold cyan] Promote to 100%  "
        "[bold cyan][+][/bold cyan] Weight +5%  "
        "[bold cyan][-][/bold cyan] Weight -5%  "
        "[bold cyan][R][/bold cyan] Reset Guard  "
        "[bold cyan][Q][/bold cyan] Quit"
    )
    return Panel(Text.from_markup(shortcuts, justify="center"), style="on grey15", height=3)


def build_dashboard_layout(
    config_dict: dict[str, Any],
    router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
    rollout: RolloutEngine,
) -> Layout:
    """Assemble the complete split-screen layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="guard_panel", size=7),
        Layout(name="footer", size=3),
    )

    # Split body into two side-by-side columns
    layout["body"].split_row(
        Layout(name="stable_panel", ratio=1),
        Layout(name="canary_panel", ratio=1),
    )

    snapshot = telemetry.get_snapshot()
    canary_weight = router.canary_weight
    is_tripped = guard.state == GuardState.TRIPPED

    layout["header"].update(create_header(config_dict, canary_weight))
    layout["stable_panel"].update(
        create_upstream_panel(
            name="Stable v1",
            url=config_dict.get("stable_url", "http://127.0.0.1:8081"),
            weight=100.0 - canary_weight,
            metrics=snapshot["stable"],
            lifetime_requests=telemetry.stable.cumulative_requests,
            is_canary=False,
        )
    )
    layout["canary_panel"].update(
        create_upstream_panel(
            name="Canary v2",
            url=config_dict.get("canary_url", "http://127.0.0.1:8082"),
            weight=canary_weight,
            metrics=snapshot["canary"],
            lifetime_requests=telemetry.canary.cumulative_requests,
            is_canary=True,
            is_tripped=is_tripped,
        )
    )
    layout["guard_panel"].update(create_guard_and_rollout_panel(guard, rollout))
    layout["footer"].update(create_footer())

    return layout
