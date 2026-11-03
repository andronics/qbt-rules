A server-rendered web UI for glancing at what qbt-rules is doing — worker/queue status, job history, and the currently-loaded rules — without needing `--list-jobs`/`--stats` or hitting the JSON API directly, plus an in-browser `rules.yml` editor. It's served on the same port as the API, at the site root.

![qbt-rules dashboard](https://raw.githubusercontent.com/andronics/qbt-rules/main/docs/images/dashboard.png)

### Overview

The dashboard reuses the exact same data the [JSON API](HTTP-API-Reference) already exposes — no separate database, no new query logic. It's server-rendered HTML (Flask + Jinja2), not a JavaScript single-page app: every page is a full HTTP request, there's no client-side framework or build step involved.

| Page | Path | Shows |
|------|------|-------|
| Overview | `/` | Job counts by status, recent activity, rules summary |
| Jobs | `/jobs` | Paginated job list, optionally filtered by `?status=` |
| Job detail | `/jobs/<job_id>` | Full job record — status, timing, result, error |
| Rules | `/rules` | Read-only view of the currently-loaded `rules.yml`, in execution order, with each rule's resolved YAML |
| Rules editor | `/rules/edit` | Edit `rules.yml` in the browser: validates as you type, saves with conflict detection, keeps previous versions in `.history/` (see [HTTP API Reference](HTTP-API-Reference#rules-editor-endpoints)) |
| Login | `/login` | API key entry form |

### Authentication

Same key as the JSON API (see [Security](Security#api-authentication)). Open any dashboard page without it and you're redirected to `/login`, which asks for the API key once and keeps you signed in with a session cookie (`qbt_rules_session`, valid for 31 days; changing the API key logs everyone out). The JSON API accepts the same session, so the dashboard's pages call it directly. 0.11 changed the cookie, so a 0.10.x login is dropped once on upgrade. The `?key=` query parameter still works too: every link within the dashboard carries it forward automatically as you navigate.

```text
http://localhost:5000/dashboard?key=YOUR_API_KEY
```

**Trade-off of `?key=`:** because the key lives in the URL rather than a header, it's more likely to end up in browser history or autocomplete than a scripted client's `X-API-Key` header would be. There's no built-in mitigation beyond what's already true of the JSON API's `?key=` support — if that's a concern, put the server behind a reverse proxy with its own auth (see [Security](Security#network-exposure)) and treat the dashboard link like any other bookmarked credential. As a smaller mitigation, the server's access log replaces every `key=` value with `[REDACTED]`, so the key never lands in a log line.

### Rules View Availability

The rules page needs a `Config` reference that isn't always available depending on how `create_app()` was called — in the normal `qbt-rules serve` startup path it always is, so this only matters if you're embedding `create_app()` yourself outside the standard CLI entry point. If it's unavailable, the page says so rather than erroring.

### What It Doesn't Do

This is intentionally minimal:

- **No job control.** No canceling jobs from the UI — use the [HTTP API](HTTP-API-Reference) or CLI client (`--cancel-job`, `qbt-rules --context ...`) for that. Saving rules from the editor can be turned off with `server.editor_enabled: false`.
- **No auto-refresh.** Reload the page to see new data; there's no polling/websocket layer.
- **No historical charts/graphs.** Job counts are current totals, not a time series.

### See Also

- [HTTP API Reference](HTTP-API-Reference) — the JSON endpoints the dashboard's data comes from
- [Architecture Internals](Architecture-Internals) — how `web.py` fits into the overall process model
- [Security](Security) — API key management and network exposure guidance
