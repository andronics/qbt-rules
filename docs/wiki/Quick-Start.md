# Quick Start

From nothing to a working qbt-rules in a few minutes. Everything else is in [In-Depth Configuration](In-Depth-Configuration) and [Deployment](Deployment).

## Prerequisites

- Docker and Docker Compose (or any OCI runtime)
- qBittorrent with Web UI enabled (see [below](#enable-the-qbittorrent-web-ui))
- For running from source: Python >= 3.13 and [uv](https://docs.astral.sh/uv/)

## Install

qbt-rules is distributed as a container image, `ghcr.io/andronics/qbt-rules` (`linux/amd64` and `linux/arm64`) — there is no PyPI package to install for end users.

```sh
docker pull ghcr.io/andronics/qbt-rules:latest
```

From source, for development or a bare-metal install:

```sh
uv tool install git+https://github.com/andronics/qbt-rules
```

Bare metal, the config directory is `./config` if it exists, otherwise `/var/lib/qbt-rules`; `--config-dir DIR` or `CONFIG_DIR` picks another.

### Docker Compose

```sh
# Create directory structure
mkdir -p qbt-rules/state
cd qbt-rules
```

**Create `compose.yml`:**

```yaml
services:
  qbt-rules:
    image: ghcr.io/andronics/qbt-rules:latest
    container_name: qbt-rules
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"
    volumes:
      - ./state:/var/lib/qbt-rules
    environment:
      # Server configuration
      QBT_RULES_SERVER_API_KEY: "your-secure-api-key-here"  # Change this!

      # qBittorrent connection
      QBT_RULES_QBITTORRENT_HOST: "http://qbittorrent:8080"
      QBT_RULES_QBITTORRENT_USERNAME: "admin"
      QBT_RULES_QBITTORRENT_PASSWORD: "adminpass"

      # Queue (SQLite default, stored in the state directory)
      QBT_RULES_QUEUE_BACKEND: "sqlite"

      # Start in dry-run: rules only log what they would do. Set to "false"
      # once you've reviewed rules.yml -- the default rules include deletes
      QBT_RULES_DRY_RUN: "true"

      # User/group the container runs as and that owns ./state
      # (default 1000:1000; Unraid uses 99:100)
      # PUID: 1000
      # PGID: 1000
```

The repository's [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) is the same thing with the full hardening (read-only root, no capabilities beyond what the entrypoint needs): see [Deployment](Deployment).

The CLI client (`docker exec qbt-rules qbt-rules ...`) uses the server's API key automatically, so one key is enough.

The volume is the image's state directory, `/var/lib/qbt-rules`. On first run, the packaged default configuration files are copied into it as `config.yml` and `rules.yml` if those don't already exist — you don't need to fetch example configs yourself before starting the container. The job queue (`qbt-rules.db`), the log (`qbt-rules.log`) and the rules editor's `.history/` live there too.

> **Upgrading from a release that used `/config`?** That volume is gone, with no fallback: mount the old directory at `/var/lib/qbt-rules` instead. See [Deployment](Deployment#upgrading).

## First run

### Start the Server

```bash
# Start container
docker compose up -d

# Check health
curl http://localhost:5000/api/health

# View logs
docker compose logs -f qbt-rules
```

### Enable the qBittorrent Web UI

- Open qBittorrent → Tools → Options → Web UI
- Check "Web User Interface (Remote control)"
- Set the username and password you used in `QBT_RULES_QBITTORRENT_USERNAME`/`_PASSWORD` above
- Note the port (default: 8080)

### Your First Rule

Edit `state/rules.yml` (mounted from your host at `./state/rules.yml`), or open the dashboard's rules editor at `http://localhost:5000/rules/edit`:

```yaml
rules:
  - id: auto-categorize-hd-movies
    meta:
      description: "Auto-categorize HD movies"
    enabled: true
    stop_on_match: true
    context: torrent-imported   # sibling of conditions/actions — runs when torrents are added
    conditions:
      all:
        - field: info.name
          operator: matches
          value: '(?i).*(1080p|2160p|4k).*'
        - field: info.category
          operator: "=="
          value: ""
    actions:
      - type: set_category
        params:
          category: "Movies-HD"
      - type: add_tag
        params:
          tags:
            - hd
            - auto-categorized
```

**What this rule does:**

1. **Matches:** Torrents with "1080p", "2160p", or "4k" in the name (case-insensitive)
2. **AND:** Currently have no category assigned
3. **Actions:** Sets category to "Movies-HD" and adds tags

**Important:** Create the "Movies-HD" category in qBittorrent first!

### Testing Your Setup

Run the CLI client from inside the server's container — no separate install needed:

```bash
# Dry-run mode (see what would happen without making changes)
docker exec qbt-rules qbt-rules --dry-run --context torrent-imported --wait
```

> **Before v0.10.0, `--dry-run` on a client command was ignored and the job ran for real.** On an older version, preview with `QBT_RULES_DRY_RUN: "true"` on the server instead, or upgrade.

**Expected output (job runs, then reports results):**

```text
2026-01-05 12:00:00 | INFO | Job abc123 queued (context=torrent-imported)
2026-01-05 12:00:00 | INFO | Successfully authenticated with qBittorrent
2026-01-05 12:00:00 | INFO | Loaded 1 rules (execute in file order)
2026-01-05 12:00:00 | INFO | Would set_category Movie.2160p.BluRay to Movies-HD (params={'category': 'Movies-HD'})
2026-01-05 12:00:00 | INFO | Would add_tag Movie.2160p.BluRay (params={'tags': ['hd', 'auto-categorized']})
2026-01-05 12:00:00 | INFO | Rule 'Auto-categorize HD movies' matched 1 torrent(s)
2026-01-05 12:00:00 | INFO | Job abc123 completed
```

**Run for real** (remove `--dry-run`):

```bash
docker exec qbt-rules qbt-rules --context torrent-imported --wait
```

**Using the HTTP API instead of the CLI client:**

```bash
# Queue a job
curl -X POST "http://localhost:5000/api/execute?context=torrent-imported&key=your-api-key"

# Check job status
curl "http://localhost:5000/api/jobs?key=your-api-key" | jq
```

Open `http://localhost:5000` for the [dashboard](Dashboard) and log in with the API key. When the results look right, set `QBT_RULES_DRY_RUN: "false"` and `docker compose up -d` again.

**Other useful commands:**

```bash
# Validate rules syntax
docker exec qbt-rules qbt-rules --validate

# List all enabled rules
docker exec qbt-rules qbt-rules --list-rules

# Debug with trace logging
docker exec qbt-rules qbt-rules --dry-run --context torrent-imported --trace --wait

# Override log level
docker exec qbt-rules qbt-rules --dry-run --context torrent-imported --log-level DEBUG --wait
```

Congratulations! You've created your first automation rule.

## Next steps

- [Contexts](Contexts): how jobs get triggered in the first place (webhooks, cron, manual runs)
- [Conditions](Conditions), [Available Fields](Available-Fields) and [Actions](Actions): everything a rule can check and do
- [In-Depth Configuration](In-Depth-Configuration): every setting
- [CLI Reference](CLI-Reference): every `qbt-rules` flag
- [Deployment](Deployment): Docker Compose, Redis, upgrading
- [Troubleshooting](Troubleshooting) if something doesn't work
