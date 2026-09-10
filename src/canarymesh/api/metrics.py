"""Prometheus metrics exporter generating standard text exposition format."""


from canarymesh.controller.rollback_guard import GuardState, RollbackGuard
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager


def generate_prometheus_metrics(
    router: TrafficRouter,
    telemetry: TelemetryManager,
    guard: RollbackGuard,
) -> str:
    """Format active runtime telemetry into Prometheus text format."""
    lines: list[str] = []

    # Traffic Weights
    lines.append("# HELP canarymesh_traffic_weight Current traffic percentage assigned to upstream")
    lines.append("# TYPE canarymesh_traffic_weight gauge")
    lines.append(f'canarymesh_traffic_weight{{upstream="canary"}} {router.canary_weight:.1f}')
    lines.append(f'canarymesh_traffic_weight{{upstream="stable"}} {100.0 - router.canary_weight:.1f}')

    # Cumulative request counters
    lines.append("# HELP canarymesh_requests_total Lifetime HTTP requests forwarded")
    lines.append("# TYPE canarymesh_requests_total counter")
    for name, win in [("stable", telemetry.stable), ("canary", telemetry.canary)]:
        lines.append(f'canarymesh_requests_total{{upstream="{name}",status="2xx"}} {win.cumulative_2xx}')
        lines.append(f'canarymesh_requests_total{{upstream="{name}",status="3xx"}} {win.cumulative_3xx}')
        lines.append(f'canarymesh_requests_total{{upstream="{name}",status="4xx"}} {win.cumulative_4xx}')
        lines.append(f'canarymesh_requests_total{{upstream="{name}",status="5xx"}} {win.cumulative_5xx}')

    # Sliding window metrics
    snapshot = telemetry.get_snapshot()
    lines.append("# HELP canarymesh_sliding_requests Number of requests recorded in active sliding window")
    lines.append("# TYPE canarymesh_sliding_requests gauge")
    for name, m in snapshot.items():
        lines.append(f'canarymesh_sliding_requests{{upstream="{name}"}} {m.total_requests}')

    lines.append("# HELP canarymesh_sliding_error_rate_percent 5xx error rate percentage in sliding window")
    lines.append("# TYPE canarymesh_sliding_error_rate_percent gauge")
    for name, m in snapshot.items():
        lines.append(f'canarymesh_sliding_error_rate_percent{{upstream="{name}"}} {m.error_rate_percent}')

    lines.append("# HELP canarymesh_sliding_latency_ms Latency percentiles in sliding window")
    lines.append("# TYPE canarymesh_sliding_latency_ms gauge")
    for name, m in snapshot.items():
        lines.append(f'canarymesh_sliding_latency_ms{{upstream="{name}",quantile="0.5"}} {m.p50_ms}')
        lines.append(f'canarymesh_sliding_latency_ms{{upstream="{name}",quantile="0.9"}} {m.p90_ms}')
        lines.append(f'canarymesh_sliding_latency_ms{{upstream="{name}",quantile="0.95"}} {m.p95_ms}')
        lines.append(f'canarymesh_sliding_latency_ms{{upstream="{name}",quantile="0.99"}} {m.p99_ms}')

    # Guard State and Trips
    lines.append("# HELP canarymesh_guard_healthy 1 if healthy, 0 if tripped")
    lines.append("# TYPE canarymesh_guard_healthy gauge")
    lines.append(f"canarymesh_guard_healthy {1 if guard.state == GuardState.HEALTHY else 0}")

    lines.append("# HELP canarymesh_guard_trips_total Total automated rollback trips triggered")
    lines.append("# TYPE canarymesh_guard_trips_total counter")
    lines.append(f"canarymesh_guard_trips_total {len(guard.trip_history)}")

    lines.append("")
    return "\n".join(lines)
