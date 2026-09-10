"""Unit tests for sliding-window telemetry."""

from canarymesh.proxy.stats import SlidingWindow, TelemetryManager


def test_sliding_window_basic_recording(mock_timestamp):
    window = SlidingWindow("test_upstream", window_size_seconds=10)

    # Record 5 successful requests with varying latencies
    for lat in [10.0, 20.0, 30.0, 40.0, 50.0]:
        window.record(200, lat, timestamp=mock_timestamp)

    metrics = window.snapshot(current_time=mock_timestamp)
    assert metrics.total_requests == 5
    assert metrics.status_2xx == 5
    assert metrics.status_5xx == 0
    assert metrics.error_rate_percent == 0.0
    assert metrics.p50_ms == 30.0
    assert metrics.max_ms == 50.0
    assert metrics.avg_ms == 30.0


def test_sliding_window_error_rate_calculation(mock_timestamp):
    window = SlidingWindow("canary", window_size_seconds=60)

    # Record 8 200s and 2 500s (20% error rate)
    for _ in range(8):
        window.record(200, 15.0, timestamp=mock_timestamp)
    for _ in range(2):
        window.record(500, 100.0, timestamp=mock_timestamp)

    metrics = window.snapshot(current_time=mock_timestamp)
    assert metrics.total_requests == 10
    assert metrics.status_2xx == 8
    assert metrics.status_5xx == 2
    assert metrics.error_rate_percent == 20.0


def test_sliding_window_pruning_expired_slots(mock_timestamp):
    window = SlidingWindow("canary", window_size_seconds=10)

    # Record at t=100
    window.record(200, 20.0, timestamp=mock_timestamp)

    # Snapshot at t=105 (within 10s window)
    metrics_inside = window.snapshot(current_time=mock_timestamp + 5)
    assert metrics_inside.total_requests == 1

    # Snapshot at t=115 (past 10s window)
    metrics_expired = window.snapshot(current_time=mock_timestamp + 15)
    assert metrics_expired.total_requests == 0
    assert metrics_expired.p50_ms == 0.0


def test_telemetry_manager_routing():
    mgr = TelemetryManager(window_size_seconds=30)
    mgr.record("stable", 200, 10.0)
    mgr.record("canary", 500, 80.0)

    snap = mgr.get_snapshot()
    assert snap["stable"].total_requests == 1
    assert snap["stable"].status_2xx == 1
    assert snap["canary"].total_requests == 1
    assert snap["canary"].status_5xx == 1
    assert snap["canary"].error_rate_percent == 100.0
