# Upgrading to 0.11

0.11.0 is a breaking release. A 0.10.x deployment that only changes its image tag **won't come back up as it was**: 0.11 no longer reads `/config`, and qBittorrent's "Run external program" line has changed. This page lists everything that changed since 0.10.x, then the steps. The details are on the pages it links.

**Copy, don't move.** Leave `/config` as it is until you're happy with 0.11: rolling back is then just the old image tag with the old mount (see [Rolling back](#rolling-back)).

## What changed

### Paths: `/etc/qbt-rules` and `/var/lib/qbt-rules`, no `/config`

| 0.10.x | 0.11 | Notes |
|--------|------|-------|
| `/config/config.yml` | `/etc/qbt-rules/config.yaml` | **Renamed** to `.yaml`. Optional (every setting has a variable). The directory can be read-only. A `config.yml` left there with no `config.yaml` is refused |
| `/config/rules.yml` | `/var/lib/qbt-rules/rules.yml` | In the **state** directory, not `/etc/qbt-rules`: the dashboard's rules editor saves it, so it must be writable by `PUID` (mode `0644`). A `rules.yml` left in `/etc/qbt-rules`, with none in the state directory, is refused |
| `/config/qbt-rules.db` (+ `-wal`) | `/var/lib/qbt-rules/qbt-rules.db` | The job queue and history. In WAL mode: copy it with `sqlite3 … ".backup …"`, or as a file with the old container stopped |
| `/config/.history/` | `/var/lib/qbt-rules/.history/` | The rules editor's backups, if you have any |
| `/config/qbt-rules.log` | *(the console)* | Not copied; see [Logs](#logs-go-to-the-console) |

There is no fallback to `/config` and nothing is copied into place on first start (0.10.x created a default `rules.yml`; 0.11 starts with no rules until you copy yours or the editor saves one). Mount `/var/lib/qbt-rules` as a **directory**, not file by file: SQLite's `-wal`/`-shm` files and the editor's `.history/` are written beside the files. The full table, with the reasons, is in [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x).

### Settings that were removed or renamed

The server refuses to start while any of these is left, and lists all of them in one error, each with its fix.

In `config.yaml`:

- `engine.dry_run` is now a top-level `dry_run` (the variable `QBT_RULES_DRY_RUN` is unchanged).
- Every path under `/config` is refused: delete `logging.file`, `queue.sqlite_path` and the `rules:` block (`rules.file`). The defaults already point at the new places.
- `server.workers` other than `1` is refused: delete it (see [One process](#one-process-gunicorn-is-gone)).
- `metrics.multiproc_dir` is refused: delete it.
- `server.host` and `server.port` still work as deprecated aliases of `listen.host` and `listen.port`, with a warning at startup. Rename them when convenient.

In the environment:

| 0.10.x | 0.11 |
|--------|------|
| `QBT_RULES_<SECTION>_<FIELD>` and `…_FILE` | Unchanged |
| `QBT_RULES_SERVER_PORT`, `QBT_RULES_SERVER_HOST` | Deprecated aliases (a warning at startup). Use `QBT_RULES_LISTEN_PORT` and `QBT_RULES_LISTEN_HOST`: the image's healthcheck reads only `QBT_RULES_LISTEN_PORT` |
| `CONFIG_DIR`, `QBT_RULES_CONFIG_DIR` | Refused: remove them (`QBT_RULES_CONFIG` names another config file, `QBT_RULES_STATE_DIR` another state directory) |
| `QBT_RULES_LOG_LEVEL` | Refused: it was never a setting. Use `QBT_RULES_LOGGING_LEVEL` |
| `QBT_RULES_METRICS_MULTIPROC_DIR`, `PROMETHEUS_MULTIPROC_DIR` | Refused: remove them; `QBT_RULES_METRICS_ENABLED` alone turns `/metrics` on |
| `QBT_RULES_SERVER_WORKERS` | Must be `1`: remove it |

The exact `config.yaml` diff a production 0.10.1 config needed is in [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x).

### The server: `qbt-rules serve`

The image runs `qbt-rules serve` (its `CMD`). `qbt-rules --serve` is gone, with no alias. If you override the container's command, change it to `serve`, or drop the override.

### One process: Gunicorn is gone

The server is one uvicorn process with the worker and the scheduler as threads beside it. Gunicorn and its worker processes are gone, so `server.workers` is gone too. Jobs run strictly one at a time (0.10.x could run two at once). `docker stop` now stops it cleanly within a second; 0.10.x ignored SIGTERM and was killed after 10 seconds. Keep one replica: a second one would run every scheduled job twice. The probes are `GET /healthz` (liveness) and `GET /readyz` (readiness), on port `5000` by default; see [Deployment](Deployment#probes).

### The CLI: commands, and a new qBittorrent hook line

The flags-only CLI is gone, with no alias: the command comes first (`serve`, `execute`, `jobs list|status|cancel`, `stats`, `validate`, `rules list`, `config`, `version`). The old form exits 2 and names the new command.

**Update qBittorrent's "Run external program"** (Tools → Options → Downloads):

```sh
# torrent added
qbt-rules execute --context torrent-imported --hash "%I"
# torrent finished
qbt-rules execute --context download-finished --hash "%I"
```

With qBittorrent and qbt-rules in separate containers, run it in the qbt-rules container:

```sh
docker exec qbt-rules qbt-rules execute --context torrent-imported --hash "%I"
```

Per-setting flags (`--server-port`, `--log-level`, …) are their `QBT_RULES_*` variables. Exit codes are `0` ok, `1` failure, `2` usage or configuration. The full old-to-new table is in [CLI Reference](CLI-Reference#migrating-from-010x); update any cron job or script that calls `qbt-rules` too.

### Timestamps are ISO 8601

Every timestamp in the JSON API is ISO 8601 in UTC (`2026-01-15T10:30:00.123456+00:00`), with either queue backend. With SQLite, 0.10.x sent RFC 822 dates (`Thu, 15 Jan 2026 10:30:00 GMT`): a script that parses them must accept ISO 8601. See [HTTP API Reference](HTTP-API-Reference).

### The dashboard logs you out once

The session cookie changed (`qbt_rules_session`), so a 0.10.x login isn't recognised: log in again with the API key. A `?key=` on a dashboard URL now logs in and redirects to the same URL without the key, and the login form needs its CSRF token (a script posting to `/login` must load the form first). Links are relative, so the dashboard works behind a path prefix.

### Logs go to the console

The log goes to the console only (`docker logs`, `kubectl logs`), not `/config/qbt-rules.log`. Set `logging.file` (`QBT_RULES_LOGGING_FILE`) to a path outside `/config`, such as `/var/lib/qbt-rules/qbt-rules.log`, to keep a rotated file as well. The old log stays in `/config`; delete it once you've upgraded.

### The first start prunes old jobs

`queue.cleanup_after` (default `7d`) is now applied at startup and then hourly; 0.10.x never applied it. So the **first start deletes every finished job older than that**: on one production database, about 80% of the history. From 0.11.1 the database is vacuumed after a cleanup that removes a large share of the jobs, so the file shrinks too (0.11.0 left it, and its `-wal` file, at full size). To keep the history, set `queue.cleanup_after` higher, or `0`, before the first start. The copy of the database left on `/config` is untouched.

### Also

- **Rules validation is stricter.** `delete_torrent` with `keep_files` is an error (from 0.10.2): 0.10.x ignored `keep_files` and deleted the files. Write `delete_files: true` (what the rule has been doing) or `delete_files: false`. The server still starts and runs such a rule as before, but `qbt-rules validate` exits 1 and the editor won't save `rules.yml` until it's fixed.
- **Metrics.** `/metrics` keeps its names and labels; the content type is `text/plain; version=0.0.4; charset=utf-8`, and the `metrics` extra (prometheus_client) is gone.
- **Python 3.13** or later, for a non-container install.

## Upgrade steps

1. **Back up** the old `/config` directory (or volume).
2. **Stop** the 0.10.x container, so the database can be copied consistently.
3. **Copy** into two new directories, leaving `/config` untouched:
   - `config.yml` → `<config dir>/config.yaml`, then edit it: `engine.dry_run` → `dry_run`; delete `logging.file`, `queue.sqlite_path` and the `rules:` block; delete `server.workers`.
   - `rules.yml` → `<state dir>/rules.yml`, mode `0644`, owned by `PUID:PGID`.
   - `qbt-rules.db` → `<state dir>/qbt-rules.db`, with `sqlite3 /config/qbt-rules.db ".backup <state dir>/qbt-rules.db"` (or `cp -p` with the old container stopped).
   - `.history/` → `<state dir>/.history/`, if it exists.
4. **Fix the environment**: remove `CONFIG_DIR`, `QBT_RULES_CONFIG_DIR`, `QBT_RULES_LOG_LEVEL` (use `QBT_RULES_LOGGING_LEVEL`) and the multiprocess variables; rename `QBT_RULES_SERVER_PORT` to `QBT_RULES_LISTEN_PORT`.
5. **Mount** `<config dir>` at `/etc/qbt-rules` (read-only is fine) and `<state dir>` at `/var/lib/qbt-rules` (a writable directory), instead of `/config`. Drop any command override other than `serve`.
6. **Start** the 0.11 image and check the log: no configuration errors, a deprecation warning for each alias still in use, and one "Cleaned up N old jobs" line.
7. **Check**: `docker exec qbt-rules qbt-rules validate`, `docker exec qbt-rules qbt-rules jobs list`, `GET /readyz` answers `{"status":"ready"}`, and log in to the dashboard again.
8. **Update qBittorrent's "Run external program"** line (see [above](#the-cli-commands-and-a-new-qbittorrent-hook-line)).

Per platform:

- **Docker Compose:** [Deployment](Deployment#from-010x-config), with `./config` and `./state` beside the compose file.
- **Unraid:** the qbt-rules template now has two paths instead of `/config`. Create two folders inside the old appdata folder, for example `/mnt/user/appdata/qbt-rules/etc` and `/mnt/user/appdata/qbt-rules/state`, copy the files into them as in step 3 (the old files stay where they are), and point the template's *Config* path at `etc` and its *State* path at `state`. The container gives the state folder to `PUID:PGID` (`99:100` on Unraid) when it starts.
- **Kubernetes:** keep the old volume and mount it twice with `subPath`s: a subdirectory holding `config.yaml` at `/etc/qbt-rules` (read-only), and a subdirectory holding `rules.yml` and the database at `/var/lib/qbt-rules` (a directory mount). An initContainer can do step 3, skipping each file that already exists. Switch the probes to HTTP `GET /readyz` and `/healthz` on port 5000.

## Rolling back

Put the 0.10.x image tag back, with its old `/config` mount and command, and remove the 0.11 mounts. Because step 3 copied rather than moved, `/config` still holds the 0.10.x files as they were (the database without the jobs 0.11 ran). Rolling back from a later 0.11.x to 0.11.0 needs nothing but the tag.

## From 0.11.1 to 0.11.2: the schedule on interpose, and configuration warnings

0.11.2 reads `schedule` with interpose's list sections instead of its own loader. Nothing else in the configuration changes, `${VAR}` expansion included. What you may notice:

- **A lone `QBT_RULES_SCHEDULE_<N>_CONTEXT` stops the server.** 0.11.1 ignored a `_CONTEXT` with no `_CRON` beside it; now the entry exists when either variable is set, and the missing one is an error naming both: `schedule[1].cron: QBT_RULES_SCHEDULE_1_CRON is not set, but QBT_RULES_SCHEDULE_1_CONTEXT is`. Set the `_CRON` or remove the `_CONTEXT`.
- **New warnings at startup.** A key in `config.yaml` that isn't a setting, a `QBT_RULES_*` variable that no setting reads, a misspelt field in a schedule entry, and a schedule variable past the end of the list (`_3_CRON` with no `_2_*`) were ignored silently; they still are, but each is now logged as a warning, with the setting it probably meant. `qbt-rules config` and `qbt-rules validate` print them too.
- **Schedule errors read differently.** They count entries from 0, as the variables do, and name the file or variable: `schedule[0].cron: a required field, not set (from /etc/qbt-rules/config.yaml)` where 0.11.1 said `schedule entry #1 has no 'cron'`. Anything that matched the old text needs updating.
- **New:** `QBT_RULES_SCHEDULE_FILE` names a YAML file holding the whole list (for a ConfigMap or secret mount). Setting `QBT_RULES_SCHEDULE` itself is an error saying to use it.
