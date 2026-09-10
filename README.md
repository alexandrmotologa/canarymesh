# CanaryMesh

CanaryMesh is an edge reverse proxy and automated rollback controller. It splits incoming HTTP traffic between a stable upstream service (v1) and a canary service (v2) using weights, sticky sessions, or request headers. A background supervisor tracks error rates and latency percentiles inside a rolling sliding window, cutting traffic to the canary service if thresholds fail.

## Key capabilities

* **Zero buffer streaming**: Forwards HTTP requests and responses as asynchronous streams without loading bodies into memory.
* **Flexible routing**: Supports weighted percentage distribution, sticky cookie hashing, and header matchers like `X-Canary: true`.
* **Rolling telemetry**: Maintains per second status counts and latency quantiles (p50, p90, p95, p99) over a 60 second circular window.
* **Automated rollback guard**: Inspects error rates and p99 latency every second, reverting canary traffic to 0% upon an SLA breach.
* **Incident webhooks**: Sends structured alert payloads to Discord, Slack, Sentinel, or generic webhook receivers.
* **Progressive delivery scheduler**: Executes YAML rollout schedules across stepped traffic phases with automated stability gates.
* **Terminal dashboard**: Displays real-time comparative metrics side by side using Rich.
* **Control plane API**: Exposes REST endpoints and Prometheus metrics on a separate management port.

## Quick start

### Installation

Requires Python 3.12 or newer.

```bash
git clone https://github.com/alexandrmotologa/canarymesh.git
cd canarymesh
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

### Running with mock upstreams

Start mock stable (port 8081) and canary (port 8082) instances:

```bash
canarymesh mock --port-v1 8081 --port-v2 8082
```

In a separate terminal, start the CanaryMesh proxy with a 20% canary split:

```bash
canarymesh start --stable http://127.0.0.1:8081 --canary http://127.0.0.1:8082 --weight 20
```

To run with the interactive split-screen dashboard:

```bash
canarymesh start --stable http://127.0.0.1:8081 --canary http://127.0.0.1:8082 --weight 20 --dashboard
```

Simulate traffic and inject faults into the canary upstream to trigger an automatic rollback:

```bash
canarymesh simulate --target http://127.0.0.1:8080 --rate 30 --inject-errors
```

## Control plane API

CanaryMesh serves management endpoints on port 8090 by default:

* `GET /api/v1/canary/status`: Shows active weights, routing metrics, and health status.
* `POST /api/v1/canary/weight`: Sets the canary traffic percentage (`{"weight": 25}`).
* `POST /api/v1/canary/abort`: Forces an immediate rollback, setting canary weight to 0%.
* `POST /api/v1/canary/promote`: Promotes the canary to receive 100% of traffic.
* `GET /metrics`: Exports Prometheus metrics.
* `GET /api/v1/live`: Streams live telemetry events over SSE.

## License

MIT License. See [LICENSE](LICENSE) for details.
