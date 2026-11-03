# 0002: The JSON API on FastAPI and uvicorn

Status: Proposed
Date: 2026-11-03
Authors: Stephen Cox (timestamps, the error shape, accepting a one-time logout), the apps coordinator and
Claude (the rest, following template-python's decisions 0004 to 0008)

## Context

Step 4c of the template migration. The JSON API (15 routes) was Flask, served by Gunicorn (`preload_app`,
a `post_fork` hook restarting the worker thread in each child, a `when_ready` hook handing log rotation to
the workers, a `FilteredLogger` that dropped health and dashboard lines from the access log because the
dashboard's URLs carried `?key=`). template-python serves FastAPI under uvicorn, one process per pod
(0008), with background threads in the lifespan (0006). The golden responses (#26) pin every route's
status, headers and body byte for byte, and #28 lists the inconsistencies they found. The dashboard pages
(4d), `/metrics` (4e) and the Typer CLI (4f) come later.

## Decision

- **Byte-compatible JSON.** Routes answer with `CompatJSONResponse` (trackie's, its 0001): keys sorted,
  compact, non-ASCII escaped, a final newline, as Flask's `jsonify` wrote them. Pydantic models
  (`api_models.py`) describe the bodies for `docs/openapi.json`; the routes still build dicts, so the
  bytes don't depend on how pydantic serialises.
- **Timestamps are ISO 8601 for both queue backends** (Stephen). The SQLite backend's datetimes were RFC
  822 under Flask; `CompatJSONResponse` writes any datetime with `isoformat()`, which is what the Redis
  backend already stored. A behaviour change for clients, in the release notes.
- **Errors stay `{"error", "message"}`** (Stephen), with Werkzeug's status names (`Payload Too Large`, not
  Python 3.13's `Content Too Large`): `ApiError` for the routes' own, and handlers for Starlette's 404 and
  405, FastAPI's request validation (a 400 naming the parameter) and anything unhandled (a 500 with a
  generic message; the exception is logged, never sent). Not FastAPI's `{"detail"}`.
- **#28 items fixed here:** 1 (`limit=abc` is a 400), 2 (`total` honours `context`: both backends'
  `count_jobs` take it), 3 (the applied limit, at most 100, is echoed), 5 (405 is JSON), 6 (no exception
  text in a 500). 4 (the double charset on `/metrics`) goes with 4e; 7 (Redis queue depth) stays open.
- **Auth unchanged:** the API key as `?key=` or `X-API-Key`, compared in constant time; 503 when none is
  configured. The routes the dashboard calls also take its login session, and a POST, PUT or DELETE on a
  session needs the page's `X-CSRF-Token`.
- **Sessions on Starlette's SessionMiddleware** (Stephen accepted a one-time logout). The cookie is
  `qbt_rules_session` (a new name: 0.10.x's Flask `session` cookie is ignored), signed with a key derived
  from the API key, `SameSite=Lax`, 31 days. `sessions.py` holds what "logged in" and the CSRF token mean,
  for the API, the Flask dashboard and, in 4d, the FastAPI login.
- **The dashboard stays Flask until 4d, mounted under FastAPI** with a2wsgi, for its own paths only
  (`DASHBOARD_PATHS`), so a wrong method on an API path is still a 405 and an unknown path a JSON 404. Its
  session interface reads and writes the ASGI scope's session, so SessionMiddleware writes the one
  cookie. `/metrics` (prometheus_client, key required) stays there until 4e.
- **One process.** `qbt-rules serve` runs uvicorn with the app; the lifespan starts the worker and the
  scheduler as `BackgroundThreads` and joins them on shutdown; `/readyz` names a dead one. `server.workers`
  above 1 is a configuration error (0008). uvicorn handles SIGTERM, which the Gunicorn path ignored.
- **Probes.** `/healthz` is the template's dependency-free liveness, and now the image's `HEALTHCHECK`
  (the copier answer `health_path` moved from `/api/health`): `/api/health` answers 503 for stuck jobs
  or an unreachable queue, which a restart doesn't fix. `/api/health` keeps its body and semantics for
  people and monitors.
- **Access log:** uvicorn's, through `server.AccessLogFilter`: every logged URL has `key=` replaced by
  `[REDACTED]`, and with `logging.http_access` off the polling paths (probes, `/metrics`, `/static/`) are
  left out. Dashboard pages are logged now, since the key no longer shows.
- **The 2 MB body limit** is checked before routing from `Content-Length`, and while reading a body sent
  without one.

## Alternatives considered

- **FastAPI's own JSON and `{"detail"}` errors.** Smaller code, but every client (the CLI, the dashboard
  JS, scripts, trackie's contract test) would see the change, and Stephen chose to keep the shape.
- **Pydantic serialisation of the response models.** Would make the models enforce the bodies, but the
  goldens would then depend on pydantic's float and datetime formatting, and the job `result` is free-form.
- **Leaving the dashboard broken until 4d.** Simpler, but the integration branch would carry a broken UI
  for several PRs; the a2wsgi mount is a few lines and goes away in 4d.
- **Keeping the Flask session format** (itsdangerous with Flask's salt) in a custom middleware. Avoids
  the logout, but means owning a session implementation the template doesn't use.
- **Mounting Flask at `/`.** Starlette prefers a full match over a partial one, so a catch-all mount turns
  every 405 into a Flask 404.

## Consequences

- `docs/openapi.json` describes the real app; the `api-breaking` job flags the change (the PR is `feat!`).
- HEAD on a GET route is a 405 (Flask answered it); nothing in the project uses it.
- Logged-in dashboard users are logged out once on upgrade.
- 4d replaces the Flask mount and the scope session interface with FastAPI routes calling `sessions.py`;
  4e replaces prometheus_client and the Flask `/metrics`.
