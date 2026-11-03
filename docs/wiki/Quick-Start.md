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

Bare metal, the config file is `/etc/qbt-rules/config.yaml` (missing is fine), with `rules.yml` beside it; `--config FILE` or `QBT_RULES_CONFIG` picks another. State goes in `/var/lib/qbt-rules` (`QBT_RULES_STATE_DIR`).

### Docker Compose

```sh
# Create directory structure
mkdir -p qbt-rules/config qbt-rules/state
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
      - ./config:/etc/qbt-rules      # rules.yml (and config.yaml, if you want one)
      - ./state:/var/lib/qbt-rules   # the job queue and the rules editor's history
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
      # once you've reviewed rules.yml
      QBT_RULES_DRY_RUN: "true"

      # User/group the container runs as and that owns ./state (give it
      # ./config too, so the rules editor can save rules.yml)
      # (default 1000:1000; Unraid uses 99:100)
      # PUID: 1000
      # PGID: 1000
```

The repository's [contrib/docker/compose.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/docker/compose.yml) is the same thing with the full hardening (read-only root, no capabilities beyond what the entrypoint needs): see [Deployment](Deployment).

The CLI client (`docker exec qbt-rules qbt-rules ...`) uses the server's API key automatically, so one key is enough.

Config lives in `/etc/qbt-rules` (`config.yaml` is optional: the variables above are enough, and `rules.yml` sits beside it); state lives in `/var/lib/qbt-rules`, the image's volume (the job queue, `qbt-rules.db`, and the rules editor's `.history/`). The log goes to the console (`docker compose logs`). Nothing is copied in on first start: with no `rules.yml` there are no rules until you write one, in `./config/rules.yml` or in the dashboard's rules editor, which creates the file on its first save. [contrib/rules.example.yml](https://github.com/andronics/qbt-rules/blob/main/contrib/rules.example.yml) is a starting point.

> **Upgrading from a release that used `/config`?** That volume is no longer read, with no fallback. See [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x) for which file goes where.

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

Edit `config/rules.yml` (mounted at `/etc/qbt-rules/rules.yml`), or open the dashboard's rules editor at `http://localhost:5000/rules/edit`:

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
