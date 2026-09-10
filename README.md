# CanaryMesh

CanaryMesh is an edge reverse proxy and automated rollback controller. It splits incoming HTTP traffic between a stable upstream service (v1) and a canary service (v2) using weights, sticky sessions, request headers, or path prefixes. A background supervisor tracks error rates and latency percentiles inside a rolling sliding window, cutting traffic to the canary service if thresholds fail.

## Key capabilities

* **Zero buffer streaming**: Forwards HTTP requests and responses as asynchronous streams without loading bodies into memory.
* **Flexible routing**: Supports weighted percentage distribution, sticky cookie hashing, header matchers (`X-Canary: true`), and path prefix rules (`/api/v2/*`).
* **Traffic shadowing (dark launching)**: Duplicates live client requests to the canary in the background with zero impact on production responses.
* **Active health probing**: Periodically monitors upstream `/healthz` endpoints, gates rollout promotions, and proactively trips rollbacks on node failure.
* **Rolling telemetry**: Maintains per second status counts and latency quantiles (p50, p90, p95, p99) over a 60 second circular window.
* **Automated rollback guard**: Inspects error rates and p99 latency every second, reverting canary traffic to 0% upon an SLA breach.
* **Multi-channel alerts and post-mortems**: Dispatches formatted notifications to Discord Embeds, Slack Block Kit, or webhooks, and writes incident post-mortem markdown reports.
* **Interactive web console**: Serves a single-page management dashboard at `/ui` with real-time canvas telemetry charts over Server-Sent Events.
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

In a separate terminal, start the CanaryMesh proxy with a 20% canary split, health probing, and traffic shadowing enabled:

```bash
canarymesh start --stable http://127.0.0.1:8081 --canary http://127.0.0.1:8082 --weight 20 --prober --shadow
```

Open your browser to `http://localhost:8090/ui` to view the web console and control traffic interactively.

To run with the terminal split-screen dashboard:

```bash
canarymesh start --stable http://127.0.0.1:8081 --canary http://127.0.0.1:8082 --weight 20 --dashboard
```

Simulate traffic and inject faults into the canary upstream to trigger an automatic rollback:

```bash
canarymesh simulate --target http://127.0.0.1:8080 --rate 30 --inject-errors
```

## Control plane API and web console

CanaryMesh serves management endpoints on port 8090 by default:

* `GET /ui`: Interactive web operations console with real-time SSE chart.
* `GET /api/v1/canary/status`: Shows active weights, routing metrics, and health status.
* `POST /api/v1/canary/weight`: Sets the canary traffic percentage (`{"weight": 25}`).
* `POST /api/v1/canary/abort`: Forces an immediate rollback, setting canary weight to 0%.
* `POST /api/v1/canary/promote`: Promotes the canary to receive 100% of traffic.
* `GET /api/v1/canary/rules`: Inspects active routing rules (headers, paths).
* `POST /api/v1/canary/rules/path`: Dynamically adds a path prefix rule (`{"path_prefix": "/checkout", "target": "canary"}`).
* `DELETE /api/v1/canary/rules/path/{rule_id}`: Removes a dynamic path prefix rule.
* `GET /api/v1/canary/shadow`: Inspects traffic shadowing status.
* `POST /api/v1/canary/shadow`: Configures traffic mirroring (`{"enabled": true, "percentage": 100}`).
* `GET /api/v1/canary/incidents`: Lists generated rollback incident post-mortems.
* `GET /api/v1/canary/health`: Checks upstream prober statuses.
* `GET /metrics`: Exports Prometheus metrics.
* `GET /api/v1/canary/live`: Streams live telemetry events over SSE.

## License

MIT License. See [LICENSE](LICENSE) for details.
