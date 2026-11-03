# HTTP API Reference

Complete reference for the HTTP API the server exposes (`web.py`, Flask under Gunicorn) — this is what the CLI client, webhooks, and cron submitters all talk to underneath. For the higher-level "how do I submit a job" walkthrough, see [Contexts](Contexts); this page is the endpoint-by-endpoint detail.

This page covers the JSON `/api/*` endpoints. The server also exposes a human-facing, server-rendered dashboard at the site root (`/`, `/jobs`, `/rules`; no `/api/` prefix, returns HTML not JSON) — see [Dashboard](Dashboard) — and, when enabled, a Prometheus `/metrics` endpoint in text exposition format rather than JSON — see [Metrics](Metrics).

**Base URL:** `http://localhost:5000` (or whatever `server.host`/`server.port` you've configured)

## Endpoints

| Method and path | Auth | What it does |
|-----------------|------|--------------|
| `POST /api/execute` | key or session | [Queue a job](#post-apiexecute) |
| `GET /api/jobs` | key or session | [List jobs](#get-apijobs) |
| `GET /api/jobs/<job_id>` | key or session | [One job](#get-apijobsjob_id) |
| `DELETE /api/jobs/<job_id>` | key or session | [Cancel a pending job](#delete-apijobsjob_id) |
| `GET /api/health` | none | [Liveness and queue/worker health](#get-apihealth) |
| `GET /api/stats` | key or session | [Aggregate counters](#get-apistats) |
| `GET /api/version` | none | [Version](#get-apiversion) |
| `GET`, `PUT /api/rules/source`; `POST /api/rules/validate`; `GET /api/rules/history[/<id>]`; `GET /api/rules/catalog`; `GET /api/config/source` | key or session | [The rules editor's endpoints](#rules-editor-endpoints) |
| `GET /metrics` | key | Prometheus metrics, when enabled: see [Metrics](Metrics) |
| `/`, `/jobs`, `/rules`, `/rules/edit`, `/login` | key or session | The HTML [Dashboard](Dashboard) |

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
  "created_at": "2026-01-15T10:30:00.123456",
  "started_at": null,
  "completed_at": null,
  "result": null,
  "error": null
}
```

Errors: `400` invalid parameters, `401` unauthorized, `500` internal error.

### GET /api/jobs

List jobs with filtering and pagination.

| Query Parameter | Required | Description |
|------------------|----------|-------------|
| `status` | No | One of `pending`, `processing`, `completed`, `failed`, `cancelled` |
| `context` | No | Filter by context |
| `limit` | No | Max results, default `50` |
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

An invalid `status` value returns `400`.

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

No authentication required — safe to use as a Docker/Compose healthcheck or load balancer probe.

**Response — `200 OK` (healthy):**

```json
{
  "status": "healthy",
  "version": "0.5.9",
  "queue": { "backend": "SQLiteQueue", "pending_jobs": 2, "processing_jobs": 0 },
  "worker": { "status": "running", "last_job_completed": "2026-01-15T10:25:00" },
  "timestamp": "2026-01-15T10:30:00.000000"
}
```

**Response — `503` (unhealthy)** if the queue backend is unreachable, the worker thread has died, or more than 5 jobs are stuck in `processing` at once — the `errors` array names which.

### GET /api/stats

Aggregate counters and performance data.

```json
{
  "jobs": { "total": 500, "pending": 1, "processing": 0, "completed": 490, "failed": 8, "cancelled": 1 },
  "performance": { "average_execution_time": "1.24s" },
  "queue": { "backend": "SQLiteQueue", "depth": 1 },
  "worker": { "status": "running", "last_job_completed": "2026-01-15T10:25:00" },
  "timestamp": "2026-01-15T10:30:00.000000"
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

`/api/execute` returns immediately (`202`) with a `pending` job — it doesn't wait for the rules to actually run. To get the result synchronously, either use the CLI client's `--wait` flag, or poll:

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
| `GET /api/rules/catalog` | The fields, operators and action types the engine supports (the editor's autocomplete), plus the contexts `config.yml`'s schedule fires |
| `GET /api/config/source` | `config.yml` as text, read-only, with credentials masked |

They answer `503` when the server was started without a config to edit.

## Authentication

Every endpoint except `/api/health` and `/api/version` requires the API key, via either:

```bash
# Query parameter
curl "http://localhost:5000/api/execute?context=nightly&key=YOUR_KEY"

# Header (equivalent, keeps the key out of logs/URLs)
curl -X POST -H "X-API-Key: YOUR_KEY" "http://localhost:5000/api/execute?context=nightly"
```

A missing or incorrect key returns `401 Unauthorized` — see [Security](Security#api-authentication) for key management guidance.

The dashboard's login form (`/login`) exchanges the key for a session cookie. Every endpoint marked "key or session" above also accepts that session, so the dashboard's own pages can call them; a state-changing request (`POST`, `PUT`, `DELETE`) riding on a session must also send the page's `X-CSRF-Token` header, or it gets `403`. Scripts that send the key are unaffected.

## Errors

Every non-2xx response follows the same shape:

```json
{ "error": "Unauthorized", "message": "Invalid or missing API key" }
```

| Status | Meaning |
|--------|---------|
| `400` | Invalid request parameters (bad `status` filter, etc.) |
| `401` | Missing or incorrect API key |
| `404` | Job ID (or endpoint) not found |
| `500` | Unhandled server-side error — check `docker logs` |
| `503` | `/api/health` reporting the server itself is unhealthy |

The rules editor's endpoints add `403` (saving turned off, or a session request without its CSRF token), `412` (stale ETag), `422` (invalid rules), `428` (no ETag) and `503` (no config): see [above](#rules-editor-endpoints).
