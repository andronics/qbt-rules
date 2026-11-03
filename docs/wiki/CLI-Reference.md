# CLI Reference

There's one command, `qbt-rules`, with two roles chosen by how it's invoked:

- **Server mode** (`qbt-rules serve`, or `qbt-rules --serve`): the HTTP API, the background worker and the scheduler. This is what the container runs.
- **Client mode** (everything else): submits a job to a running server over HTTP, or asks it about jobs, or works on the local config (`--validate`, `--list-rules`).

`qbt-rules --help` lists every flag, with examples. In the container, run the client through `docker exec`: it goes through the same entrypoint as the server, so it runs as the same user and finds the same config directory.

```sh
docker exec qbt-rules qbt-rules --context manual --wait
```

## Commands

### Server

| Flag | Default | What it does |
|------|---------|--------------|
| `serve` / `--serve` | | Run in server mode (HTTP API + worker + scheduler). `serve` is the name the image's `CMD` uses; `--serve` is the same thing |
| `--server-host HOST` | `0.0.0.0` | Bind address (`listen.host`) |
| `--server-port PORT` | `5000` | Port (`listen.port`). In the container, set `QBT_RULES_LISTEN_PORT` instead, which the healthcheck reads too: see [In-Depth Configuration](In-Depth-Configuration#where-configuration-comes-from) |
| `--server-api-key KEY` | | API key clients must present (`server.api_key`). Prefer `QBT_RULES_SERVER_API_KEY_FILE` |
| `--server-workers NUM` | `1` | Must be `1` (`server.workers`): the server is one process. Any other value is refused |
| `--queue-backend BACKEND` | `sqlite` | `sqlite` or `redis` (`queue.backend`) |
| `--queue-sqlite-path PATH` | `qbt-rules.db` in `state_dir` (`/var/lib/qbt-rules`) | SQLite database (`queue.sqlite_path`) |
| `--queue-redis-url URL` | `redis://localhost:6379/0` | Redis connection URL (`queue.redis_url`) |

### Submitting jobs

| Flag | Default | What it does |
|------|---------|--------------|
| `--context CONTEXT` | none | The job's context: any string you choose, matched against rules' `context:` (see [Contexts](Contexts)). Without it, only rules with no `context:` run |
| `--hash HASH` | all torrents | Evaluate one torrent only (its 40-character hex hash) |
| `--wait` | | Poll the server until the job finishes, then print its summary. Gives up after 5 minutes |
| `--dry-run` | | Run this job in dry-run mode: actions are logged as "Would …", nothing changes. The client refuses a server that doesn't confirm it (v0.10.0+) |
| `--client-server-url URL` | `http://localhost:5000` | Server to submit to (`client.server_url`) |
| `--client-api-key KEY` | the server's key | API key to submit with (`client.api_key`). Falls back to `server.api_key` when unset, so one key is enough inside the container |

### Job management

| Flag | What it does |
|------|--------------|
| `--list-jobs` | List recent jobs |
| `--status-filter STATUS` | With `--list-jobs`: only `pending`, `processing`, `completed`, `failed` or `cancelled` jobs |
| `--limit NUM` | With `--list-jobs`: at most this many (default `20`) |
| `--job-status JOB_ID` | One job's status, timing and result |
| `--cancel-job JOB_ID` | Cancel a job that's still `pending` |
| `--stats` | Server statistics: job counts, average execution time, queue and worker state |
| `--output FORMAT` | `table` (default) or `json`, for `--list-jobs`, `--job-status`, `--stats`, `--cancel-job` and `--list-rules` |

### Utilities

| Flag | What it does |
|------|--------------|
| `--validate` | Check the settings (refusing what changed in 0.11, and warning when there's no API key) and `rules.yml` (structure, operators, action parameters, `$ref`s) without running anything |
| `--list-rules` | List the rules in execution order: enabled, `stop_on_match`, context, id and description |
| `--version` | Print the version |

### Common options

| Flag | Default | What it does |
|------|---------|--------------|
| `--config FILE` | `QBT_RULES_CONFIG`, then `/etc/qbt-rules/config.yaml` | The config file (missing is fine); `rules.yml` is read beside it (see [In-Depth Configuration](In-Depth-Configuration#where-configuration-comes-from)). `--config-dir`, from 0.10.x, is refused |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (`logging.level`) |
| `--trace` | | Trace mode: module, function and line in every log line, and every field access |

Every server, queue and client flag has an environment variable and a config key: the flag wins over `QBT_RULES_<SECTION>_<FIELD>_FILE`, which wins over `QBT_RULES_<SECTION>_<FIELD>`, then `config.yaml`, then the default. See [In-Depth Configuration](In-Depth-Configuration#settings).

### Examples

```sh
# Server with a custom port and API key
qbt-rules serve --server-port 8080 --server-api-key my-secret-key

# Server with the Redis queue backend
qbt-rules serve --queue-backend redis --queue-redis-url redis://localhost:6379/0

# Run the weekly-cleanup rules now
qbt-rules --context weekly-cleanup

# One torrent, after it finished downloading, and wait for the result
qbt-rules --context download-finished --hash abc123def456... --wait

# Submit to another server
qbt-rules --context import-complete --client-server-url http://remote-server:5000

# Pending jobs only, as JSON for scripting
qbt-rules --list-jobs --status-filter pending --output json

# A job's status, cancel one, server statistics
qbt-rules --job-status <job-id>
qbt-rules --cancel-job <job-id>
qbt-rules --stats

# Check the config and rules before restarting
qbt-rules --validate
qbt-rules --list-rules
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success: the job was queued (or, with `--wait`, completed), or the command ran |
| 1 | Failure: the job failed or was cancelled, `--wait` timed out, the server couldn't be reached or rejected the API key, an invalid `--hash`, `--validate` found errors, or a configuration or qBittorrent error |
| 2 | Bad usage: an unknown flag or an invalid flag value |
