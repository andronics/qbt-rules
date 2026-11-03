# qbt-rules

[![CI](https://github.com/andronics/qbt-rules/actions/workflows/base-ci.yml/badge.svg)](https://github.com/andronics/qbt-rules/actions/workflows/base-ci.yml)
[![Release](https://img.shields.io/github/v/release/andronics/qbt-rules?sort=semver)](https://github.com/andronics/qbt-rules/releases)
[![Image](https://img.shields.io/badge/image-ghcr.io-blue?logo=docker)](https://github.com/andronics/qbt-rules/pkgs/container/qbt-rules)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

A rules engine for qBittorrent automation, with a job queue, scheduler and web dashboard.

Write what should happen to your torrents in YAML, and qbt-rules keeps doing it: when a torrent is added, when it
finishes, on a schedule, or whenever you ask. It categorizes, tags, pauses, resumes, deletes, throttles, skips
files and notifies, so an unattended qBittorrent doesn't turn into uncategorized downloads, dead torrents and
unmet ratio requirements.

```yaml
rules:
  - id: skip-sample-files
    meta:
      description: "Don't download sample files"
    context: torrent-imported          # run when qBittorrent adds a torrent
    conditions:
      all:
        - field: files.name
          operator: matches
          value: '(?i)(^|/)sample'
    actions:
      - type: set_file_priority
        params:
          priority: skip
          pattern: '(?i)(^|/)sample'
```

![qbt-rules dashboard](docs/images/dashboard.png)

- **Declarative YAML rules**, no coding required, run top to bottom in file order
- **Reusable references**: define a variable, condition, or action sequence once under `refs:`, reuse it everywhere ([docs](https://github.com/andronics/qbt-rules/wiki/Reusable-References))
- **Free-form execution contexts**: webhooks, cron sweeps, the internal scheduler, manual runs; no fixed trigger list ([docs](https://github.com/andronics/qbt-rules/wiki/Contexts))
- **Rich conditions**: AND/OR/NOT groups, 17+ operators, and [fields](https://github.com/andronics/qbt-rules/wiki/Available-Fields) from 8 qBittorrent API categories, plus fleet-wide `stats.*` and optional tracker-side `tracker.*` stats from [trackie](https://github.com/andronics/trackie)
- **Idempotent actions**, safe to run repeatedly, and a dry-run mode to preview them
- **Dashboard**: jobs, results and rules at a glance, plus an in-browser `rules.yml` editor that validates as you type, on the same port as the API
- **Persistent job queue** (SQLite or Redis): jobs survive restarts
- **Multi-version qBittorrent support**: v4.1 through v5.1+ via `qbittorrent-api`'s auto-detection

## Quick Start

You need Docker and a qBittorrent with its Web UI enabled. Save this as `compose.yml`, set your qBittorrent
address and credentials, and replace `change-me` with a long random string (`openssl rand -hex 32`):

```yaml
services:
  qbt-rules:
    image: ghcr.io/andronics/qbt-rules:latest
    container_name: qbt-rules
    restart: unless-stopped
    ports: ["127.0.0.1:5000:5000"]
    volumes: ["./config:/etc/qbt-rules", "./state:/var/lib/qbt-rules"]
    environment:
      QBT_RULES_QBITTORRENT_HOST: http://qbittorrent:8080
      QBT_RULES_QBITTORRENT_USERNAME: admin
      QBT_RULES_QBITTORRENT_PASSWORD: adminpass
      QBT_RULES_SERVER_API_KEY: change-me      # API + dashboard login
      QBT_RULES_DRY_RUN: "true"                # log what rules would do; set false when happy
```

```sh
docker compose up -d
curl http://127.0.0.1:5000/api/health
docker exec qbt-rules qbt-rules --context torrent-imported --wait   # run the torrent-imported rules now
```

Rules live in `./config/rules.yml` (start from [contrib/rules.example.yml](contrib/rules.example.yml), or
write them in the dashboard's editor at `http://127.0.0.1:5000/rules/edit`, logging in with the API key); the job
queue lives in `./state`. Nothing is copied in on first start, and every setting has an environment variable, so
`config.yaml` is optional. Read your rules before turning dry-run off. The container runs as `PUID:PGID` (default
`1000:1000`; Unraid uses `99`/`100`).

> **Upgrading from a release that mounted `/config`?** Config is now in `/etc/qbt-rules` and state in
> `/var/lib/qbt-rules`, and `/config` is no longer read. The wiki's
> [Migrating from 0.10.x](https://github.com/andronics/qbt-rules/wiki/In-Depth-Configuration#migrating-from-010x)
> lists which file goes where.

The full walk-through, including your first rule and triggering rules from qBittorrent's "Run external program"
setting, is in the wiki's [Quick Start](https://github.com/andronics/qbt-rules/wiki/Quick-Start). A hardened Compose
file is in [contrib/docker/compose.yml](contrib/docker/compose.yml).

## Documentation

Everything is in the **[wiki](https://github.com/andronics/qbt-rules/wiki)**. Its source is [`docs/wiki/`](docs/wiki/), in this
repository, reviewed with the code.

- [Introduction](https://github.com/andronics/qbt-rules/wiki/Introduction): what it is and how it works
- [Rules Architecture](https://github.com/andronics/qbt-rules/wiki/Rules-Architecture), [Contexts](https://github.com/andronics/qbt-rules/wiki/Contexts), [Conditions](https://github.com/andronics/qbt-rules/wiki/Conditions), [Actions](https://github.com/andronics/qbt-rules/wiki/Actions) and [Available Fields](https://github.com/andronics/qbt-rules/wiki/Available-Fields): writing rules
- [Examples](https://github.com/andronics/qbt-rules/wiki/Examples) and [Advanced Rules Example](https://github.com/andronics/qbt-rules/wiki/Advanced-Rules-Example)
- [In-Depth Configuration](https://github.com/andronics/qbt-rules/wiki/In-Depth-Configuration): every setting
- [CLI Reference](https://github.com/andronics/qbt-rules/wiki/CLI-Reference) and [HTTP API Reference](https://github.com/andronics/qbt-rules/wiki/HTTP-API-Reference)
- [Deployment](https://github.com/andronics/qbt-rules/wiki/Deployment): Docker Compose, Redis, upgrading
- [Security](https://github.com/andronics/qbt-rules/wiki/Security): threat model, API auth, network exposure, credentials
- [Troubleshooting](https://github.com/andronics/qbt-rules/wiki/Troubleshooting) and [FAQ](https://github.com/andronics/qbt-rules/wiki/Frequently-Asked-Questions)
- [Contributing](https://github.com/andronics/qbt-rules/wiki/Contributing) and [Release Process](https://github.com/andronics/qbt-rules/wiki/Release-Process)

## For AI assistants

Built with AI assistants; every change gets human review. **[AGENTS.md](AGENTS.md) and
[.agents/stack.md](.agents/stack.md) are the only instruction files** (stack, commands, rules, definition of
done, docs map). Read them instead of this README.

| Assistant | Entry point |
|---|---|
| Claude Code | [CLAUDE.md](CLAUDE.md) (imports both) + [.claude/settings.json](.claude/settings.json) |
| Codex, Cursor, Copilot coding agent | AGENTS.md, natively ([Copilot](.github/copilot-instructions.md), [Cursor](.cursor/rules/project.mdc) pointers) |
| Gemini CLI | [GEMINI.md](GEMINI.md) (imports both) |
| Chat without repo access | [docs/ai/prompts.md](docs/ai/prompts.md), "Context for a chat assistant" |

Humans: kick-off prompts are in [docs/ai/prompts.md](docs/ai/prompts.md), and the review checklist in
[docs/ai/review-checklist.md](docs/ai/review-checklist.md).

## Development

```sh
uv sync                           # Python >= 3.13, dev tools included
uv run pytest                     # tests (80% coverage floor)
uv run ruff check && uv run mypy  # lint and type check
sh scripts/checks.sh              # everything CI's checks job runs
```

The workflow is: a branch, Conventional Commit PR titles, squash merge. Releases are automated by
release-please, which also writes the [CHANGELOG](CHANGELOG.md). See
[Contributing](https://github.com/andronics/qbt-rules/wiki/Contributing).

This project was generated from [template-base](https://github.com/andronics/template-base) and
[template-python](https://github.com/andronics/template-python) (and
[template-container](https://github.com/andronics/template-container) for the image). Template
fixes arrive as a weekly *Template update* PR per template.

## License

Released into the public domain under the [Unlicense](LICENSE).
