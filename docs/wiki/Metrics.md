Prometheus metrics on `/metrics`: job throughput, queue health, rule and action execution, and HTTP traffic. Off by default; nothing extra to install (the image has everything it needs).

### Enabling

```yaml
# /etc/qbt-rules/config.yaml
metrics:
  enabled: true
```

Or set `QBT_RULES_METRICS_ENABLED=true` (see [In-Depth Configuration](In-Depth-Configuration#settings) for the variable and `_FILE` pattern every setting follows). While it's off, `/metrics` answers 404.

**From 0.10.x:** the metrics used to need the `metrics` extra (prometheus_client), which the image didn't install, and a multiprocess directory. Both are gone: the server is one process and keeps its metrics in memory (interpose's registry, as the template's services do). `metrics.multiproc_dir`, `QBT_RULES_METRICS_MULTIPROC_DIR` and `PROMETHEUS_MULTIPROC_DIR` are refused at startup with a message saying to remove them. Counters start from zero when the server restarts, as Prometheus expects.

### Authentication

`/metrics` needs the API key, like every route except the probes (`/healthz`, `/readyz`, `/api/health`) and `/api/version`; the dashboard's login session isn't accepted. See [Security](Security#api-authentication). Send it as the `X-API-Key` header (preferred) or the `key` query parameter.

With Prometheus 3.x, send the header from a file, so the key isn't in `prometheus.yml` and doesn't show on the Targets page:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: qbt-rules
    metrics_path: /metrics
    http_headers:
      X-API-Key:
        files: [/etc/prometheus/secrets/qbt-rules-api-key]
    static_configs:
      - targets: ["qbt-rules:5000"]
```

On an older Prometheus without `http_headers`, use the query parameter. It works the same, but the key then shows in the target's URL on the Targets page:

```yaml
    params:
      key: ["YOUR_API_KEY"]
```

**Kubernetes:** admit the scraper's namespace to the pod on the HTTP port in the NetworkPolicy (template-container's file has a commented allowance for a `monitoring` namespace), and keep `/metrics` off a public ingress route. The key is still required when the scraper is in the cluster.

### Example scrape

```text
# HELP qbt_rules_build_info The running version: always 1
# TYPE qbt_rules_build_info gauge
qbt_rules_build_info{version="0.11.0"} 1
# HELP qbt_rules_queue_depth Current pending queue depth
# TYPE qbt_rules_queue_depth gauge
qbt_rules_queue_depth{backend="SQLiteQueue"} 1
# HELP qbt_rules_jobs_total Total jobs by status
# TYPE qbt_rules_jobs_total gauge
qbt_rules_jobs_total{status="cancelled"} 0
qbt_rules_jobs_total{status="completed"} 1
qbt_rules_jobs_total{status="failed"} 1
qbt_rules_jobs_total{status="pending"} 1
qbt_rules_jobs_total{status="processing"} 0
# HELP qbt_rules_worker_running Worker thread running (1) or not (0)
# TYPE qbt_rules_worker_running gauge
qbt_rules_worker_running 1
# HELP qbt_rules_actions_executed_total Total actions executed by the rules engine (excludes dry-run and idempotent skips)
# TYPE qbt_rules_actions_executed_total counter
qbt_rules_actions_executed_total{action_type="add_tag",result="success"} 1
# HELP qbt_rules_http_requests_total Total HTTP requests
# TYPE qbt_rules_http_requests_total counter
qbt_rules_http_requests_total{endpoint="stats",method="GET",status="200"} 1
...
```

The content type is `text/plain; version=0.0.4; charset=utf-8`. A metric with nothing recorded yet still has its `# HELP` and `# TYPE` lines.

### Metric Reference

The names, types and labels are the ones 0.10.x exported, so dashboards and alerts keep working. One metric is new: `qbt_rules_build_info`.

**Build info:**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `qbt_rules_build_info` | Gauge | `version` | Always `1`; `version` is the running version |

**Event counters and histograms**, counted as things happen:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `qbt_rules_http_requests_total` | Counter | `endpoint`, `method`, `status` | Every HTTP request except `/metrics` itself. `endpoint` is the route's name (`list_jobs`, `execute`, `login`, `static`, ...), `unknown` for a path that matches no route |
| `qbt_rules_http_request_duration_seconds` | Histogram | `endpoint`, `method` | HTTP request latency |
| `qbt_rules_actions_executed_total` | Counter | `action_type`, `result` | Every action the rules engine actually runs (`result` is `success` or `failure`); dry runs and idempotent skips never reach it |
| `qbt_rules_job_duration_seconds` | Histogram | *(none)* | Time from job start to completion, success or failure |
| `qbt_rules_scheduler_fires_total` | Counter | `result` | Internal cron scheduler fires: `success` queued the job, `failure` couldn't (see [Scheduling](Scheduling)) |

Both histograms use the buckets 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5 and 10 seconds (prometheus_client's defaults, as in 0.10.x).

**State gauges**, read on every scrape from the same data [`/api/stats`](HTTP-API-Reference) and [`/api/health`](HTTP-API-Reference) expose:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `qbt_rules_queue_depth` | Gauge | `backend` | Current pending queue depth (`backend` is `SQLiteQueue` or `RedisQueue`) |
| `qbt_rules_jobs_total` | Gauge | `status` | Total jobs by status (`pending`/`processing`/`completed`/`failed`/`cancelled`) |
| `qbt_rules_worker_running` | Gauge | *(none)* | `1` if the worker thread is running, `0` otherwise |
| `qbt_rules_worker_last_job_completed_timestamp_seconds` | Gauge | *(none)* | Unix timestamp of the last completed job; no sample until one has completed |
| `qbt_rules_scheduler_entries` | Gauge | *(none)* | Number of configured `schedule:` entries |

### Cardinality

Every label takes its values from a fixed set: the action types in [Actions](Actions) (about 20), the HTTP methods and status codes, and the app's route names. Traffic can't add series: an unusual HTTP method isn't counted, and an unknown path counts as `endpoint="unknown"`. Rule names are **not** a label anywhere: they're free-form text with no bound. For per-rule visibility, pair a rule with [`notify`](Actions#notify) or [`add_tag`](Actions#add_tag).

### What's Not Instrumented

- **qBittorrent API calls** (`qbittorrent.py`): worth adding if per-call latency or error visibility becomes a real need.
- **Per-rule granularity**: see Cardinality above.
- **Queue backend internals**: the state gauges above cover what the backends expose (`get_stats()`, `get_queue_depth()`).

### See Also

- [HTTP API Reference](HTTP-API-Reference): the JSON endpoints several state gauges are sourced from
- [Dashboard](Dashboard): the other read-only surface (`/`, `/jobs`, `/rules`)
- [Scheduling](Scheduling): the internal cron scheduler `qbt_rules_scheduler_fires_total` tracks
- [Security](Security): API key management, what `/metrics` exposes
