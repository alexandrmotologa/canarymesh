# Telemetry and automated rollback

CanaryMesh tracks real-time response data using an in-memory sliding window with reservoir sampling and evaluates service level agreement (SLA) boundaries in the background.

## Telemetry collection

Every HTTP exchange records response metrics immediately after headers are received from the upstream target:

* Status category (2xx, 3xx, 4xx, 5xx)
* Round-trip duration in milliseconds (sampled per second using Algorithm R reservoir sampling)
* Upstream target name (stable or canary)

Observations are placed into 1-second buckets inside a 60-second circular buffer. During each snapshot, data older than 60 seconds is pruned automatically.

### Computed metrics

* **RPS**: Active requests divided by the window duration (60s).
* **5xx error rate**: Percentage of 5xx responses out of all requests in the window.
* **Latency quantiles**: Nearest-rank percentiles calculated over bounded latency observations: p50, p90, p95, and p99.
* **Comparative degradation**: Real-time ratio of Canary p99 to Stable baseline p99 and error rate difference.

## Rollback guard

The rollback guard runs an asynchronous loop every second. It checks canary metrics against both absolute limits and relative baseline degradation:

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `max_error_rate_percent` | `1.0%` | Maximum allowable 5xx server error rate |
| `max_p99_latency_ms` | `350.0 ms` | Maximum allowable 99th percentile latency |
| `min_sample_size` | `10` | Minimum requests required before checking boundaries |
| `enable_relative_analysis`| `true` | Enable comparative regression checks against Stable baseline |
| `max_relative_latency_ratio` | `2.0x` | Max ratio of Canary p99 to Stable p99 |
| `max_relative_error_diff_percent`| `3.0%` | Max difference between Canary 5xx% and Stable 5xx% |
| `enable_probation` | `false` | Enable automatic recovery into probation mode after cooldown |

### Tripping mechanism

To avoid false alarms from single outliers during low traffic, the guard waits until `min_sample_size` requests appear in the window.

When an absolute or relative threshold is exceeded:

1. Canary traffic is immediately set to `0.0%`.
2. The guard state changes from `HEALTHY` to `TRIPPED`.
3. An incident event is recorded in memory and written to `incidents/inc-<id>.md`.
4. Alert payloads are formatted and dispatched to all configured notification channels (Discord, Slack, Telegram, PagerDuty, or custom webhooks).
5. The incident post-mortem markdown report can be downloaded directly from the Web Console or API.
