# In-Depth Configuration

This page describes qbt-rules' configuration: the settings (`config.yaml` and `QBT_RULES_*` environment variables), where its files live, and the rules file (`rules.yml`). Moving from 0.10.x? See [Migrating from 0.10.x](#migrating-from-010x).

## Where configuration comes from

Every setting can be given in four places, and the first one that has it wins:

1. `QBT_RULES_<KEY>_FILE`: the path of a file holding the value (Docker and Kubernetes secrets)
2. `QBT_RULES_<KEY>`: an environment variable
3. the YAML config file: `QBT_RULES_CONFIG` or `--config`, default `/etc/qbt-rules/config.yaml`. A missing file is fine.
4. the built-in default

`<KEY>` is the setting's key in upper case, with the dots as underscores: `qbittorrent.host` is `QBT_RULES_QBITTORRENT_HOST`. There are no per-setting CLI flags: `--config` picks the file, and `qbt-rules config` prints every setting's effective value and which of these it came from.
A value of the wrong type, such as `0.5` or `true` for an integer or a list for a string, is an error that names the setting, and the server doesn't start.
The engine is [interpose](https://github.com/metalayerlab/interpose)'s settings loader; `src/qbt_rules/config.py` declares the settings.

`config.yaml` is read once at startup: restart the server to pick up a change. `rules.yml` is re-read whenever it changes on disk.

**Where the files are.** The config file is in `/etc/qbt-rules`, which can be read-only; everything qbt-rules writes, `rules.yml` included, is in the state directory, `/var/lib/qbt-rules`:

| Path | What it is | Setting |
|------|------------|---------|
| `/etc/qbt-rules/config.yaml` | The settings. Optional: every setting has a default and an environment variable. The only file in `/etc/qbt-rules` | `QBT_RULES_CONFIG`, `--config` |
| `/var/lib/qbt-rules/rules.yml` | Your rules ([reference below](#rulesyml-reference)). In the state directory because the dashboard's rules editor saves it: keep it **writable** by the server | `rules.file` (relative to `state_dir`) |
| `/var/lib/qbt-rules/qbt-rules.db` | The SQLite job queue (WAL mode: `-wal` and `-shm` files sit beside it) | `queue.sqlite_path` (relative to `state_dir`) |
| `/var/lib/qbt-rules/.history/` | Previous versions of `rules.yml`, kept by the rules editor | `state_dir` |
| *(the console)* | The log: stderr, which `docker logs` and Kubernetes keep. Set `logging.file` to also write a file (rotated by size); a relative path is under `state_dir` | `logging.file` |

The image's volume is `/var/lib/qbt-rules`; mount your config directory at `/etc/qbt-rules`, read-only if you like (see [Deployment](Deployment)). The old `/config` directory is not read, with no fallback: a path setting under `/config` is refused at startup. So is a `rules.yml` left in `/etc/qbt-rules` (beside `config.yaml`, where 0.11's development builds read it) while the state directory has none: move it to `/var/lib/qbt-rules/rules.yml`.

**First start.** Nothing is copied into place. With no `config.yaml` every setting has its default; with no `rules.yml` there are no rules, and the dashboard's rules editor creates the file on its first save (the state directory must be writable, as it is in the image).

**Refused settings are reported together.** Everything 0.11 refuses (a removed or renamed variable or key, a path under `/config`, a `config.yml` or `rules.yml` in the old place, an alias set to a different value from its key) is collected and reported in one error, each with what to use instead, and the server exits with status 2. One run lists everything to change. [contrib/rules.example.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/rules.example.yml) and [contrib/qbt-rules.example.yaml](https://github.com/andronics/qbt-rules/blob/main/contrib/qbt-rules.example.yaml) are starting points.

**Starting without an API key.** The server starts with no configuration at all (the image's smoke test runs it that way). Without `server.api_key` it refuses every authenticated request with a `503` that says what to set, the dashboard's login page says so too, and `/api/health` (still `200`: the process is fine) lists it under `config_problems`. The placeholder key the 0.10.x default `config.yml` shipped with (`your-secure-api-key-here-...`) is public, so it counts as unset. qBittorrent credentials aren't checked at startup: qBittorrent can allow logins without a password, and a wrong one shows up as a failed job.

**Listen port and the healthcheck.** The image's `HEALTHCHECK` polls `/healthz` (liveness, which depends on nothing) on `QBT_RULES_LISTEN_PORT` (default `5000`); `/readyz` and `/api/health` are described in [Deployment](Deployment#probes). `listen.port` is the setting's name; `server.port` and `QBT_RULES_SERVER_PORT` (the 0.10.x names) still work as deprecated aliases, but the healthcheck doesn't read them, so use `QBT_RULES_LISTEN_PORT`. The server logs a deprecation warning at startup for each alias in use, in the file or as a variable, naming the key or variable to use instead (`qbt-rules config` and `qbt-rules validate` print it too), and refuses to start if an alias and its key are set to different values. `server.host` / `QBT_RULES_SERVER_HOST` are aliases of `listen.host` the same way.

**`${VAR}` in the file.** `${VAR}` and `${VAR:-default}` inside `config.yaml` are replaced with that environment variable (or the default, or nothing). A `QBT_RULES_*` variable for the setting still wins over the expanded value.

**The schedule.** `schedule:` is a list of `{cron, context}` entries, so it has no single variable. Set it in the file, or with indexed variables, `QBT_RULES_SCHEDULE_<N>_CRON` and `QBT_RULES_SCHEDULE_<N>_CONTEXT` (each with a `_FILE` form), from `N=0` up; the first missing index ends the list. If any are set they replace the file's list entirely. See [Scheduling](Scheduling).

## Settings

Generated from the code: don't edit the table, run `uv run scripts/gen-wiki.py`.

<!-- generated:start settings -->
| Key | Environment variable | Default | Description |
|---|---|---|---|
| `listen.host` | `QBT_RULES_LISTEN_HOST` | `0.0.0.0` | Address the HTTP server binds to. `server.host` (`QBT_RULES_SERVER_HOST`) is a deprecated alias. |
| `listen.port` | `QBT_RULES_LISTEN_PORT` | `5000` | Port the HTTP server listens on, and the one the image's healthcheck polls. `server.port` (`QBT_RULES_SERVER_PORT`) is a deprecated alias, which the healthcheck doesn't read. |
| `state_dir` | `QBT_RULES_STATE_DIR` | `/var/lib/qbt-rules` | Directory for state: `rules.yml`, the SQLite job database and the rules editor's history (`.history/`). Must be writable. |
| `dry_run` | `QBT_RULES_DRY_RUN` | `False` | Log what rules would do without doing it. Replaces 0.10.x's `engine.dry_run`. |
| `rules.file` | `QBT_RULES_RULES_FILE` | *(none)* | The rules file. Empty: `rules.yml` in `state_dir` (`/var/lib/qbt-rules/rules.yml`). A relative path is relative to `state_dir`. It must be writable for the dashboard's editor to save it. |
| `server.api_key` | `QBT_RULES_SERVER_API_KEY` | *(none)* | Key for the HTTP API and the dashboard login (`openssl rand -hex 32`). Unset, the server starts but refuses every authenticated request, and `/api/health` says so. 🔒 Secret: use the `_FILE` variant. |
| `server.workers` | `QBT_RULES_SERVER_WORKERS` | `1` | Must be 1: the server is one process, so its worker and scheduler run once. Kept so a 0.10.x config that sets it to 1 still loads. |
| `server.editor_enabled` | `QBT_RULES_SERVER_EDITOR_ENABLED` | `True` | Allow saving `rules.yml` from the dashboard's rules editor. `false` keeps it read-only. |
| `client.server_url` | `QBT_RULES_CLIENT_SERVER_URL` | `http://localhost:5000` | Server the CLI client submits jobs to. |
| `client.api_key` | `QBT_RULES_CLIENT_API_KEY` | *(none)* | API key the CLI client sends. Empty: `server.api_key`, right for `docker exec` into the server's own container. 🔒 Secret: use the `_FILE` variant. |
| `queue.backend` | `QBT_RULES_QUEUE_BACKEND` | `sqlite` | Job queue: `sqlite` or `redis`. |
| `queue.sqlite_path` | `QBT_RULES_QUEUE_SQLITE_PATH` | *(none)* | SQLite job database. Empty: `qbt-rules.db` in `state_dir`. A relative path is relative to `state_dir`. |
| `queue.redis_url` | `QBT_RULES_QUEUE_REDIS_URL` | `redis://localhost:6379/0` | Redis URL, for `queue.backend: redis`: `redis://[:password@]host[:port][/db]`. 🔒 Secret: use the `_FILE` variant. |
| `queue.cleanup_after` | `QBT_RULES_QUEUE_CLEANUP_AFTER` | `7d` | Delete finished jobs older than this: seconds or a duration (`7d`, `2w`, `30 days`). `0` keeps them. |
| `qbittorrent.host` | `QBT_RULES_QBITTORRENT_HOST` | `http://localhost:8080` | qBittorrent's Web UI address. |
| `qbittorrent.username` | `QBT_RULES_QBITTORRENT_USERNAME` | `admin` | qBittorrent Web UI user. |
| `qbittorrent.password` | `QBT_RULES_QBITTORRENT_PASSWORD` | *(none)* | qBittorrent Web UI password. 🔒 Secret: use the `_FILE` variant. |
| `notifications.webhook_url` | `QBT_RULES_NOTIFICATIONS_WEBHOOK_URL` | *(none)* | Default webhook for the `notify` action when a rule gives no `url`. 🔒 Secret: use the `_FILE` variant. |
| `notifications.service` | `QBT_RULES_NOTIFICATIONS_SERVICE` | `generic` | Default `notify` service: `generic`, `discord`, `slack` or `ntfy`. |
| `integrations.sonarr.url` | `QBT_RULES_INTEGRATIONS_SONARR_URL` | *(none)* | Sonarr's address, for the `arr_blocklist` action. |
| `integrations.sonarr.api_key` | `QBT_RULES_INTEGRATIONS_SONARR_API_KEY` | *(none)* | Sonarr's API key. 🔒 Secret: use the `_FILE` variant. |
| `integrations.radarr.url` | `QBT_RULES_INTEGRATIONS_RADARR_URL` | *(none)* | Radarr's address, for the `arr_blocklist` action. |
| `integrations.radarr.api_key` | `QBT_RULES_INTEGRATIONS_RADARR_API_KEY` | *(none)* | Radarr's API key. 🔒 Secret: use the `_FILE` variant. |
| `integrations.trackie.url` | `QBT_RULES_INTEGRATIONS_TRACKIE_URL` | *(none)* | trackie's address, for the `tracker.*` fields. Empty: not used. |
| `integrations.trackie.max_age` | `QBT_RULES_INTEGRATIONS_TRACKIE_MAX_AGE` | `3 hours` | Older tracker data counts as no data: seconds or a duration. |
| `integrations.trackie.timeout` | `QBT_RULES_INTEGRATIONS_TRACKIE_TIMEOUT` | `10` | Seconds for trackie's `/snapshot` request. |
| `metrics.enabled` | `QBT_RULES_METRICS_ENABLED` | `False` | Serve Prometheus metrics on `/metrics` (needs the API key). |
| `logging.level` | `QBT_RULES_LOGGING_LEVEL` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. DEBUG logs every rule evaluation. |
| `logging.file` | `QBT_RULES_LOGGING_FILE` | *(none)* | Also log to this file, rotated by size. Empty: the console only (`docker logs`). A relative path is relative to `state_dir`. |
| `logging.max_bytes` | `QBT_RULES_LOGGING_MAX_BYTES` | `10485760` | Rotate the log file at this size; `0` never rotates. |
| `logging.backup_count` | `QBT_RULES_LOGGING_BACKUP_COUNT` | `5` | Rotated log files to keep. |
| `logging.trace_mode` | `QBT_RULES_LOGGING_TRACE_MODE` | `False` | Add module, function and line to each log line. |
| `logging.http_access` | `QBT_RULES_LOGGING_HTTP_ACCESS` | `False` | Log every HTTP request, health checks included. |
<!-- generated:end settings -->

`schedule` isn't in the table: see [the schedule](#where-configuration-comes-from) above and [Scheduling](Scheduling).

A few settings need more than a line:

- **`server.editor_enabled`**: `false` keeps the rules editor read-only (it still validates). A `rules.yml` made read-only on disk (`chmod 444`) is never written either way.
- **`queue.cleanup_after`**: finished jobs older than this are removed once at startup and then hourly. With SQLite, a cleanup that deleted rows truncates the `-wal` file, and one that removed more than a quarter of the jobs (and more than 1,000) runs `VACUUM`, which shrinks the database file; writes wait while it runs (well under a second for 100 MB on a local SSD), and the log line `VACUUM after removing … took …` gives its duration. The `-wal` file is also capped at 64 MiB after each checkpoint.
- **`metrics.enabled`**: serves `/metrics`, which needs the API key. See [Metrics](Metrics) for the metrics and a Prometheus scrape config. 0.10.x's `metrics.multiproc_dir` (and `QBT_RULES_METRICS_MULTIPROC_DIR`, `PROMETHEUS_MULTIPROC_DIR`) is refused: remove it.
- **`logging.level`**: applies to the console and the log file. `DEBUG` logs every rule evaluation per torrent.
- **`logging.max_bytes`**: the file is renamed to `qbt-rules.log.1` (older ones shift to `.2`, `.3`, ...) and a new one started. The server is one process, so one handler writes and rotates it.
- **`logging.http_access`**: off, the access log leaves out the requests that only poll (`/healthz`, `/readyz`, `/api/health`, `/metrics`, `/static/...`); on, every request is logged. Either way every logged URL has its `key=` value replaced with `[REDACTED]`.
- **`server.workers`**: must be `1`. The server is one uvicorn process (no Gunicorn), so a 0.10.x config with a higher value is refused at startup; remove the setting.

### Migrating from 0.10.x

0.11 moves the configuration onto the template's layout: `config.yaml` in `/etc/qbt-rules` (read-only is fine), and everything qbt-rules writes, `rules.yml` included, in `/var/lib/qbt-rules`. Nothing reads `/config` any more, and nothing is moved for you. Copy (don't move: keep `/config` as it is until you're happy, so rolling back is just the old image) each file:

| 0.10.x | 0.11 | Notes |
|--------|------|-------|
| `/config/config.yml` | `/etc/qbt-rules/config.yaml` | Renamed: `.yaml`. Optional: drop it if you configure with variables. Edit it as below |
| `/config/rules.yml` | `/var/lib/qbt-rules/rules.yml` | The **state** directory, not `/etc/qbt-rules`: the rules editor saves it. Make it writable by the server's user (`PUID`, 1000 by default), e.g. mode `0644`; a read-only copy (`0444`) opens read-only in the editor |
| `/config/qbt-rules.db` (and `-wal`) | `/var/lib/qbt-rules/qbt-rules.db` | The job history; optional (a new, empty one is created). It is in WAL mode, so copy it consistently: `sqlite3 /config/qbt-rules.db ".backup /var/lib/qbt-rules/qbt-rules.db"`, or a plain copy with the old app stopped. A copy of the main file alone, made while it runs, can miss the jobs still in `qbt-rules.db-wal` |
| `/config/.history/` | `/var/lib/qbt-rules/.history/` | The rules editor's backups; optional (0.10.1 deployments that never saved from the editor have none) |
| `/config/qbt-rules.log` (and `.1`, `.2`, ...) | *(the console)* | Not copied: the log goes to the console now (`docker logs`, `kubectl logs`). Set `QBT_RULES_LOGGING_FILE=/var/lib/qbt-rules/qbt-rules.log` to keep a file as well |

In `config.yaml`, the edits a production 0.10.1 config needed (the server refuses to start until they are made, and lists them all at once):

```diff
-engine:
-  dry_run: false
+dry_run: false
 logging:
   level: info
-  file: /config/qbt-rules.log
   trace: false
   http_access: false
 ...
 queue:
   backend: sqlite
-  sqlite_path: /config/qbt-rules.db
   cleanup_after: 7d
-rules:
-  file: /config/rules.yml
```

- **`engine.dry_run` is now a top-level `dry_run`.** `engine.dry_run` is refused with that message. The variable, `QBT_RULES_DRY_RUN`, is unchanged.
- **Delete every path under `/config`**: `logging.file`, `queue.sqlite_path`, and the `rules:` block (`rules.file`). The defaults already point at the new places (`/var/lib/qbt-rules/rules.yml`, `/var/lib/qbt-rules/qbt-rules.db`, the console); a path under `/config` is refused at startup.
- **`server.host` and `server.port`** still work, as deprecated aliases of `listen.host` and `listen.port`: the server logs a warning naming the new key. Rename them when convenient.
- **`server.workers`** above `1` is refused (one process now): delete it.
- **`server.api_key` and `client.api_key`** still holding the shipped placeholder count as unset: set a real key.
- `version: 1` can stay or go; nothing reads it. Unknown keys are ignored, so check any you add against the [settings table](#settings) (`logging.trace`, for one, has never been a setting: it is `logging.trace_mode`).

Credentials, the qBittorrent host, notifications, the queue backend, `cleanup_after`, the schedule and the `client` keys carry over unchanged.

**Mount `/var/lib/qbt-rules` as a directory**, not single files: SQLite creates `qbt-rules.db-wal` and `-shm` beside the database, the rules editor replaces `rules.yml` atomically and writes `.history/` beside it, and with file-only mounts those land on the container's throwaway layer. A Kubernetes deployment that keeps its old volume can mount it twice with `subPath`s: `/etc/qbt-rules` holding `config.yaml` (read-only), and a directory at `/var/lib/qbt-rules` holding `rules.yml`, `qbt-rules.db` and `.history/`.

**The first start prunes old jobs.** `queue.cleanup_after` (default `7d`) is applied at startup and then hourly; 0.10.1 never applied it, so the first start of 0.11 deletes every finished job older than that (on one production database, about 80% of them). 0.11.0 left the database file at full size; from 0.11.1 that cleanup is followed by a `VACUUM`, which shrinks it. The old database on `/config` is untouched, for rollback. Set `queue.cleanup_after` higher, or `0` to keep everything, before the first start if you want the history.

Environment variables:

| 0.10.x | 0.11 |
|--------|------|
| Every `QBT_RULES_<SECTION>_<FIELD>` and its `_FILE` form | Unchanged |
| `QBT_RULES_DRY_RUN`, `QBT_RULES_RULES_FILE`, `QBT_RULES_SCHEDULE_<N>_CRON` / `_CONTEXT` | Unchanged (`QBT_RULES_RULES_FILE` now works: 0.10.x documented it but never read it; a relative path is under `QBT_RULES_STATE_DIR`) |
| `QBT_RULES_SERVER_PORT`, `QBT_RULES_SERVER_HOST` | Deprecated aliases of `QBT_RULES_LISTEN_PORT` and `QBT_RULES_LISTEN_HOST`, with a warning at startup. Set `QBT_RULES_LISTEN_PORT` instead: the healthcheck reads only that |
| `CONFIG_DIR` | Refused at startup: remove it (use `QBT_RULES_CONFIG` for another config file) |
| `QBT_RULES_CONFIG_DIR` | Refused at startup: remove it (use `QBT_RULES_CONFIG` and `QBT_RULES_STATE_DIR`) |
| `QBT_RULES_LOG_LEVEL` | Refused: it was never a setting; use `QBT_RULES_LOGGING_LEVEL` |
| `--config-dir DIR` | Refused: use `--config FILE` |
| *(new)* | `QBT_RULES_CONFIG` (the config file), `QBT_RULES_STATE_DIR` (state, `rules.yml` included) |

**Rules.** `qbt-rules validate` is stricter than 0.10.1's `--validate`. In particular, `delete_torrent` with `keep_files` is an error: 0.10.1 ignored `keep_files` and deleted the files, so write `delete_files: true` (what such a rule has been doing) or `delete_files: false` (keep them). The server still starts and runs the rule as 0.10.1 did, but the dashboard's editor won't save `rules.yml` until it validates.

## Secrets

A secret setting (🔒 in the table) is read from all four places, like any other, so nothing stops it being set in the config file or a plain environment variable. Don't: `docker inspect` and `ps` show the variable. Use the `_FILE` variant and mount the value as a file:

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

Secrets are never logged. The secrets qbt-rules uses, and what each one grants:

| Setting | Grants |
|---------|--------|
| `server.api_key` (and `client.api_key`) | Every API endpoint and the dashboard: queuing jobs runs any action in `rules.yml`, including deletes |
| `qbittorrent.password` | Full control of qBittorrent |
| `notifications.webhook_url` | Posting to your Discord/Slack/ntfy channel (the token is in the URL) |
| `integrations.sonarr.api_key`, `integrations.radarr.api_key` | Full control of that Sonarr/Radarr instance |
| `queue.redis_url` | The Redis queue, when the URL holds a password |

See [Security](Security#credential-management) for how to keep them out of `docker inspect`, and how to rotate the API key.

## Examples

A complete config file with every default is in [contrib/qbt-rules.example.yaml](https://github.com/andronics/qbt-rules/blob/main/contrib/qbt-rules.example.yaml).

A minimal Docker setup needs no config file: only what differs from the defaults, as environment variables.

```yaml
environment:
  QBT_RULES_SERVER_API_KEY_FILE: /run/secrets/api_key
  QBT_RULES_QBITTORRENT_HOST: http://qbittorrent:8080
  QBT_RULES_QBITTORRENT_USERNAME: admin
  QBT_RULES_QBITTORRENT_PASSWORD_FILE: /run/secrets/qbt_password
```

A config file for the integrations and a schedule, with the secrets still in files:

```yaml
# /etc/qbt-rules/config.yaml
qbittorrent:
  host: http://qbittorrent:8080
schedule:
  - cron: "*/30 * * * *"
    context: cron
notifications:
  service: discord        # webhook_url from QBT_RULES_NOTIFICATIONS_WEBHOOK_URL_FILE
integrations:
  sonarr:
    url: http://sonarr:8989   # api_key from QBT_RULES_INTEGRATIONS_SONARR_API_KEY_FILE
  trackie:
    url: http://trackie:8080
```

A busier setup with a Redis queue and an internal schedule, all in variables:

```yaml
environment:
  QBT_RULES_QUEUE_BACKEND: redis
  QBT_RULES_QUEUE_REDIS_URL_FILE: /run/secrets/redis_url
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
