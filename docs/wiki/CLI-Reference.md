# CLI Reference

There's one command, `qbt-rules`, and it takes a command first:

- **`qbt-rules serve`** runs the server: the HTTP API, the dashboard, the background worker and the scheduler. This is what the container runs (the image's `CMD`).
- **`qbt-rules execute`**, **`jobs`** and **`stats`** talk to a running server over HTTP: queue a job, or ask about jobs.
- **`qbt-rules validate`**, **`rules list`** and **`config`** work on the local configuration, with no server needed.

`qbt-rules --help` lists the commands, and `qbt-rules <command> --help` shows a command's options. In the container, run commands through `docker exec`: it goes through the same entrypoint as the server, so it runs as the same user and reads the same configuration.

```sh
docker exec qbt-rules qbt-rules execute --context manual --wait
```

## The qBittorrent hook

qBittorrent's "Run external program" (Tools → Options → Downloads) can queue a job for the torrent that was just added or finished. `%I` is the torrent's info hash:

```sh
qbt-rules execute --context torrent-imported --hash "%I"
```

With qBittorrent and qbt-rules in separate containers, run it in the qbt-rules container (`docker exec qbt-rules qbt-rules execute --context torrent-imported --hash "%I"`), or call the HTTP API with `curl` instead (see [Contexts](Contexts#wiring-up-qbittorrent-webhooks)). Use `--context download-finished` on the "torrent finished" hook. The client reads `client.server_url` and `client.api_key` (`QBT_RULES_CLIENT_SERVER_URL`, `QBT_RULES_CLIENT_API_KEY_FILE`); the key falls back to `server.api_key`, so inside the server's container nothing needs setting.

## Commands

Generated from the code: don't edit, run `uv run scripts/gen-wiki.py`.

<!-- generated:start cli -->
### `qbt-rules config`

Print the effective configuration and where each value came from. Secrets: set or unset.

| Option | Environment variable | Description |
|---|---|---|
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules execute`

Queue a job on the running server, for a context and one torrent or all of them.

The server is `client.server_url`, and the key `client.api_key` (else `server.api_key`).
qBittorrent's "Run external program" calls this with the torrent's hash:
`qbt-rules execute --context torrent-imported --hash "%I"`

| Option | Environment variable | Description |
|---|---|---|
| `--context` |  | Run the rules for this context (any name your rules use). Without it, only rules with no context run. |
| `--hash` |  | Only this torrent (its 40-character info hash, qBittorrent's %I). Without it, every torrent. |
| `--wait` |  | Wait for the job to finish (up to 5 minutes); exit 1 if it fails. |
| `--dry-run` |  | Log what the rules would do and change nothing. |
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules jobs cancel`

Cancel a job that hasn't started (pending). Exits 1 once it has.

| Argument | Description |
|---|---|
| `JOB_ID` | The job's ID. |

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules jobs list`

List recent jobs, newest first.

| Option | Environment variable | Description |
|---|---|---|
| `--status` |  | Only jobs in this state: pending, processing, completed, failed or cancelled. |
| `--context` |  | Only jobs with this context. |
| `--limit` |  | At most this many (the server caps it at 100). |
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules jobs status`

One job's state, timing and result.

| Argument | Description |
|---|---|
| `JOB_ID` | The job's ID. |

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules rules list`

List the rules in the order they run (file order), with their $refs resolved.

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules serve`

Run the server until SIGTERM: the HTTP API and dashboard, the worker and the scheduler.

| Option | Environment variable | Description |
|---|---|---|
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules stats`

The server's job counts, average run time, queue and worker.

| Option | Environment variable | Description |
|---|---|---|
| `--json` |  | Print JSON instead of a table, for scripts. |
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules validate`

Check the settings and the rules without running anything. Exits 1 on any error.

Each problem is printed as `FILE:LINE:COLUMN: SEVERITY: MESSAGE (PATH)`. The checks are
the dashboard's rules editor's: YAML syntax, structure, `$ref` resolution, then operators,
actions and their parameters. Warnings alone pass.

| Argument | Description |
|---|---|
| `RULES_FILE` | The rules file to check (default: rules.file, rules.yml in the state directory). |

| Option | Environment variable | Description |
|---|---|---|
| `--config`, `-c` | `QBT_RULES_CONFIG` | Config file (default /etc/qbt-rules/config.yaml; missing is fine). |

### `qbt-rules version`

Print the version.
<!-- generated:end cli -->

Every command takes `--config`/`-c` (or `QBT_RULES_CONFIG`). Every other setting comes from its environment variable or `config.yaml`: there are no per-setting flags. For example, `QBT_RULES_LISTEN_PORT=8080 qbt-rules serve`, or `QBT_RULES_CLIENT_SERVER_URL=http://nas:5000 qbt-rules stats`. See [In-Depth Configuration](In-Depth-Configuration#settings).

### Examples

```sh
# Run the weekly-cleanup rules now
qbt-rules execute --context weekly-cleanup

# One torrent, after it finished downloading, and wait for the result
qbt-rules execute --context download-finished --hash 8c9a6e4f3b2d1a0e9f8c7b6a5d4e3f2a1b0c9d8e --wait

# Preview: log what the rules would do, change nothing
qbt-rules execute --context manual --dry-run --wait

# Submit to another server
QBT_RULES_CLIENT_SERVER_URL=http://remote-server:5000 qbt-rules execute --context import-complete

# Pending jobs only, as JSON for scripting
qbt-rules jobs list --status pending --json

# A job's status, cancel one, server statistics
qbt-rules jobs status <job-id>
qbt-rules jobs cancel <job-id>
qbt-rules stats

# Check the settings and rules before restarting; check a candidate rules file
qbt-rules validate
qbt-rules validate ./rules.new.yml
qbt-rules rules list

# The effective configuration, and where each value came from
qbt-rules config
```

`config` never prints a secret's value: `******** (set)` means you set it (in the file, the variable or its `_FILE`), and `(unset)` means you didn't, even when a default applies (`queue.redis_url = (unset)  (default)` uses `redis://localhost:6379/0`).

`validate` prints each problem as `FILE:LINE:COLUMN: SEVERITY: MESSAGE (PATH)`, the same checks the dashboard's rules editor runs:

```text
Settings: /etc/qbt-rules/config.yaml
/var/lib/qbt-rules/rules.yml:14:15: error: Unknown action type 'explode' (rules[1].actions[0].type)
Rules: /var/lib/qbt-rules/rules.yml: 2 rule(s), 1 error(s), 0 warning(s), 0 note(s)
error: validation failed: 1 error(s)
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success: the command ran, the job was queued (or, with `--wait`, completed), or `validate` found no errors (warnings are fine) |
| 1 | Failure: `validate` found an error; with `--wait`, the job failed, was cancelled or didn't finish within 5 minutes; the server couldn't be reached, refused the API key, or refused the request (`jobs status` or `jobs cancel` of an unknown job, `jobs cancel` of a job that has started); no API key to send; `rules list` with a broken `rules.yml` |
| 2 | Bad usage or configuration: an unknown command or option, an invalid value (such as a `--hash` that isn't 40 hex characters), the 0.10.x flags-only form, or a configuration that can't be loaded (an invalid setting, a removed variable) |

## Migrating from 0.10.x

0.11 is a clean break: the flags-only form (`qbt-rules --context …`) is gone, with no alias. Run the old form and the error names the new command. **Update qBittorrent's "Run external program" line, and any cron job or script that calls `qbt-rules`.**

| 0.10.x | 0.11 |
|---|---|
| `qbt-rules --context torrent-imported --hash %I` (the qBittorrent hook) | `qbt-rules execute --context torrent-imported --hash "%I"` |
| `qbt-rules --context X [--hash H] [--wait] [--dry-run]` | `qbt-rules execute --context X [--hash H] [--wait] [--dry-run]` |
| `qbt-rules --serve`, `qbt-rules serve` | `qbt-rules serve` |
| `qbt-rules --list-jobs [--status-filter S] [--limit N]` | `qbt-rules jobs list [--status S] [--limit N]` (and `--context C`) |
| `qbt-rules --job-status ID` | `qbt-rules jobs status ID` |
| `qbt-rules --cancel-job ID` | `qbt-rules jobs cancel ID` |
| `qbt-rules --stats` | `qbt-rules stats` |
| `--output json` | `--json` |
| `qbt-rules --validate` | `qbt-rules validate [RULES_FILE]` |
| `qbt-rules --list-rules` | `qbt-rules rules list` |
| `qbt-rules --version` | `qbt-rules version` |
| (none) | `qbt-rules config` |
| `--server-host`, `--server-port` | `QBT_RULES_LISTEN_HOST`, `QBT_RULES_LISTEN_PORT` |
| `--server-api-key`, `--client-api-key` | `QBT_RULES_SERVER_API_KEY_FILE`, `QBT_RULES_CLIENT_API_KEY_FILE` (or without `_FILE`) |
| `--client-server-url` | `QBT_RULES_CLIENT_SERVER_URL` |
| `--queue-backend`, `--queue-sqlite-path`, `--queue-redis-url` | `QBT_RULES_QUEUE_BACKEND`, `QBT_RULES_QUEUE_SQLITE_PATH`, `QBT_RULES_QUEUE_REDIS_URL` |
| `--log-level`, `--trace` | `QBT_RULES_LOGGING_LEVEL`, `QBT_RULES_LOGGING_TRACE_MODE=true`, on the **server**: the rules run in its worker, so a client's logging never showed them |
| `--server-workers` | removed: the server is one process |

Other changes: the client sends the API key in the `X-API-Key` header (it was `?key=`); `jobs status`, `jobs cancel`, `jobs list` and `stats` exit 1 when the server refuses the request (they exited 0); an invalid `--hash` exits 2 (it was 1); `validate` treats an unset `qbittorrent.password` as a warning (qBittorrent can let a host in without logging in), and a missing `rules.yml` as a warning; `validate` and `config` exit 2 on a configuration that can't be loaded.
