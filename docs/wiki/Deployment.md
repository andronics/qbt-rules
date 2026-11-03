# Deployment

qbt-rules ships as one container image, `ghcr.io/andronics/qbt-rules` (`linux/amd64` and `linux/arm64`). Manifests live in [`contrib/`](https://github.com/andronics/qbt-rules/tree/main/contrib), versioned with the code; release-please moves their image tag to each new release. The Compose file keeps the same hardening as the image: a non-root user, read-only root, only the capabilities the entrypoint needs.

## Process model

The container runs `qbt-rules serve`: the Flask HTTP API under **Gunicorn**, plus the background worker thread that runs jobs and the internal [scheduler](Scheduling), in one container.

- **One server per qBittorrent instance.** Jobs queue up and are worked off in order; separate workloads are separate contexts on the same server, not separate containers (see [Advanced Topics](Advanced-Topics)).
- **`server.workers`** (default `1`) sets the number of Gunicorn worker processes. The scheduler still fires once per cron tick whatever it's set to (see [Scheduling](Scheduling#running-with-multiple-server-workers)), and [metrics](Metrics) need `metrics.multiproc_dir` above 1.
- **The queue is the state.** With the default SQLite backend the queue is a file in the state directory; with Redis it's in Redis. Either way, queued jobs survive a restart.

## Docker Compose

[contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) is the reference deployment. It mounts:

- `./state` at `/var/lib/qbt-rules`, the image's state directory and its only volume. For now it holds everything: `config.yml` and `rules.yml` (copied from the packaged defaults on first start if missing), the SQLite queue `qbt-rules.db`, the log `qbt-rules.log`, and the rules editor's `.history/`.
- `./config` at `/etc/qbt-rules`, read-only. The current server doesn't read anything from it yet: keep `config.yml` in `./state`.

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
docker exec qbt-rules qbt-rules --validate     # config.yml and rules.yml
```

- The port binds to `127.0.0.1` only: put a reverse proxy (Traefik) in front for TLS and remote access (see [Security](Security#network-exposure)).
- The container starts as root only to give `/var/lib/qbt-rules` to `PUID:PGID` (default `1000:1000`; Unraid uses `99:100`), then drops to that user. `docker exec qbt-rules qbt-rules ...` goes through the same wrapper, so the CLI runs as that user too.
- Secrets go in files mounted read-only, passed as `QBT_RULES_<SECTION>_<FIELD>_FILE` (see [In-Depth Configuration](In-Depth-Configuration#secrets)).
- The image's healthcheck polls `GET /api/health` on `QBT_RULES_LISTEN_PORT` (default `5000`). If you change `QBT_RULES_SERVER_PORT`, set `QBT_RULES_LISTEN_PORT` to match.

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
      # config.yml, rules.yml and the log (the queue is in Redis)
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

Read the [CHANGELOG](https://github.com/andronics/qbt-rules/blob/main/CHANGELOG.md) entries between your version and the new one; breaking changes are marked ⚠. Then change the image tag and `docker compose up -d`. `config.yml`, `rules.yml` and the queue database carry over as they are.

### From `/config` to `/var/lib/qbt-rules`

The image no longer uses `/config`, and doesn't fall back to it: a container still mounting only `/config` ignores it and starts with fresh default files (and an empty queue) in an anonymous volume. Move the volume:

1. Stop the container: `docker compose down`.
2. Change the volume from `./config:/config` to `./config:/var/lib/qbt-rules` (or move the directory's contents to `./state` and mount that, like [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml)).
3. If your `config.yml` or environment names paths under `/config` (`queue.sqlite_path`, `rules.file`, `logging.file`, `QBT_RULES_QUEUE_SQLITE_PATH`, ...), change them to `/var/lib/qbt-rules/...`, or delete them to use the defaults, which already point there. Drop `CONFIG_DIR=/config` if you set it.
4. Start it again, then check: `docker exec qbt-rules qbt-rules --validate` and `docker exec qbt-rules qbt-rules --list-jobs`.

The container `chown`s the state directory to `PUID:PGID` on start, so ownership sorts itself out.

### Rolling back

Put the previous image tag back and `docker compose up -d`. Keep a copy of the state directory before an upgrade, so you can restore it alongside the older image. Rolling back past the `/config` change means mounting the directory at `/config` again.
