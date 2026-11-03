A server-rendered web UI for glancing at what qbt-rules is doing — worker/queue status, job history, and the currently-loaded rules — without needing `qbt-rules jobs list`/`stats` or hitting the JSON API directly, plus an in-browser `rules.yml` editor. It's served on the same port as the API, at the site root.

![qbt-rules dashboard](https://raw.githubusercontent.com/andronics/qbt-rules/main/docs/images/dashboard.png)

### Overview

The dashboard reuses the exact same data the [JSON API](HTTP-API-Reference) already exposes — no separate database, no new query logic. It's server-rendered HTML (FastAPI routes with Jinja2 templates, on the same app as the JSON API), not a JavaScript single-page app: every page is a full HTTP request, there's no client-side framework or build step involved.

| Page | Path | Shows |
|------|------|-------|
| Overview | `/` | Job counts by status, recent activity, rules summary |
| Jobs | `/jobs` | Paginated job list, optionally filtered by `?status=` |
| Job detail | `/jobs/<job_id>` | Full job record — status, timing, result, error |
| Rules | `/rules` | Read-only view of the currently-loaded `rules.yml`, in execution order, with each rule's resolved YAML |
| Rules editor | `/rules/edit` | Edit `rules.yml` in the browser: validates as you type, saves with conflict detection, keeps previous versions in `.history/` (see [HTTP API Reference](HTTP-API-Reference#rules-editor-endpoints) and [Saving rules.yml](#saving-rulesyml)) |
| Login | `/login` | API key entry form |

### Authentication

Same key as the JSON API (see [Security](Security#api-authentication)). Open any dashboard page without a session and you're redirected to `/login?next=<that page>`, which asks for the API key once and keeps you signed in with a session cookie (`qbt_rules_session`, valid for 31 days; changing the API key logs everyone out). The form posts the key in the request body, never in a URL, along with a CSRF token from your session. After signing in you land back on the page you asked for: `next` only ever holds a path on this server (a full URL, `//host` or a backslash trick is reduced to a path), so a crafted link can't send you to another site. The JSON API accepts the same session, so the dashboard's pages call it directly. 0.11 changed the cookie, so a 0.10.x login is dropped once on upgrade.

With no API key configured, the pages send you to the login form, which says what to set instead of asking for a key.

**A one-off link with `?key=`** still works, as a way in (a bookmark, a link from another tool):

```text
http://localhost:5000/jobs?key=YOUR_API_KEY
```

A valid key starts the same session and then redirects to the same URL **without** `key=` (other query parameters are kept), so the key doesn't stay in the address bar, and the page you end up on (and its history entry) doesn't carry it. 0.10.x served the page with the key left in the URL, and its links carried it forward; since 0.11 no dashboard link carries the key. The first request still has the key in its URL, so it can still reach the browser history as a redirected entry, and anything that logs full URLs in front of the server (a reverse proxy) sees it once: prefer the form. The server's own access log replaces every `key=` value with `[REDACTED]`. A wrong key sends you to the login form with an error. A script can send the key as an `X-API-Key` header instead, which signs in and serves the page directly.

### Behind a Reverse Proxy

Every link, form action, script URL and redirect the dashboard emits is relative to the current page (`../jobs`, `./login?next=...`), never an absolute path. So the dashboard works under a path prefix (for example a proxy or ingress that serves it at `https://example.org/qbt/` and strips `/qbt` before passing requests on) without any setting: the browser resolves each link against wherever it really is. Open the prefix with its trailing slash (`/qbt/`, not `/qbt`). The rules editor's calls to the JSON API are relative too.

Static files (`/static/...`, the editor's script and the vendored Ace editor) need no login. Pages ask for them with `?v=<version>`, so an upgrade never runs a cached old script; they're served with `Cache-Control: no-cache` and an ETag, so a reload revalidates cheaply.

### Saving rules.yml

The editor saves `rules.yml` where the server reads it: `/var/lib/qbt-rules/rules.yml`, in the state directory, which the container already gives to `PUID:PGID` (or wherever `rules.file` points). That is why `rules.yml` isn't in `/etc/qbt-rules`: the config directory can stay read-only. With no `rules.yml` yet, the first save creates it. Every save that changes the file keeps the previous version in `/var/lib/qbt-rules/.history/` (the newest 20), and the engine picks the new rules up on its next job, with no restart.

The editor opens read-only, with a banner saying why, when:

- `server.editor_enabled` is `false`;
- `rules.yml` is read-only on disk (for example mode `0444`, as a copy from a read-only volume can be): make it writable by the server's user (`chmod 644`) to edit here;
- `rules.yml` doesn't exist and its directory can't be written, so the first save couldn't create it;
- the history directory can't be written, so the previous version couldn't be kept.

It still validates as you type in every case. A save of a file with errors is refused (`422`), so a `rules.yml` that `qbt-rules validate` rejects (such as 0.10.1's ignored `keep_files` on `delete_torrent`) has to be fixed before the first save.

### Rules View Availability

The rules pages need the running rules config, which `qbt-rules serve` always provides, so this only matters if you build the app yourself (`api.create_app` with `Services(rules=None)`). Without it, the rules page and the editor say so rather than erroring.

### What It Doesn't Do

This is intentionally minimal:

- **No job control.** No canceling jobs from the UI — use the [HTTP API](HTTP-API-Reference) or CLI client (`qbt-rules jobs cancel`, `qbt-rules execute`) for that. Saving rules from the editor can be turned off with `server.editor_enabled: false`.
- **No auto-refresh.** Reload the page to see new data; there's no polling/websocket layer.
- **No historical charts/graphs.** Job counts are current totals, not a time series.

### See Also

- [HTTP API Reference](HTTP-API-Reference) — the JSON endpoints the dashboard's data comes from
- [Architecture Internals](Architecture-Internals) — how `web.py` fits into the overall process model
- [Security](Security) — API key management and network exposure guidance
