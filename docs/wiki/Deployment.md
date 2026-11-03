# Deployment

qbt-rules ships as one container image, `ghcr.io/andronics/qbt-rules` (`linux/amd64` and `linux/arm64`). Manifests live in [`contrib/`](https://github.com/andronics/qbt-rules/tree/main/contrib), versioned with the code; release-please moves their image tag to each new release. The Compose file keeps the same hardening as the image: a non-root user, read-only root, only the capabilities the entrypoint needs.

## Process model

The container runs `qbt-rules serve`: **one uvicorn process** serving the HTTP API, with the background worker thread that runs jobs and the internal [scheduler](Scheduling) beside it.

- **One server per qBittorrent instance.** Jobs queue up and are worked off in order; separate workloads are separate contexts on the same server, not separate containers (see [Advanced Topics](Advanced-Topics)).
- **One process, one replica.** There are no worker processes: `server.workers` must be `1` (any other value, or `--server-workers`, is refused at startup and says to drop it). The scheduler runs in that process, so it fires once per cron tick; a second replica would fire every entry twice. In Kubernetes keep `replicas: 1` with the `Recreate` strategy (template-python decision 0008).
- **Stopping.** `docker stop` (SIGTERM) stops the server cleanly: it stops taking requests, the worker finishes its current poll (a running job gets a few seconds), and the worker and scheduler threads are joined before the process exits.
- **The queue is the state.** With the default SQLite backend the queue is a file in the state directory; with Redis it's in Redis. Either way, queued jobs survive a restart.

## Docker Compose

[contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) is the reference deployment. It mounts:

- `./config` at `/etc/qbt-rules`, read-only: `config.yaml` (optional: every setting also has a variable) and `rules.yml`. Read-only, the dashboard's rules editor still opens and validates but can't save; edit `rules.yml` on the host. To save from the dashboard (which also creates `rules.yml` on its first save if it's missing), drop the `:ro` and give `./config` to `PUID:PGID`.
- `./state` at `/var/lib/qbt-rules`, the image's state directory and its only volume: the SQLite queue `qbt-rules.db` and the rules editor's `.history/`.

The log goes to the console (`docker compose logs`); set `QBT_RULES_LOGGING_FILE` to also write a file. Nothing is copied into place on first start: see [In-Depth Configuration](In-Depth-Configuration#where-configuration-comes-from) for every path.

The file carries no qBittorrent settings: add them, and the API key, to its `environment:` before the first start:

```yaml
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: "Europe/London"
      QBT_RULES_SERVER_API_KEY_FILE: /run/secrets/qbt-rules/api_key
      QBT_RULES_QBITTORRENT_HOST: http://qbittorrent:8080
      QBT_RULES_QBITTORRENT_USERNAME: admin
      QBT_RULES_QBITTORRENT_PASSWORD_FILE: /run/secrets/qbt-rules/qbt_password
      QBT_RULES_DRY_RUN: "true"     # log what rules would do; set "false" when happy
```

and uncomment the `./secrets:/run/secrets/qbt-rules:ro` volume. Then:

```sh
mkdir -p config state secrets
openssl rand -hex 32 > secrets/api_key
printf '%s' 'your-qbittorrent-password' > secrets/qbt_password
docker compose -f contrib/docker/compose.yml up -d
docker compose -f contrib/docker/compose.yml logs -f
docker exec qbt-rules qbt-rules --validate     # config.yaml and rules.yml
```

- The port binds to `127.0.0.1` only: put a reverse proxy (Traefik) in front for TLS and remote access (see [Security](Security#network-exposure)).
- The container starts as root only to give `/var/lib/qbt-rules` to `PUID:PGID` (default `1000:1000`; Unraid uses `99:100`), then drops to that user. `docker exec qbt-rules qbt-rules ...` goes through the same wrapper, so the CLI runs as that user too.
- Secrets go in files mounted read-only, passed as `QBT_RULES_<SECTION>_<FIELD>_FILE` (see [In-Depth Configuration](In-Depth-Configuration#secrets)).
- The image's healthcheck polls `GET /healthz` on `QBT_RULES_LISTEN_PORT` (default `5000`): move the port with that variable. `QBT_RULES_SERVER_PORT` still works as an alias, but the healthcheck doesn't read it.

### Probes

| Path | Use it for | Answers |
|------|-----------|---------|
| `GET /healthz` | Liveness (the image's `HEALTHCHECK`, a Kubernetes `livenessProbe`) | `200 {"status":"ok"}` while the process serves HTTP. Depends on nothing, so a slow queue never gets the container restarted |
| `GET /readyz` | Readiness (a `readinessProbe`) | `200 {"status":"ready"}`, or `503` while starting or when the worker or scheduler thread has died (the message names it) |
| `GET /api/health` | Detail, for a human or a dashboard | `200` with the queue and worker status and any `config_problems` (no API key), or `503` when the queue is unreachable, the worker thread is dead or more than 5 jobs are processing at once |

None of them needs the API key.

### Redis queue

For high-volume webhook environments, the queue can live in Redis instead of SQLite (the image includes the Redis client). Add a Redis service next to qbt-rules:

```yaml
services:
  qbt-rules:
    image: ghcr.io/andronics/qbt-rules:latest
    container_name: qbt-rules
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"
    volumes:
      # config.yaml and rules.yml (the queue is in Redis)
      - ./config:/etc/qbt-rules
      # the rules editor's history
      - ./state:/var/lib/qbt-rules
      # Optional: Docker secrets
      # - ./secrets:/run/secrets/qbt-rules:ro
    environment:
      QBT_RULES_SERVER_API_KEY: "your-secure-api-key-here"  # Change this!
      # QBT_RULES_SERVER_API_KEY_FILE: /run/secrets/qbt-rules/api_key

      # Queue configuration (Redis)
      QBT_RULES_QUEUE_BACKEND: "redis"
      QBT_RULES_QUEUE_REDIS_URL: "redis://redis:6379/0"
      # With a password: "redis://:password@redis:6379/0", or put the whole
      # URL in a file: QBT_RULES_QUEUE_REDIS_URL_FILE
      QBT_RULES_QUEUE_CLEANUP_AFTER: "7d"

      # qBittorrent connection
      QBT_RULES_QBITTORRENT_HOST: "http://qbittorrent:8080"
      QBT_RULES_QBITTORRENT_USERNAME: "admin"
      QBT_RULES_QBITTORRENT_PASSWORD: "adminpass"
      # QBT_RULES_QBITTORRENT_PASSWORD_FILE: /run/secrets/qbt-rules/qbt_password

      QBT_RULES_LOGGING_LEVEL: "INFO"
    depends_on:
      redis:
        condition: service_healthy

  redis:
    image: redis:7-alpine
    container_name: qbt-rules-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --appendfsync everysec
    # With a password (recommended):
    # command: redis-server --appendonly yes --requirepass your-redis-password
    volumes:
      - redis-data:/data   # optional: the queue is short-lived by design
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 5s
    # Don't publish Redis's port: only qbt-rules needs it

volumes:
  redis-data:
```

### Full stack with qBittorrent

A complete demonstration setup, qBittorrent + qbt-rules + Redis, on one Compose network:

```yaml
services:
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    restart: unless-stopped
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/London
      - WEBUI_PORT=8080
    volumes:
      - ./qbittorrent/config:/config
      - ./qbittorrent/downloads:/downloads
    ports:
      - "8080:8080"      # Web UI
      - "6881:6881"      # Torrent port
      - "6881:6881/udp"

  qbt-rules:
    image: ghcr.io/andronics/qbt-rules:latest
    container_name: qbt-rules
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"
    volumes:
      - ./qbt-rules/state:/var/lib/qbt-rules
    environment:
      QBT_RULES_SERVER_API_KEY: "your-secure-api-key-here"
      QBT_RULES_QUEUE_BACKEND: "redis"
      QBT_RULES_QUEUE_REDIS_URL: "redis://redis:6379/0"
      QBT_RULES_QUEUE_CLEANUP_AFTER: "7d"
      QBT_RULES_QBITTORRENT_HOST: "http://qbittorrent:8080"
      QBT_RULES_QBITTORRENT_USERNAME: "admin"
      QBT_RULES_QBITTORRENT_PASSWORD: "adminpass"
      # Run the "scheduled" rules every 5 minutes, no sidecar needed
      QBT_RULES_SCHEDULE_0_CRON: "*/5 * * * *"
      QBT_RULES_SCHEDULE_0_CONTEXT: "scheduled"
    depends_on:
      qbittorrent:
        condition: service_started
      redis:
        condition: service_healthy

  redis:
    image: redis:7-alpine
    container_name: qbt-rules-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --appendfsync everysec
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  redis-data:
```

Older examples ran a second "cron" container looping `qbt-rules --context scheduled; sleep 300`: the internal scheduler above replaces it (see [Scheduling](Scheduling)).

### Image tags

| Tag | Meaning | Stability |
|-----|---------|-----------|
| `X.Y.Z` | Exact version | Immutable — pin production deployments to this |
| `X.Y` | Latest patch within this minor version | Moves forward on every `X.Y.z` patch release |
| `X` | Latest minor/patch within this major version (from 1.0) | Moves forward on every `X.y.z` release |
| `latest` | Most recent release | Moves on every release |
| `edge` | Most recent build of `main` | Moves on every push to `main`, may be unstable |

For anything long-running, pin to the exact version tag rather than `latest` or `edge`: those are floating tags that change out from under a deployment on the next release. How releases happen is on [Release Process](Release-Process).

## Upgrading

Read the [CHANGELOG](https://github.com/andronics/qbt-rules/blob/main/CHANGELOG.md) entries between your version and the new one; breaking changes are marked ⚠. Then change the image tag and `docker compose up -d`. `config.yaml`, `rules.yml` and the queue database carry over as they are.

### From 0.10.x (`/config`)

0.11 no longer reads `/config`, and doesn't fall back to it: config is in `/etc/qbt-rules`, state in `/var/lib/qbt-rules`. [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x) lists which file goes where and which settings and variables changed. With Compose:

1. Stop the container: `docker compose down`.
2. Copy, don't move, so the old directory still works with the old image: `mkdir -p config state`, then `cp -p old/config.yml config/config.yaml` (optional), `cp -p old/rules.yml config/`, `cp -p old/qbt-rules.db state/` and `cp -pr old/.history state/` (both optional).
3. In `config/config.yaml`, delete every path under `/config` (`queue.sqlite_path`, `rules.file`, `logging.file`) and rename `engine.dry_run` to a top-level `dry_run`. Drop `CONFIG_DIR` and `QBT_RULES_CONFIG_DIR` from the environment, and rename `QBT_RULES_SERVER_PORT` to `QBT_RULES_LISTEN_PORT`. The server refuses to start, naming the fix, if any of these is left.
4. Mount `./config:/etc/qbt-rules` and `./state:/var/lib/qbt-rules` (as [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) does), start it, then check: `docker exec qbt-rules qbt-rules --validate` and `docker exec qbt-rules qbt-rules --list-jobs`.

The container `chown`s the state directory to `PUID:PGID` on start; the config directory is yours, so give it to `PUID:PGID` if the rules editor should save `rules.yml`.

### Rolling back

Put the previous image tag back and `docker compose up -d`. Keep a copy of the state directory before an upgrade, so you can restore it alongside the older image. Rolling back past 0.11 means the old image with the old `/config` mount, which step 2 above left untouched.
