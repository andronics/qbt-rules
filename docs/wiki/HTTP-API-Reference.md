# HTTP API Reference

Complete reference for the HTTP API the server exposes (`api.py`, FastAPI under uvicorn) — this is what the CLI client, webhooks, and cron submitters all talk to underneath. For the higher-level "how do I submit a job" walkthrough, see [Contexts](Contexts); this page is the endpoint-by-endpoint detail.

The server listens on port 5000 by default. The live OpenAPI schema is served at `/openapi.json`, and interactive docs at `/docs`. The same schema is committed as [`docs/openapi.json`](https://github.com/andronics/qbt-rules/blob/main/docs/openapi.json): CI fails when it's stale, and a pull request that breaks it must say so (`feat!:`).

The server also serves the human-facing dashboard at the site root (`/`, `/jobs`, `/rules`, `/rules/edit`, `/login`, `/static`; HTML, not JSON) — see [Dashboard](Dashboard) — and, when enabled, a Prometheus `/metrics` endpoint in text exposition format — see [Metrics](Metrics). They're routes on the same app (web.py), left out of the schema.

**Base URL:** `http://localhost:5000` (or whatever `listen.host`/`listen.port` you've configured)

## Endpoints

Generated from the code: don't edit the table, run `uv run scripts/gen-wiki.py`.

<!-- generated:start http-api -->
| Method | Path | Summary |
|---|---|---|
| `GET` | `/api/config/source` | config.yaml as text, read-only, with credentials masked |
| `POST` | `/api/execute` | Queue a job |
| `GET` | `/api/health` | Queue and worker health |
| `GET` | `/api/jobs` | List jobs, newest first |
| `DELETE` | `/api/jobs/{job_id}` | Cancel a pending job |
| `GET` | `/api/jobs/{job_id}` | One job |
| `GET` | `/api/rules/catalog` | The fields, operators and actions rules can use |
| `GET` | `/api/rules/history` | Previous versions of rules.yml, newest first |
| `GET` | `/api/rules/history/{version_id}` | One previous version's content |
| `GET` | `/api/rules/source` | rules.yml as text, with its ETag |
| `PUT` | `/api/rules/source` | Save rules.yml |
| `POST` | `/api/rules/validate` | Validate a candidate rules.yml without saving it |
| `GET` | `/api/stats` | Job counts and timings |
| `GET` | `/api/version` | The running version |
| `GET` | `/healthz` | Liveness: the process is up |
| `GET` | `/readyz` | Readiness: able to serve requests |
<!-- generated:end http-api -->

What each route needs (see [Authentication](#authentication)):

| Auth | Routes |
|------|--------|
| none | `GET /healthz`, `GET /readyz`, `GET /api/health`, `GET /api/version` |
| key only | `GET /api/jobs`, `DELETE /api/jobs/{job_id}`, `GET /api/stats`, `GET /metrics` |
| key or session | every other `/api/*` route, and the dashboard pages |

### Probes

`/healthz` (liveness) answers `200 {"status":"ok"}` as long as the process serves HTTP, and depends on nothing: it's what the image's `HEALTHCHECK` polls. `/readyz` (readiness) answers `503` while the server is starting, or when the worker or scheduler thread has died (the message names it). Orchestrators should restart on the first and route traffic on the second. [`/api/health`](#get-apihealth) is the detailed check: queue, worker and stuck jobs.

### Timestamps

Every timestamp is ISO 8601 in UTC (`"2026-01-15T10:30:00.123456+00:00"`), with either queue backend. *(Changed in 0.11: with the SQLite backend, job timestamps used to be RFC 822 dates such as `"Thu, 15 Jan 2026 10:30:00 GMT"`.)*

### POST /api/execute

Queue a job for execution.

| Query Parameter | Required | Description |
|------------------|----------|-------------|
| `context` | No | Context string to match against rules' `context:` field. Omit for context-agnostic rules only |
| `hash` | No | Restrict evaluation to a single torrent (its 40-char hex hash) |
| `dry_run` | No | `true` to run this job in dry-run mode: rules are evaluated and actions logged as "Would …", nothing changes. Accepts `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`; anything else is a `400`. It can only add dry-run: on a server configured for dry-run, every job is dry-run *(v0.10.0+)* |
| `key` | Yes* | API key (*or use the `X-API-Key` header instead) |

**Response — `202 Accepted`:**

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "context": "nightly",
  "hash": null,
  "dry_run": false,
  "status": "pending",
  "created_at": "2026-01-15T10:30:00.123456+00:00",
  "started_at": null,
  "completed_at": null,
  "result": null,
  "error": null
}
```

Errors: `400` invalid parameters, `401` unauthorized, `403` a session request without its CSRF token, `500` internal error.

A failed job's `error` is one line naming the exception, for example `ConnectionError: Cannot reach qBittorrent server (Host: http://qbittorrent:8080; Error: ...; Fix: Check that qBittorrent is running and the host/port are correct)`, at most 500 characters. The full traceback is in the server log (`docker logs`). *(Changed in 0.11: it used to hold the whole traceback, which `execute --wait` and `jobs status` printed.)*

### GET /api/jobs

List jobs with filtering and pagination.

| Query Parameter | Required | Description |
|------------------|----------|-------------|
| `status` | No | One of `pending`, `processing`, `completed`, `failed`, `cancelled` |
| `context` | No | Filter by context |
| `limit` | No | Max results, default `50`, at most `100` (a larger value is capped) |
| `offset` | No | Pagination offset, default `0` |
| `key` | Yes | API key |

**Response — `200 OK`:**

```json
{
  "total": 150,
  "limit": 50,
  "offset": 0,
  "jobs": [ { "job_id": "...", "context": "nightly", "status": "completed", "...": "..." } ]
}
```

`total` counts the jobs matching `status` and `context`, before `limit` and `offset`; `limit` is the limit applied. An invalid `status`, or a `limit` or `offset` that isn't a whole number of 0 or more, returns `400`. *(Changed in 0.11: `total` used to ignore `context`, `limit` echoed the value asked for, and a non-numeric `limit` was a `500`.)*

### GET /api/jobs/\<job_id\>

Fetch a single job by its UUID. `200` with the job object, or `404` if it doesn't exist.

A **completed** job's `result` (v0.7+) looks like:

```json
{
  "total_torrents": 42,
  "torrents_processed": 3,
  "rules_matched": 4,
  "actions_executed": 3,
  "actions_skipped": 1,
  "errors": 0,
  "dry_run": false,
  "by_rule": {
    "force-start-public-capped": { "matched": 2, "actions_executed": 2, "actions_skipped": 0, "errors": 0 },
    "tag-private-trackers": { "matched": 2, "actions_executed": 1, "actions_skipped": 1, "errors": 0 }
  }
}
```

`by_rule` is keyed by each rule's `id` --
see [Rules-Architecture](Rules-Architecture#rule-identity-id-and-metadescription). Every
enabled rule that ran appears here, even with all-zero counts, if it matched
nothing; a disabled rule never appears. Jobs completed before v0.7 won't have
this key at all -- treat its absence the same as an empty object.

### DELETE /api/jobs/\<job_id\>

Cancel a **pending** job. `200` on success; `400` if the job has already moved past `pending` (processing/completed/failed/cancelled jobs can't be cancelled); `404` if the job doesn't exist.

```json
{ "job_id": "550e8400-...", "status": "cancelled", "message": "Job cancelled successfully" }
```

### GET /api/health

No authentication required. The image's healthcheck polls [`/healthz`](#probes) instead, which depends on nothing; this one checks the queue and the worker.

**Response — `200 OK` (healthy):**

```json
{
  "status": "healthy",
  "version": "0.5.9",
  "queue": { "backend": "SQLiteQueue", "pending_jobs": 2, "processing_jobs": 0 },
  "worker": { "status": "running", "last_job_completed": "2026-01-15T10:25:00+00:00" },
  "timestamp": "2026-01-15T10:30:00.000000+00:00"
}
```

A server started without a setting it needs (no `server.api_key`) is still healthy, since restarting it wouldn't help, but adds `"config_problems": ["server.api_key is not set, ..."]`, one sentence per problem naming what to set. The key is absent when there are none.

**Response — `503` (unhealthy)** if the queue backend is unreachable, the worker thread has died, or more than 5 jobs are stuck in `processing` at once — the `errors` array names which.

### GET /api/stats

Aggregate counters and performance data.

```json
{
  "jobs": { "total": 500, "pending": 1, "processing": 0, "completed": 490, "failed": 8, "cancelled": 1 },
  "performance": { "average_execution_time": "1.24s" },
  "queue": { "backend": "SQLiteQueue", "depth": 1 },
  "worker": { "status": "running", "last_job_completed": "2026-01-15T10:25:00+00:00" },
  "timestamp": "2026-01-15T10:30:00.000000+00:00"
}
```

### GET /api/version

No authentication required.

```json
{ "version": "0.5.9", "api_version": "1.0", "python_version": "3.11.7" }
```

### Job Lifecycle

`pending` → `processing` → `completed` **or** `failed`. A `pending` job can additionally move to `cancelled` via `DELETE /api/jobs/<job_id>`; once a job leaves `pending`, cancellation is no longer possible — let it finish and check the result instead.

### Polling for Completion

`/api/execute` returns immediately (`202`) with a `pending` job — it doesn't wait for the rules to actually run. To get the result synchronously, either use `qbt-rules execute --wait`, or poll:

```bash
JOB_ID=$(curl -s -X POST "http://localhost:5000/api/execute?context=nightly&key=$KEY" | jq -r .job_id)

until [ "$(curl -s "http://localhost:5000/api/jobs/$JOB_ID?key=$KEY" | jq -r .status)" != "pending" ] && \
      [ "$(curl -s "http://localhost:5000/api/jobs/$JOB_ID?key=$KEY" | jq -r .status)" != "processing" ]; do
  sleep 1
done

curl -s "http://localhost:5000/api/jobs/$JOB_ID?key=$KEY" | jq .result
```

### Rules editor endpoints

The dashboard's rules editor (`/rules/edit`) is a static page; everything it shows and saves goes through these JSON endpoints, which scripts can use too:

| Method and path | What it does |
|-----------------|--------------|
| `GET /api/rules/source` | `rules.yml` as text: `{content, etag, modified_at, size, path, editable, readonly_reason}`, with an `ETag` header |
| `POST /api/rules/validate` | Validate a candidate without saving it. Body `{"content": "<yaml>"}`; returns `{valid, issues, counts, summary}`, each issue with its severity, message, path and line/column |
| `PUT /api/rules/source` | Save `rules.yml`. Body `{"content": "<yaml>"}` plus an `If-Match` header (or `"etag"` in the body) holding the ETag the edit started from. `200` saved or unchanged; `400` no content; `403` saving is turned off (`server.editor_enabled: false`) or the file isn't writable; `412` the file changed since that ETag (the response carries the current version); `422` validation found errors; `428` no ETag sent |
| `GET /api/rules/history` | Previous versions kept by editor saves, newest first: `{versions: [{id, saved_at, size}]}` |
| `GET /api/rules/history/<id>` | One previous version's content (restore it by saving it); `404` if there's no such version |
| `GET /api/rules/catalog` | The fields, operators and action types the engine supports (the editor's autocomplete), plus the contexts `config.yaml`'s schedule fires |
| `GET /api/config/source` | `config.yaml` as text, read-only, with credentials masked |

They answer `503` when the server was started without a config to edit.

## Authentication

Every endpoint except the probes (`/healthz`, `/readyz`, `/api/health`) and `/api/version` requires the API key, via either:

```bash
# Query parameter
curl "http://localhost:5000/api/execute?context=nightly&key=YOUR_KEY"

# Header (equivalent, keeps the key out of logs/URLs)
curl -X POST -H "X-API-Key: YOUR_KEY" "http://localhost:5000/api/execute?context=nightly"
```

A missing or incorrect key returns `401 Unauthorized`, and a server with no key configured returns `503` — see [Security](Security#api-authentication) for key management guidance. The key is compared in constant time, and the access log replaces any `key=` in a URL with `[REDACTED]`.

The dashboard's login form (`/login`) exchanges the key for a session cookie, `qbt_rules_session`. Every endpoint marked "key or session" above also accepts that session, so the dashboard's own pages can call them; a state-changing request (`POST`, `PUT`, `DELETE`) riding on a session must also send the page's `X-CSRF-Token` header, or it gets `403`. A wrong key is a `401` even with a session. Scripts that send the key are unaffected. *(Changed in 0.11: the session moved to the server's session middleware, so a 0.10.x login is dropped once on upgrade.)*

## Errors

Every non-2xx response follows the same shape:

```json
{ "error": "Unauthorized", "message": "Invalid or missing API key" }
```

| Status | Meaning |
|--------|---------|
| `400` | Invalid request parameters: a bad `status` or `dry_run`, a `limit`/`offset` that isn't a whole number of 0 or more, or a body without its `content` string |
| `401` | Missing or incorrect API key |
| `403` | A session request without its CSRF token, or saving `rules.yml` when it can't be saved |
| `404` | Job ID, saved version (or endpoint) not found |
| `405` | The path exists but not with that method (the `Allow` header lists the ones it takes) |
| `413` | Request body over 2 MB |
| `500` | Unhandled server-side error. The body never carries the exception's text: check `docker logs` |
| `503` | `/api/health` reporting the server itself is unhealthy, `/readyz` not ready, or, on any authenticated endpoint, no API key configured on the server (`"message": "No API key is configured on the server: ..."`) |

The rules editor's endpoints add `412` (stale ETag), `422` (invalid rules), `428` (no ETag) and `503` (no config): see [above](#rules-editor-endpoints). The `error` names are fixed, whatever Python version runs the server: `413` is `Payload Too Large` and `422` is `Unprocessable Entity`, as in 0.10.x (Python 3.13 renamed them `Content Too Large` and `Unprocessable Content`), and `414` and `416`, if they ever reach the API, are `URI Too Long` and `Requested Range Not Satisfiable`. *(Changed in 0.11: `405` used to be an HTML page, and some `500`s carried the exception's text.)*
