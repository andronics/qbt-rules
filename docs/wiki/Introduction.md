# Introduction

## What it is

qbt-rules is a **client-server automation engine** for qBittorrent. A small HTTP server (backed by a persistent SQLite or Redis job queue and a background worker) evaluates declarative YAML rules against your torrents and executes actions — categorize, tag, pause, resume, delete, throttle — with no manual intervention once configured.

A rule is just a condition and a list of actions:

```yaml
- id: clean-up-well-seeded-torrents
  meta:
    description: "Clean up well-seeded torrents"
  context: weekly-cleanup
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
      - field: info.category
        operator: "!="
        value: "keep"
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

See [Quick Start](Quick-Start) to get this running.

## How it works

One container runs the server (`qbt-rules serve`): a Flask HTTP API under Gunicorn, a background worker thread, and an optional internal scheduler. Something submits a **job** — a webhook from qBittorrent's "Run external program", a cron entry, the CLI client (`qbt-rules --context ...`), the [dashboard](Dashboard), or a plain `curl` to the [HTTP API](HTTP-API-Reference) — carrying a free-form context string and, optionally, one torrent's hash. The job is persisted in the queue, so it survives a restart; the worker picks it up, loads `rules.yml`, and walks the rules top to bottom, evaluating each rule's conditions against each torrent's fields (fetched from qBittorrent's Web API) and running the actions of the rules that match. The job's result (rules matched, actions executed or skipped, errors) is stored back on the job. The details are in [Rules Architecture](Rules-Architecture) and [Architecture Internals](Architecture-Internals).

### Why Use This?

**Save Time & Effort:**

- Automatically categorize torrents based on content patterns (movies, TV shows, resolution)
- Clean up old or completed torrents to save disk space
- Tag and organize torrents from specific trackers
- Enforce ratio requirements for private trackers
- Block unwanted or malicious content immediately upon arrival
- Manage bandwidth limits dynamically based on conditions
- Handle hundreds of torrents without manual work

**Flexible & Powerful:**

- Declarative YAML configuration (no coding required)
- Reusable references (`refs:` + `$ref` + `${vars.x}`) — define a condition or action sequence once, reuse it across every rule that needs it
- Rich condition operators (equality, comparison, regex, time-based, list membership)
- Access to 8 different qBittorrent API endpoint categories
- Any number of execution contexts you define yourself (webhooks, cron, manual)
- Dry-run mode for safe testing
- Idempotent actions prevent unnecessary operations

### Key Features

✅ **Declarative YAML Configuration** - Define rules in easy-to-read YAML files

✅ **Client-Server Architecture** - HTTP API + persistent job queue + background worker; jobs survive server restarts

✅ **Reusable References** - Define variables, conditions, and action sequences once under `refs:`, reference them anywhere with `$ref`/`${vars.x}`

✅ **Free-Form Execution Contexts** - No fixed trigger list; webhooks, cron, and manual runs all just pass whatever context string you choose

✅ **Rich Condition Operators** - Equality, comparison, regex, time-based, list operations (`contains`/`not_contains`/`in`/`not_in` all accept list values)

✅ **Dot Notation Field Access** - Access 8 API categories: info, trackers, files, peers, properties, webseeds, transfer, app

✅ **File-Order Execution** - Rules execute top-to-bottom for predictable behavior (no priority/ordering field — file position *is* the order)

✅ **Idempotent Actions** - Smart skipping prevents redundant operations

✅ **Dry-Run Mode** - Test rules safely without making changes

✅ **Web Dashboard** - Jobs, results and rules at a glance, plus an in-browser `rules.yml` editor that validates as you type, on the same port as the API

✅ **Comprehensive Logging** - Detailed logs with optional trace mode

✅ **User-Friendly Errors** - Clear error messages with fix suggestions

✅ **Docker-First Deployment** - Multi-platform images (amd64, arm64) on GHCR

✅ **Multi-Version qBittorrent Support** - v4.1 through v5.1+ via `qbittorrent-api`'s auto-detection

✅ **Human-Readable Sizes** - Use intuitive syntax like `"50GB"` or `"100MB"`

✅ **Nested Conditions** - Complex boolean logic with nested `all`/`any`/`none` groups

## When not to use it

- **Not a content scanner.** Every condition works on the metadata qBittorrent exposes (names, sizes, trackers, state), never on file contents. It's a policy layer, not antivirus: see [Security](Security#threat-model).
- **Not real-time.** A job is queued and worked off asynchronously; a webhook-triggered rule runs seconds after the event, not inside qBittorrent's own event loop. And a magnet link's file list isn't known when it's first added (see [Security](Security#known-limitation-magnet-link-metadata-timing)).
- **Not multi-tenant.** One server per qBittorrent instance, one `rules.yml`, one API key that grants everything. Don't expose it to people you wouldn't give the qBittorrent Web UI password to.
- **Not a library.** It ships as a container image; running from source is for development.

### Requirements

- **Docker** and Docker Compose (recommended — the supported distribution method)
- **qBittorrent** with Web UI enabled
- **System:** anywhere Docker runs (Linux, macOS, Windows, NAS, homelab servers); the image is built for `linux/amd64` and `linux/arm64`
- **Optional:** a Redis server, if you choose `queue.backend: redis` over the SQLite default
