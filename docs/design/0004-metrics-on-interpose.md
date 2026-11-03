# 0004: Metrics on interpose's Registry

Status: Proposed
Date: 2026-11-03
Authors: the apps coordinator and Claude (following template-python's decision 0007)

## Context

Step 4e of the template migration. 0.10.x served `/metrics` with prometheus_client in multiprocess mode,
written for Gunicorn's forked workers: a `metrics` extra, a `metrics.multiproc_dir` directory and the
`PROMETHEUS_MULTIPROC_DIR` variable. The image never installed the extra, so `metrics.enabled: true`
failed at startup in the shipped image. Since 4c the server is one uvicorn process (template-python
decision 0008), with the worker and the scheduler as threads. template-python's decision 0007 gives a
service `/metrics` on interpose's `Registry` (`app.state.metrics`, `<package>_build_info`), and its migrating
guide says to re-declare prometheus_client metrics on it, keeping their names. #28 item 4: the 4c port kept
Flask's doubled content type, `...; charset=utf-8; charset=utf-8`.

## Decision

- **The registry is the template's:** `create_app` builds it (`metrics.build_registry`, with
  `qbt_rules_build_info{version} 1`) as `app.state.metrics`, and `metrics.Metrics` registers qbt-rules' own
  metrics on it. One registry per app: no process-global state, so tests don't share counts.
- **Names, types and label sets kept** from 0.10.x: the state gauges `qbt_rules_queue_depth{backend}`,
  `qbt_rules_jobs_total{status}`, `qbt_rules_worker_running`,
  `qbt_rules_worker_last_job_completed_timestamp_seconds`, `qbt_rules_scheduler_entries`; the events
  `qbt_rules_actions_executed_total{action_type,result}`, `qbt_rules_job_duration_seconds`,
  `qbt_rules_scheduler_fires_total{result}`, `qbt_rules_http_requests_total{endpoint,method,status}`,
  `qbt_rules_http_request_duration_seconds{endpoint,method}`, with prometheus_client's default buckets.
  Labels are written in the order prometheus_client's multiprocess collector wrote them (sorted). Nothing
  is renamed; `qbt_rules_build_info` is added.
- **Declared label values** (interpose requires them): the action types from `schema.ACTION_TYPES`, the
  standard HTTP methods, status codes 100-599, the queue class (declared when the services attach) and
  every route's name (declared after the routes are registered). An event outside its set isn't counted
  (an unusual method, an unknown action type); an undeclared route name counts as `unknown`.
- **Threads:** the worker thread (job duration, and the engine's actions), the scheduler thread (fires),
  the event loop (HTTP metrics) and the scrape all touch the registry. interpose's metrics aren't locked,
  so every change and every render holds one lock (`metrics.LOCK`), held for microseconds and never
  across I/O. Decision 0007's alternative, one owning thread per series with every label set created
  before the first scrape, would have meant writing zero-valued series 0.10.x never showed, and a route
  name can be any of about 30.
- **The route** is sync (the template's is async): the state gauges read the queue (SQLite, or Redis over
  the network) first, in the threadpool, then set the gauges and render under the lock. It's in the
  OpenAPI schema (tag `meta`) and answers 404 while `metrics.enabled` is off, before any key check, so
  it looks like no route. Content type: interpose's `text/plain; version=0.0.4; charset=utf-8`, one
  charset (#28 item 4).
- **Auth: the API key stays** (`X-API-Key` or `?key=`; not the session). Decision 0007 makes the
  template's `/metrics` unauthenticated, relying on the NetworkPolicy (template-container v2.1.0's
  commented scraper allowance) and keeping `/metrics` off the ingress. qbt-rules' installs are mostly
  Unraid and plain Docker, with no NetworkPolicy, and 0.10.x already required the key, so scrapers are
  set up for it. Prometheus sends it with `http_headers` (from a file), or `params: {key: [...]}` on an
  older Prometheus. The wiki's Metrics page has both.
- **Removed:** prometheus_client, the `metrics` extra, `metrics.multiproc_dir`,
  `QBT_RULES_METRICS_MULTIPROC_DIR` and `PROMETHEUS_MULTIPROC_DIR`. Each setting is refused at startup
  (REMOVED_KEYS, REFUSED_VARIABLES), as 4b refused its removed settings.

## Alternatives considered

- **Keep prometheus_client** (single-process mode). A second metrics library beside interpose, which every
  service already has, a process-global registry, and still an extra the image would have to install.
- **Unauthenticated, as the template.** Fine behind a NetworkPolicy, but most installs have none; the
  counts and route names would be readable by anyone who can reach the port.
- **Register `/metrics` only when enabled** (4c's way). Keeps it out of `docs/openapi.json` and the wiki's
  generated endpoint table, which decision 0007 wants it in.

## Consequences

- `metrics.enabled: true` works in the shipped image: interpose is a core dependency.
- The exposition differs from 0.10.x only in format: integers without `.0`, no exponent notation
  (`1793707262`, not `1.793707262e+09`), samples sorted by label value, `version=0.0.4` in the content
  type, and `# HELP`/`# TYPE` lines for a metric with no samples yet. Prometheus parses both the same.
- The counters restart from zero with the process (they did under prometheus_client too, once its
  directory was cleared at startup).
- Wiki: Metrics (the metric list, the scrape config), In-Depth-Configuration, Security,
  Architecture-Internals, HTTP-API-Reference.

## Open questions

- None for the code. Whether a Kubernetes deployment should drop the key requirement for an in-cluster
  scraper is a deployment choice; recommendation: keep it, since the key is already in a Secret.
