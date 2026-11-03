Contexts determine **when** a rule is allowed to run. Every job submitted to the server carries a context string, and every rule optionally declares which context(s) it responds to.

### How Contexts Actually Work

**Since v0.4.1, contexts are fully free-form.** There is no fixed list of context names built into the engine — `context:` on a rule is just a string (or list of strings) compared against whatever context the job was submitted with. You choose the names; the engine doesn't attach any special meaning to any of them.

- A rule with **no `context:` field** executes regardless of the job's context.
- A rule **with `context: X`** only executes when the job's context is exactly `X` (or, if `context` is a list, when the job's context is one of the listed values).
- If a job is submitted with **no context at all**, only rules with no `context:` field can match — rules requiring a specific context are skipped.

**Rule-level field, not a condition:**

```yaml
- id: auto-categorize-hd-movies
  enabled: true
  context: torrent-imported   # sibling of conditions/actions, NOT nested inside conditions
  conditions:
    all:
      - field: info.name
        operator: matches
        value: '(?i).*(1080p|2160p|4k).*'
  actions:
    - type: set_category
      params:
        category: "Movies-HD"
```

A rule with `context: [hourly, manual]` runs for either context:

```yaml
- id: hourly-or-manual-cleanup
  context: [hourly, manual]
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

### Submitting a Job With a Context

Contexts are set by whatever *submits* the job, not by the rule file itself:

**HTTP API:**

```bash
curl -X POST "http://localhost:5000/api/execute?context=weekly-cleanup&key=YOUR_KEY"
```

**CLI client** (talking to a running server):

```bash
qbt-rules --context weekly-cleanup --client-server-url http://localhost:5000 --client-api-key YOUR_KEY --wait
```

**From inside the server's own container** (common in Docker deployments, no separate client install needed):

```bash
docker exec qbt-rules qbt-rules --context weekly-cleanup --wait
```

See [HTTP API Reference](HTTP-API-Reference) for every endpoint (job status, cancellation, health, stats), not just `/api/execute`.

### Common Context Naming Conventions

There's no required naming scheme, but these conventions cover most real setups and match the examples used throughout this wiki:

| Context name (example) | Typical trigger source | Torrent scope |
|-------------------------|------------------------|---------------|
| `torrent-imported` | qBittorrent's `OnTorrentAdded` autorun hook | Single torrent (`&hash=%I`) |
| `download-finished` | qBittorrent's `OnTorrentFinished` autorun hook | Single torrent (`&hash=%I`) |
| `weekly-cleanup` / `hourly` / `nightly` | Cron container or systemd timer | All torrents |
| `adhoc-run` | Manual CLI invocation for testing | All torrents |

You can invent any name that makes sense for your setup — `low-bandwidth`, `weekend`, `sonarr-import` are all equally valid; the engine treats them identically to the examples above.

### Wiring Up qBittorrent Webhooks

Configure qBittorrent to call the server on torrent events (Tools → Options → Downloads → "Run external program"):

```bash
# On torrent added
curl -X POST "http://qbt-rules:5000/api/execute?context=torrent-imported&hash=%I&key=YOUR_API_KEY"

# On torrent completed
curl -X POST "http://qbt-rules:5000/api/execute?context=download-finished&hash=%I&key=YOUR_API_KEY"
```

When `&hash=%I` is included, only that single torrent is evaluated against the rules — the job doesn't process your entire library.

**Important:** rules that inspect `files.*` — like the content-safety filters in [Security](Security#known-limitation-magnet-link-metadata-timing) — can silently miss magnet-link torrents if they're only allowed to run in the `torrent-imported` context, since the file list isn't known yet at that instant. See that page for why, and how to design around it.

### Scheduled/Recurring Contexts

Contexts don't run themselves — something has to submit the job on a schedule. A small cron container calling the HTTP API works well:

```bash
# crontab inside a lightweight sidecar container
*/30 * * * * curl -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=weekly-cleanup"
```

Or from the host via systemd timer, using the CLI client:

```ini
# /etc/systemd/system/qbt-rules-cleanup.service
[Unit]
Description=qbt-rules weekly cleanup
[Service]
Type=oneshot
ExecStart=/usr/local/bin/qbt-rules --context weekly-cleanup --client-server-url http://localhost:5000 --client-api-key YOUR_KEY
```

```ini
# /etc/systemd/system/qbt-rules-cleanup.timer
[Unit]
Description=Run qbt-rules cleanup weekly
[Timer]
OnCalendar=weekly
Persistent=true
[Install]
WantedBy=timers.target
```

### Testing Without a Context

Run with `--dry-run` and no `--context` to see what every context-agnostic rule would do, without needing to pick a specific context:

```bash
qbt-rules --dry-run --context adhoc-run --client-server-url http://localhost:5000 --client-api-key YOUR_KEY
```

### Checking Job Status

Every submitted job is tracked and queryable regardless of context:

```bash
# List recent jobs
qbt-rules --list-jobs --client-server-url http://localhost:5000 --client-api-key YOUR_KEY

# Check a specific job
qbt-rules --job-status <job-id> --client-server-url http://localhost:5000 --client-api-key YOUR_KEY
```
