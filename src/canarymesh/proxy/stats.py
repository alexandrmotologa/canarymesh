"""In-memory sliding-window telemetry engine tracking latency percentiles and status codes."""

import math
import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class SecondSlot:
    """Telemetry metrics collected within a single 1-second interval."""
    epoch_second: int
    status_2xx: int = 0
    status_3xx: int = 0
    status_4xx: int = 0
    status_5xx: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def total_requests(self) -> int:
        return self.status_2xx + self.status_3xx + self.status_4xx + self.status_5xx


@dataclass
class WindowMetrics:
    """Aggregated metrics across the active sliding window."""
    upstream: str
    window_seconds: int
    total_requests: int
    status_2xx: int
    status_3xx: int
    status_4xx: int
    status_5xx: int
    error_rate_percent: float
    client_error_rate_percent: float
    rps: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    avg_ms: float
    max_ms: float


class SlidingWindow:
    """Sliding-window metric recorder maintaining a circular history of 1-second slots."""

    def __init__(self, upstream_name: str, window_size_seconds: int = 60):
        self.upstream_name = upstream_name
        self.window_size = window_size_seconds
        self._slots: dict[int, SecondSlot] = {}
        self._lock = Lock()

        # Cumulative lifetime totals
        self.cumulative_requests = 0
        self.cumulative_2xx = 0
        self.cumulative_3xx = 0
        self.cumulative_4xx = 0
        self.cumulative_5xx = 0

    def record(self, status_code: int, latency_ms: float, timestamp: float | None = None) -> None:
        """Record a single response event."""
        now = int(timestamp if timestamp is not None else time.time())
        cutoff = now - self.window_size

        with self._lock:
            # Update cumulative lifetime counters
            self.cumulative_requests += 1
            if 200 <= status_code < 300:
                self.cumulative_2xx += 1
            elif 300 <= status_code < 400:
                self.cumulative_3xx += 1
            elif 400 <= status_code < 500:
                self.cumulative_4xx += 1
            elif 500 <= status_code < 600:
                self.cumulative_5xx += 1

            # Prune obsolete slots
            expired_keys = [k for k in self._slots if k <= cutoff]
            for k in expired_keys:
                del self._slots[k]

            # Get or create current second slot
            slot = self._slots.get(now)
            if slot is None:
                slot = SecondSlot(epoch_second=now)
                self._slots[now] = slot

            if 200 <= status_code < 300:
                slot.status_2xx += 1
            elif 300 <= status_code < 400:
                slot.status_3xx += 1
            elif 400 <= status_code < 500:
                slot.status_4xx += 1
            elif 500 <= status_code < 600:
                slot.status_5xx += 1

            slot.latencies_ms.append(latency_ms)

    def snapshot(self, current_time: float | None = None) -> WindowMetrics:
        """Calculate and return aggregated window metrics."""
        now = int(current_time if current_time is not None else time.time())
        cutoff = now - self.window_size

        with self._lock:
            # Prune obsolete keys during snapshot
            expired_keys = [k for k in self._slots if k <= cutoff]
            for k in expired_keys:
                del self._slots[k]

            total_2xx = 0
            total_3xx = 0
            total_4xx = 0
            total_5xx = 0
            all_latencies: list[float] = []

            for slot in self._slots.values():
                total_2xx += slot.status_2xx
                total_3xx += slot.status_3xx
                total_4xx += slot.status_4xx
                total_5xx += slot.status_5xx
                all_latencies.extend(slot.latencies_ms)

        total_reqs = total_2xx + total_3xx + total_4xx + total_5xx
        err_rate = (total_5xx / total_reqs * 100.0) if total_reqs > 0 else 0.0
        client_err_rate = (total_4xx / total_reqs * 100.0) if total_reqs > 0 else 0.0
        rps = total_reqs / float(self.window_size)

        if all_latencies:
            all_latencies.sort()
            p50 = self._percentile(all_latencies, 50)
            p90 = self._percentile(all_latencies, 90)
            p95 = self._percentile(all_latencies, 95)
            p99 = self._percentile(all_latencies, 99)
            avg = sum(all_latencies) / len(all_latencies)
            max_val = all_latencies[-1]
        else:
            p50 = p90 = p95 = p99 = avg = max_val = 0.0

        return WindowMetrics(
            upstream=self.upstream_name,
            window_seconds=self.window_size,
            total_requests=total_reqs,
            status_2xx=total_2xx,
            status_3xx=total_3xx,
            status_4xx=total_4xx,
            status_5xx=total_5xx,
            error_rate_percent=round(err_rate, 2),
            client_error_rate_percent=round(client_err_rate, 2),
            rps=round(rps, 2),
            p50_ms=round(p50, 2),
            p90_ms=round(p90, 2),
            p95_ms=round(p95, 2),
            p99_ms=round(p99, 2),
            avg_ms=round(avg, 2),
            max_ms=round(max_val, 2),
        )

    def reset(self) -> None:
        """Clear all slots in the sliding window."""
        with self._lock:
            self._slots.clear()

    @staticmethod
    def _percentile(sorted_data: list[float], percentile: float) -> float:
        """Compute nearest-rank percentile on sorted array."""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1


class TelemetryManager:
    """Manages separate sliding windows for stable and canary upstreams."""

    def __init__(self, window_size_seconds: int = 60):
        self.window_size_seconds = window_size_seconds
        self.stable = SlidingWindow("stable", window_size_seconds)
        self.canary = SlidingWindow("canary", window_size_seconds)

    def record(self, upstream: str, status_code: int, latency_ms: float) -> None:
        """Route recording to appropriate upstream window."""
        if upstream == "canary":
            self.canary.record(status_code, latency_ms)
        else:
            self.stable.record(status_code, latency_ms)

    def get_snapshot(self) -> dict[str, WindowMetrics]:
        """Return current snapshot for both upstreams."""
        return {
            "stable": self.stable.snapshot(),
            "canary": self.canary.snapshot(),
        }

    def reset_canary(self) -> None:
        """Reset canary stats after an abort or version switch."""
        self.canary.reset()
