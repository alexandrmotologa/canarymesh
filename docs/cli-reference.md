# CLI reference

The `canarymesh` command-line interface provides operational commands to start the proxy, manage weights and routing rules, inspect incidents, and run simulations.

## Commands

### `canarymesh start`

Starts the reverse proxy, control plane API, and rollback guard.

```bash
canarymesh start [OPTIONS]
```

Options:

* `--stable, -s`: Stable upstream service URL. Default: `http://127.0.0.1:8081`.
* `--canary, -c`: Canary upstream service URL. Default: `http://127.0.0.1:8082`.
* `--weight, -w`: Initial canary percentage (0 to 100). Default: `0.0`.
* `--proxy-port`: Listening port for edge proxy data plane. Default: `8080`.
* `--proxy-host`: Listening host for edge proxy data plane. Default: `0.0.0.0`.
* `--control-port`: Listening port for management REST API. Default: `8090`.
* `--control-host`: Listening host for management REST API. Default: `0.0.0.0`.
* `--scenario`: Path to progressive rollout YAML scenario file.
* `--dashboard, -d`: Launch the interactive split-screen Rich terminal user interface.
* `--shadow`: Enable dark launch traffic shadowing to Canary.
* `--shadow-percent`: Shadow traffic percentage (1-100). Default: `100.0`.
* `--max-error-rate`: Error rate threshold percentage for automated rollback. Default: `1.0`.
* `--max-p99-ms`: 99th percentile latency threshold in milliseconds. Default: `350.0`.
* `--min-samples`: Minimum requests required before evaluating SLA. Default: `10`.
* `--relative-ratio`: Max allowed Canary/Stable p99 latency ratio. Default: `2.0`.
* `--relative-err-diff`: Max allowed Canary - Stable 5xx% difference. Default: `3.0`.
* `--webhook`: Webhook notification URLs (Discord, Slack, Telegram, PagerDuty, or custom). Can be specified multiple times.

### `canarymesh set-weight`

Updates canary weight on a running instance via the control plane API.

```bash
canarymesh set-weight 35 --control-url http://127.0.0.1:8090
```

### `canarymesh abort`

Forces an immediate rollback to 0% canary traffic.

```bash
canarymesh abort --control-url http://127.0.0.1:8090
```

### `canarymesh promote`

Sets canary traffic to 100% and completes the rollout.

```bash
canarymesh promote --control-url http://127.0.0.1:8090
```

### `canarymesh status`

Queries and displays active runtime metrics, weights, and guard state.

```bash
canarymesh status --control-url http://127.0.0.1:8090
```

### `canarymesh rules`

Lists all active dynamic path prefix and header match routing rules.

```bash
canarymesh rules --control-url http://127.0.0.1:8090
```

### `canarymesh incidents`

Lists all recorded automated rollback incidents or displays a specific post-mortem markdown report.

```bash
# List all incidents
canarymesh incidents --control-url http://127.0.0.1:8090

# View specific post-mortem report
canarymesh incidents inc-07ca7209 --control-url http://127.0.0.1:8090
```

### `canarymesh validate-scenario`

Validates YAML rollout scenario file syntax, steps, and durations before execution.

```bash
canarymesh validate-scenario scenarios/progressive-rollout.yaml
```

### `canarymesh mock`

Starts mock v1 (stable) and v2 (canary) servers for testing with optional fault injection.

```bash
canarymesh mock --port-v1 8081 --port-v2 8082 --inject-errors --error-rate 25
```

### `canarymesh simulate`

Generates synthetic concurrent HTTP requests against the proxy.

```bash
canarymesh simulate --target http://127.0.0.1:8080 --rate 30 --duration 20
```
