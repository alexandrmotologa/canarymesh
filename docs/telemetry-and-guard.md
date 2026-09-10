# Telemetry and automated rollback

CanaryMesh tracks real-time response data using an in-memory sliding window and evaluates service level agreement (SLA) boundaries in the background.

## Telemetry collection

Every HTTP exchange records response metrics immediately after headers are received from the upstream target:

* Status category (2xx, 3xx, 4xx, 5xx)
* Round-trip duration in milliseconds
* Upstream target name (stable or canary)

Observations are placed into 1-second buckets inside a 60-second circular buffer. During each snapshot, data older than 60 seconds is discarded.

### Computed metrics

* **RPS**: Active requests divided by the window duration (60s).
* **5xx error rate**: Percentage of 5xx responses out of all requests in the window.
* **Latency quantiles**: Nearest-rank percentiles calculated over sorted latency observations: p50, p90, p95, and p99.

## Rollback guard

The rollback guard runs an asynchronous loop every second. It checks canary metrics against configured limits:

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `max_error_rate_percent` | `1.0%` | Maximum allowable 5xx server error rate |
| `max_p99_latency_ms` | `350.0 ms` | Maximum allowable 99th percentile latency |
| `min_sample_size` | `10` | Minimum requests required before checking boundaries |

### Tripping mechanism

To avoid false alarms from single outliers during low traffic, the guard waits until `min_sample_size` requests appear in the window.

When a threshold is exceeded:

1. Canary traffic is immediately set to `0.0%`.
2. The guard state changes from `HEALTHY` to `TRIPPED`.
3. An incident event is added to the internal audit log.
4. An alert payload is sent to all configured webhooks.

### Incident payload

```json
{
  "event": "EMERGENCY_ROLLBACK",
  "service": "canarymesh",
  "timestamp": "2026-09-10T11:45:00.123456+00:00",
  "reason": "Canary 5xx error rate (14.2%) exceeded threshold (1.0%)",
  "previous_canary_weight": 25.0,
  "current_canary_weight": 0.0,
  "metrics": {
    "total_requests": 28,
    "status_2xx": 24,
    "status_5xx": 4,
    "error_rate_percent": 14.29,
    "p99_ms": 32.5
  },
  "text": "[CanaryMesh Alert] Emergency Rollback Triggered: Canary 5xx error rate (14.2%) exceeded threshold (1.0%). Canary weight shifted from 25.0% to 0%."
}
```
