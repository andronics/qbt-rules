Optional Prometheus metrics via a `/metrics` endpoint — job throughput, queue health, rule/action execution, and HTTP traffic. Off by default; requires the `metrics` extra.

### Enabling

The published image doesn't include the `metrics` extra (only `redis`). From source, install it with:

```bash
uv sync --extra metrics
```

```yaml
# config.yaml
metrics:
  enabled: true
  multiproc_dir: /tmp/qbt-rules-metrics   # default shown, usually fine as-is
```

Or via environment variables: `QBT_RULES_METRICS_ENABLED=true` (and `QBT_RULES_METRICS_MULTIPROC_DIR` if you need a non-default directory — see [In-Depth Configuration](In-Depth-Configuration#settings) for the full env var/`_FILE` pattern this follows like every other section).

If `metrics.enabled: true` but the `metrics` extra isn't installed, the server fails to start with a clear error rather than crashing on the first scrape:

```text
ValueError: metrics.enabled is true but the 'prometheus_client' package isn't installed. Install with: pip install qbt-rules[metrics]
```

### Authentication

`/metrics` requires the API key, the same as every route except `/api/health` and `/api/version` — see [Security](Security#api-authentication). Prometheus's own `scrape_config` supports this via a custom header or the query param directly:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: qbt-rules
    metrics_path: /metrics
    params:
      key: ["YOUR_API_KEY"]
    static_configs:
      - targets: ["qbt-rules:5000"]
```

(Or `authorization: {credentials: YOUR_API_KEY}` with a small reverse-proxy rule translating the bearer token into `X-API-Key`, if you'd rather not put the key in `prometheus.yml` directly — either works, since `require_api_key` accepts the key via query param or `X-API-Key` header identically.)

### Fork-safety: why this needs `multiproc_dir` at all

qbt-rules already learned this lesson once, with the internal [Scheduler](Scheduling#running-with-multiple-server-workers): Gunicorn's `preload_app` + fork model means a naive in-process counter gets forked into `server.workers` independent, unsynchronized copies — one per Gunicorn worker process — silently undercounting everything the moment `server.workers > 1`.

Prometheus's Python client solves this with **multiprocess mode**: every process (the master and every forked worker) writes its own file into `multiproc_dir`, and `/metrics` aggregates across every file in that directory on each scrape. qbt-rules handles all of this automatically — clearing stale files from a previous run at startup, registering a Gunicorn `child_exit` hook, and only ever needing `multiproc_dir` to be a writable directory (the default lives under `/tmp`, already writable in the standard Docker image — no new volume needed).

**Verified empirically** (matching the Scheduler's own verification standard — reasoning about Gunicorn fork semantics on paper isn't good enough): a real 2-worker server correctly summed HTTP request and job counts across both forked workers plus the master process. Killing a worker mid-run and letting Gunicorn respawn a replacement didn't lose or double-count anything — a dead worker's historical counter/histogram contributions correctly keep counting forever (that's the *correct* behavior: "this request really happened" doesn't stop being true just because the process that recorded it is gone), while its current-state gauges (queue depth, job counts by status) are recomputed fresh on every single scrape rather than tracked per-process at all, so a dead worker can't leave a stale gauge reading behind in the first place.

### Metric Reference

**Event counters/histograms** — genuine in-process events, nothing else tracks these:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `qbt_rules_http_requests_total` | Counter | `method`, `endpoint`, `status` | Every HTTP request except `/metrics` itself |
| `qbt_rules_http_request_duration_seconds` | Histogram | `method`, `endpoint` | HTTP request latency |
| `qbt_rules_actions_executed_total` | Counter | `action_type`, `result` | Every action the rules engine actually runs — excludes dry-run and idempotent-skip, which never reach real execution |
| `qbt_rules_job_duration_seconds` | Histogram | *(none)* | Time from job start to completion, success or failure |
| `qbt_rules_scheduler_fires_total` | Counter | `result` | Internal cron scheduler fire attempts (see [Scheduling](Scheduling)) |

**State gauges** — computed fresh on every scrape from the same data [`/api/stats`](HTTP-API-Reference#get-apistats) and [`/api/health`](HTTP-API-Reference#get-apihealth) already expose, not tracked incrementally:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `qbt_rules_queue_depth` | Gauge | `backend` | Current pending queue depth |
| `qbt_rules_jobs_total` | Gauge | `status` | Total jobs by status (`pending`/`processing`/`completed`/`failed`/`cancelled`) |
| `qbt_rules_worker_running` | Gauge | *(none)* | `1` if the worker thread is running, `0` otherwise |
| `qbt_rules_worker_last_job_completed_timestamp_seconds` | Gauge | *(none)* | Unix timestamp of the last completed job; absent if none have completed yet |
| `qbt_rules_scheduler_entries` | Gauge | *(none)* | Number of configured `schedule:` entries |

### Cardinality

`action_type` is deliberately the only label on action-execution metrics — bounded to the fixed set of action names in [Actions](Actions) (~20 today). Rule names are **not** a label anywhere: they're free-form user text with no cardinality bound, and a large or dynamically-generated rule set could otherwise create an unbounded number of time series in Prometheus/Grafana. If you need per-rule visibility, pair a rule with [`notify`](Actions#notify) or [`add_tag`](Actions#add_tag) instead and track it that way.

### What's Not Instrumented

- **qBittorrent API calls** (`qbittorrent.py`) — out of scope for this first pass; worth revisiting if per-call qBittorrent latency/error visibility becomes a real need.
- **Per-rule granularity** — see Cardinality above.
- **Queue backend internals** — `SQLiteQueue`/`RedisQueue` have no shared chokepoint to instrument at write time (confirmed via source review), and everything meaningful they'd expose is already covered by the state gauges above, computed from their existing `get_stats()`/`get_queue_depth()` methods instead.

### See Also

- [HTTP API Reference](HTTP-API-Reference) — the JSON endpoints several state gauges are sourced from
- [Dashboard](Dashboard) — the other read-only surface (`/`, `/jobs`, `/rules`), same auth model
- [Scheduling](Scheduling) — the internal cron scheduler `qbt_rules_scheduler_fires_total` tracks, and the Gunicorn fork-safety pattern this reuses
- [Security](Security) — API key management, what `/metrics` exposes
