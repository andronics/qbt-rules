# In-Depth Configuration

This page describes the configuration of the current server: `config.yml` and `rules.yml` in one config directory, overridden by `QBT_RULES_*` environment variables.

## Where configuration comes from

**The config directory.** The server keeps everything in one directory:

| File | What it is |
|------|------------|
| `config.yml` | Server, queue, client, qBittorrent connection, scheduling, integrations and logging settings ([reference below](#configyml-reference)) |
| `rules.yml` | Your automation rules ([reference below](#rulesyml-reference)) |
| `qbt-rules.db` | The SQLite job queue (`queue.sqlite_path`) |
| `qbt-rules.log` | The log file and its rotated copies (`logging.file`) |
| `.history/` | Previous versions of `rules.yml` kept by the dashboard's rules editor |

`config.yml` and `rules.yml` are copied from the packaged defaults on first start if they're missing.

Which directory that is:

1. `--config-dir DIR` on the command line
2. the `CONFIG_DIR` environment variable
3. `./config`, if it exists (bare metal)
4. `/var/lib/qbt-rules`, the image's state directory and volume

In the container that's `/var/lib/qbt-rules`: mount it as a volume (see [Deployment](Deployment)). The old `/config` directory is gone, with no fallback. The image also has `/etc/qbt-rules`, and [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) mounts `./config` there read-only, but the server doesn't read anything from it yet: keep `config.yml` in the state directory.

**Overrides.** Every value in `config.yml` can be overridden. Resolution order (highest to lowest priority):

1. CLI flags (e.g. `--server-port 5000`)
2. `_FILE`-suffixed environment variable (e.g. `QBT_RULES_SERVER_API_KEY_FILE=/run/secrets/api_key`)
3. Environment variable directly (e.g. `QBT_RULES_SERVER_API_KEY=abc123`)
4. This config file
5. Default value

`config.yml` isn't hot-reloaded: restart the server to pick up a change. `rules.yml` is re-read whenever it changes on disk.

**Listen port and the healthcheck.** The image's `HEALTHCHECK` polls `/api/health` on `QBT_RULES_LISTEN_PORT` (default `5000`), not on `server.port`. If you move the server with `QBT_RULES_SERVER_PORT`, set `QBT_RULES_LISTEN_PORT` to the same value, or the container reports unhealthy.

## Settings

### config.yml Reference

`config.yml` contains server, queue, client, qBittorrent connection, and logging settings. It lives in the config directory (see [above](#where-configuration-comes-from)); a default copy is created automatically on first run if one doesn't already exist.

| Section | Parameter | Type | Default | Description |
|---------|-----------|------|---------|-------------|
| **server** | `host` | string | `0.0.0.0` | HTTP API bind address (used with `--serve`) |
| | `port` | integer | `5000` | HTTP API port |
| | `api_key` | string | *(required)* | API key clients/webhooks must present |
| | `workers` | integer | `1` | Gunicorn worker processes |
| | `editor_enabled` | boolean | `true` | Allow saving `rules.yml` from the dashboard's rules editor (`/rules/edit`). `false` keeps the editor read-only (it still validates); a `rules.yml` made read-only on disk is never written either way |
| **queue** | `backend` | string | `sqlite` | Job queue backend: `sqlite` or `redis` |
| | `sqlite_path` | string | `/var/lib/qbt-rules/qbt-rules.db` | SQLite database path (when `backend: sqlite`) |
| | `redis_url` | string | *(unset)* | Redis connection URL (when `backend: redis`), e.g. `redis://[:password@]host[:port][/db]` |
| | `cleanup_after` | string/int | `7d` | Job retention period — `Xd`/`Xw` or a raw integer of seconds |
| **client** | `server_url` | string | `http://localhost:5000` | Server URL the CLI client submits jobs to |
| | `api_key` | string | *(required)* | Must match `server.api_key` |
| **qbittorrent** | `host` | string | `http://localhost:8080` | qBittorrent Web UI URL |
| | `username` | string | `admin` | Web UI username |
| | `password` | string | *(required)* | Web UI password |
| **rules** | `file` | string | `/var/lib/qbt-rules/rules.yml` | Path to the rules file |
| **schedule** | *(list)* | list | `[]` | Internal cron entries (`cron`/`context` pairs) — see [Scheduling](Scheduling). List-structured, so it uses indexed `QBT_RULES_SCHEDULE_<N>_CRON`/`_<N>_CONTEXT` env vars rather than a single variable — see below |
| **notifications** | `webhook_url` | string | *(unset)* | Default webhook URL for the [`notify`](Actions#notify) action when a rule omits `params.url` |
| | `service` | string | `generic` | Default service (`discord`/`slack`/`ntfy`/`generic`) when a rule omits `params.service` |
| **integrations** | `sonarr.url` | string | *(unset)* | Sonarr base URL, for the [`arr_blocklist`](Actions#arr_blocklist) action |
| | `sonarr.api_key` | string | *(unset)* | Sonarr API key |
| | `radarr.url` | string | *(unset)* | Radarr base URL, for the [`arr_blocklist`](Actions#arr_blocklist) action |
| | `radarr.api_key` | string | *(unset)* | Radarr API key |
| | `trackie.url` | string | *(unset)* | [trackie](https://github.com/andronics/trackie) base URL, for the [`tracker.*`](Available-Fields#tracker-seeding-stats-trackie) fields |
| | `trackie.max_age` | duration | `3 hours` | Tracker data older than this counts as missing (seconds or a duration) |
| | `trackie.timeout` | number | `10` | Seconds for the snapshot request |
| **metrics** | `enabled` | boolean | `false` | Enable the [Prometheus `/metrics` endpoint](Metrics) — requires the `metrics` extra (`uv sync --extra metrics`; the image doesn't include it) |
| | `multiproc_dir` | string | `/tmp/qbt-rules-metrics` | Shared directory for `prometheus_client`'s multiprocess mode, required for correct metrics under `server.workers > 1` |
| **logging** | `level` | string | `INFO` | Log level for both the console and the log file: `DEBUG`, `INFO`, `WARNING`, `ERROR`. `DEBUG` logs every rule evaluation per torrent, so the file grows quickly |
| | `file` | string | `/var/lib/qbt-rules/qbt-rules.log` | Log file path |
| | `max_bytes` | integer | `10485760` (10 MB) | Rotate the log file when it reaches this size: it is renamed to `qbt-rules.log.1` (older files shift to `.2`, `.3`, ...) and a new file is started. `0` disables rotation. With `server.workers > 1` each Gunicorn worker rotates the same file, so a few lines can land in the wrong file around a rotation |
| | `backup_count` | integer | `5` | Number of rotated log files to keep |
| | `trace_mode` | boolean | `false` | Include module/function/line numbers; enables `--trace`-style detail for every job |
| | `http_access` | boolean | `false` | Log every HTTP request (including health checks) — noisy, off by default |
| **engine** | `dry_run` | boolean | `false` | Dry-run every job: rules are evaluated and actions logged as "Would …", nothing changes. Env: `QBT_RULES_DRY_RUN` (no section prefix) |
| *(top-level)* | `version` | integer | `1` | Schema marker (v0.7+), read via `config.get('version', 1)`. Not consulted by qbt-rules today — a forward-compat hook for future migrations. Safe to leave as-is |

### Environment Variable Overrides

There is no `${VARIABLE_NAME}` or `${VARIABLE_NAME:-default}` expansion syntax inside `config.yml` — every config key instead has a matching `QBT_RULES_*` environment variable that overrides it directly:

| Config key | Environment variable |
|------------|----------------------|
| `server.host` | `QBT_RULES_SERVER_HOST` |
| `server.port` | `QBT_RULES_SERVER_PORT` |
| `server.api_key` | `QBT_RULES_SERVER_API_KEY` |
| `server.workers` | `QBT_RULES_SERVER_WORKERS` |
| `server.editor_enabled` | `QBT_RULES_SERVER_EDITOR_ENABLED` |
| `queue.backend` | `QBT_RULES_QUEUE_BACKEND` |
| `queue.sqlite_path` | `QBT_RULES_QUEUE_SQLITE_PATH` |
| `queue.redis_url` | `QBT_RULES_QUEUE_REDIS_URL` |
| `queue.cleanup_after` | `QBT_RULES_QUEUE_CLEANUP_AFTER` |
| `client.server_url` | `QBT_RULES_CLIENT_SERVER_URL` |
| `client.api_key` | `QBT_RULES_CLIENT_API_KEY` |
| `qbittorrent.host` | `QBT_RULES_QBITTORRENT_HOST` |
| `qbittorrent.username` | `QBT_RULES_QBITTORRENT_USERNAME` |
| `qbittorrent.password` | `QBT_RULES_QBITTORRENT_PASSWORD` |
| `rules.file` | `QBT_RULES_RULES_FILE` |
| `notifications.webhook_url` | `QBT_RULES_NOTIFICATIONS_WEBHOOK_URL` |
| `notifications.service` | `QBT_RULES_NOTIFICATIONS_SERVICE` |
| `integrations.sonarr.url` | `QBT_RULES_INTEGRATIONS_SONARR_URL` |
| `integrations.sonarr.api_key` | `QBT_RULES_INTEGRATIONS_SONARR_API_KEY` |
| `integrations.radarr.url` | `QBT_RULES_INTEGRATIONS_RADARR_URL` |
| `integrations.radarr.api_key` | `QBT_RULES_INTEGRATIONS_RADARR_API_KEY` |
| `integrations.trackie.url` | `QBT_RULES_INTEGRATIONS_TRACKIE_URL` |
| `integrations.trackie.max_age` | `QBT_RULES_INTEGRATIONS_TRACKIE_MAX_AGE` |
| `integrations.trackie.timeout` | `QBT_RULES_INTEGRATIONS_TRACKIE_TIMEOUT` |
| `metrics.enabled` | `QBT_RULES_METRICS_ENABLED` |
| `metrics.multiproc_dir` | `QBT_RULES_METRICS_MULTIPROC_DIR` |
| `logging.level` | `QBT_RULES_LOGGING_LEVEL` |
| `logging.file` | `QBT_RULES_LOGGING_FILE` |
| `logging.max_bytes` | `QBT_RULES_LOGGING_MAX_BYTES` |
| `logging.backup_count` | `QBT_RULES_LOGGING_BACKUP_COUNT` |
| `logging.trace_mode` | `QBT_RULES_LOGGING_TRACE_MODE` |
| `logging.http_access` | `QBT_RULES_LOGGING_HTTP_ACCESS` |
| `engine.dry_run` | `QBT_RULES_DRY_RUN` |

Every one of these follows a mechanical `QBT_RULES_<SECTION>_<FIELD>` naming convention, with one intentional exception: `engine.dry_run` has no section prefix at all (`QBT_RULES_DRY_RUN`). (`qbittorrent.user`/`.pass` were undocumented legacy aliases for `.username`/`.password` in older versions — removed; `username`/`password` are the only accepted keys now.)

**`schedule:` is the one section above that doesn't fit this table** — being a list rather than a single value, it uses **indexed** environment variables instead: `QBT_RULES_SCHEDULE_<N>_CRON` / `QBT_RULES_SCHEDULE_<N>_CONTEXT`, starting at `N=0` and counting up contiguously (enumeration stops at the first missing index). See [Scheduling](Scheduling) for the full pattern, including `_FILE` support and the "environment entirely replaces config.yml, not merged" precedence rule.

## Secrets

**Every** `QBT_RULES_*` variable has a `_FILE` counterpart that reads the value from a file instead of taking it literally — the standard pattern for Docker/Compose secrets:

```yaml
# compose.yml
services:
  qbt-rules:
    environment:
      QBT_RULES_SERVER_API_KEY_FILE: /run/secrets/api_key
      QBT_RULES_QBITTORRENT_PASSWORD_FILE: /run/secrets/qbt_password
    secrets:
      - api_key
      - qbt_password
secrets:
  api_key:
    file: ./secrets/api_key.txt
  qbt_password:
    file: ./secrets/qbt_password.txt
```

In a typical Docker deployment, most people set the required values (`server.api_key`, `qbittorrent.username`/`password`) via environment variables in `compose.yml` and leave `config.yml` at its defaults for everything else.

The secrets qbt-rules uses, and what each one grants:

| Setting | Grants |
|---------|--------|
| `server.api_key` (and `client.api_key`) | Every API endpoint and the dashboard: queuing jobs runs any action in `rules.yml`, including deletes |
| `qbittorrent.password` | Full control of qBittorrent |
| `notifications.webhook_url` | Posting to your Discord/Slack/ntfy channel (the token is in the URL) |
| `integrations.sonarr.api_key`, `integrations.radarr.api_key` | Full control of that Sonarr/Radarr instance |

See [Security](Security#credential-management) for how to keep them out of `docker inspect`, and how to rotate the API key.

## Examples

**Example config.yml:**

```yaml
server:
  host: 0.0.0.0
  port: 5000
  api_key: your-secure-api-key-here
  workers: 1

queue:
  backend: sqlite
  sqlite_path: /var/lib/qbt-rules/qbt-rules.db
  cleanup_after: 7d

client:
  server_url: http://localhost:5000
  api_key: your-secure-api-key-here

qbittorrent:
  host: http://qbittorrent:8080
  username: admin
  password: adminpass

rules:
  file: /var/lib/qbt-rules/rules.yml

# Optional -- see Scheduling
schedule:
  - cron: "*/30 * * * *"
    context: cron

# Optional -- see Actions#notify
notifications:
  webhook_url: https://discord.com/api/webhooks/your-webhook-here
  service: discord

# Optional -- see Actions#arr_blocklist
integrations:
  sonarr:
    url: http://sonarr:8989
    api_key: your-sonarr-api-key-here
  radarr:
    url: http://radarr:7878
    api_key: your-radarr-api-key-here
  trackie:
    url: http://trackie:8080

# Optional -- see Metrics
metrics:
  enabled: false
  multiproc_dir: /tmp/qbt-rules-metrics

logging:
  level: INFO
  file: /var/lib/qbt-rules/qbt-rules.log
  max_bytes: 10485760
  backup_count: 5
  trace_mode: false
  http_access: false
```

A minimal Docker setup sets only what differs from the defaults, as environment variables, and leaves `config.yml` as created on first start:

```yaml
environment:
  QBT_RULES_SERVER_API_KEY_FILE: /run/secrets/api_key
  QBT_RULES_QBITTORRENT_HOST: http://qbittorrent:8080
  QBT_RULES_QBITTORRENT_USERNAME: admin
  QBT_RULES_QBITTORRENT_PASSWORD_FILE: /run/secrets/qbt_password
```

A busier setup with a Redis queue and an internal schedule:

```yaml
environment:
  QBT_RULES_QUEUE_BACKEND: redis
  QBT_RULES_QUEUE_REDIS_URL: redis://redis:6379/0
  QBT_RULES_SCHEDULE_0_CRON: "*/30 * * * *"
  QBT_RULES_SCHEDULE_0_CONTEXT: cron
  QBT_RULES_SCHEDULE_1_CRON: "0 3 * * *"
  QBT_RULES_SCHEDULE_1_CONTEXT: nightly
```

The complete Redis stack is on the [Deployment](Deployment#redis-queue) page; the schedule format is on [Scheduling](Scheduling).

## rules.yml Reference

The `rules.yml` file defines automation rules, and optionally a `refs:` block (see [Reusable References](Reusable-References)). Rules execute in **file order** (top to bottom) — there's no separate priority/ordering field.

**File Structure:**

```yaml
version: 1       # optional — schema marker, see below

refs:            # optional — see Reusable References
  vars: {}
  conditions: {}
  actions: {}
  meta: {}       # optional (v0.7+) — descriptive metadata for conditions/actions blocks

rules:
  - id: stable-slug-identifier
    meta:
      description: "Descriptive, human-readable text for logs/dashboard"
    enabled: true
    stop_on_match: false
    context: manual   # optional — see Contexts
    conditions:
      all: []   # All conditions must match (AND)
      any: []   # Any condition must match (OR)
      none: []  # No conditions can match (NOT)
    actions:
      - type: action_name
        params: {}
```

**Rule Field Reference:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | **Yes** | - | Short, unique, stable identifier — see [Rules-Architecture](Rules-Architecture#rule-identity-id-and-metadescription). Enforced unique at load time |
| `meta.description` | string | No | *(falls back to `id`)* | Human-readable text for logs/dashboard/CLI. `meta` itself is optional |
| `enabled` | boolean | No | `true` | Set to `false` to disable the rule without deleting it |
| `stop_on_match` | boolean | No | `false` | If true, matched torrents skip remaining rules |
| `context` | string or list | No | *(none — runs regardless of context)* | Sibling of `conditions`/`actions`, **not** nested inside `conditions`. See [Contexts](Contexts) |
| `conditions` | object or list | **Yes** | - | Conditions object (see below). Must be present — use `{}` for an unconditional rule, not a blank/null value |
| `actions` | list | **Yes** | - | List of actions to execute |

A top-level `version:` key (a sibling of `refs:`/`rules:`, v0.7+) is a schema
marker, read via `Config.rules_version` and defaulting to `1` when absent —
not consulted by qbt-rules today, purely a forward-compat hook.

**Conditions Object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `all` | list | No | All conditions must be true (AND) |
| `any` | list | No | At least one condition must be true (OR) |
| `none` | list | No | No conditions can be true (NOT) |

`conditions` can also be a **bare list** instead of an object — every entry is implicitly AND-ed together, equivalent to wrapping it in `all:`. This is the form used throughout [Reusable References](Reusable-References) to mix `$ref: conditions.name` entries with inline conditions.

**Condition Item:**

```yaml
- field: info.name
  operator: contains
  value: "1080p"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `field` | string | Yes | Dot notation field path (e.g., `info.name`, `trackers.url`) |
| `operator` | string | Yes | Comparison operator (see [Conditions](Conditions#operator-reference)) |
| `value` | any | Yes | Value to compare against |

**Action Item:**

```yaml
- type: set_category
  params:
    category: movies
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Action name (see [Actions](Actions)) |
| `params` | object | No | Action-specific parameters |

## Key Concepts

### File Order Execution

Rules execute **top to bottom** in the order they appear in `rules.yml`. This provides predictable, easy-to-understand behavior — there is no rule-level priority field that reorders execution independent of file position.

**Best Practice:**

- **Top:** Blocking/filtering rules with `stop_on_match: true`
- **Middle:** Categorization and tagging rules
- **Bottom:** Cleanup and maintenance rules

**Example:**

```yaml
rules:
  # 1. Block unwanted content first (stops further processing)
  - id: block-archives
    stop_on_match: true
    # ...

  # 2. Then categorize
  - id: categorize-movies
    # ...

  # 3. Finally cleanup
  - id: remove-old-completed
    # ...
```

### stop_on_match Behavior

When `stop_on_match: true` and a torrent matches the rule:

- The rule's actions execute on that torrent
- That torrent **skips all remaining rules** in the current job
- Other torrents continue processing normally

**Use Cases:**

- Content filtering (block unwanted, skip other rules)
- Mutually exclusive categorization
- Early exit for special cases

**Example:**

```yaml
rules:
  - id: block-unwanted
    stop_on_match: true  # Matched torrents stop here
    conditions:
      any:
        - field: info.name
          operator: contains
          value: "unwanted"
    actions:
      - type: stop

  - id: categorize-all  # Blocked torrents never reach this rule
    # ...
```

### Empty Condition Groups

Empty condition groups are **ignored** (treated as always true):

```yaml
conditions:
  all: []  # Empty - ignored
  any:
    - field: info.ratio
      operator: ">"
      value: 2.0
  # Effectively: any conditions must match
```

If **all groups are empty or absent**, the rule matches **all torrents** — but `conditions` must still be present as an explicit empty object, not blank/null:

```yaml
conditions: {}  # Matches everything

# NOT this — a blank value parses as null and logs an evaluation
# error per torrent instead of matching everything:
# conditions:
```
