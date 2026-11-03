# Frequently Asked Questions

**[General](#general-questions)**

- [What is qbt-rules?](#q-what-is-qbt-rules)
- [Why not RSS automation?](#q-why-not-use-qbittorrents-built-in-rss-automation)
- [Works with qBittorrent v4.x?](#q-does-this-work-with-qbittorrent-v4x)
- [Safe on existing torrents?](#q-is-this-safe-to-run-on-my-existing-torrents)
- [Runs on Windows?](#q-can-i-run-this-on-windows)

**[Configuration](#configuration-questions)**

- [Where do config files go?](#q-where-should-i-put-my-config-files)
- [Env vars in config?](#q-how-do-i-use-environment-variables-in-config-files)
- [Multiple rule files?](#q-can-i-have-multiple-rule-files)
- [qBittorrent unreachable?](#q-what-happens-if-qbittorrent-is-unreachable)
- [Enable trace logging?](#q-how-do-i-enable-trace-logging)

**[Fields & Conditions](#field--condition-questions)**

- [How do I find available fields?](#q-how-do-i-know-what-fields-are-available)
- [`info.size` vs `info.total_size`?](#q-whats-the-difference-between-infosize-and-infototal_size)
- [Why isn't my `files.*` condition matching?](#q-why-is-my-files-condition-not-working)
- [Check for no tags?](#q-how-do-i-check-if-a-torrent-has-no-tags)
- [Regex in conditions?](#q-can-i-use-regex-in-conditions)
- [`older_than`/`newer_than`?](#q-how-do-older_than-and-newer_than-work)
- [What does `info.state` return?](#q-what-does-infostate-return)

**[Contexts](#context-questions)**

- [How often do context jobs run?](#q-how-often-do-scheduled-context-jobs-run)
- [Test without waiting?](#q-can-i-test-scheduled-rules-without-waiting)
- [How do webhooks work?](#q-how-do-webhooks-work)
- [Filter which torrents a rule sees?](#q-can-i-filter-which-torrents-a-rule-processes)
- [`manual` vs `scheduled`?](#q-whats-the-difference-between-manual-and-scheduled-contexts)

**[Actions](#action-questions)**

- [Idempotent `stop`?](#q-will-stop-action-pause-a-torrent-thats-already-paused)
- [`start` vs `force_start`?](#q-whats-the-difference-between-start-and-force_start)
- [Does delete remove files?](#q-does-delete_torrent-remove-files-from-disk)
- [Set multiple tags?](#q-can-i-set-multiple-tags-at-once)
- [Remove all tags?](#q-how-do-i-remove-all-tags)
- [What does `limit: -1` mean?](#q-what-does-limit--1-mean-for-uploaddownload-limits)
- [Multiple actions per torrent?](#q-can-i-run-multiple-actions-for-the-same-torrent)
- [Change queue position?](#q-can-i-change-a-torrents-queue-position)

**[Performance](#performance-questions)**

- [How many API calls?](#q-how-many-api-calls-does-the-system-make)
- [Reduce API calls?](#q-how-can-i-reduce-api-calls)
- [10,000+ torrents?](#q-can-i-run-this-on-a-system-with-10000-torrents)
- [How long does execution take?](#q-how-long-does-execution-take)

**[Errors & Troubleshooting](#error--troubleshooting-questions)**

- [401 Unauthorized?](#q-im-getting-401-unauthorized-errors)
- [Rules not matching?](#q-rules-arent-matching-torrents-i-expect)
- [Unexpected `False` results?](#q-getting-unexpected-false-results-when-accessing-fields)
- [Scheduled job not running?](#q-my-scheduled-context-job-isnt-running)
- [Webhooks not triggering?](#q-webhooks-arent-triggering)
- [Changes not applying?](#q-changes-arent-applying-to-torrents)

**[Docker & Deployment](#docker--deployment-questions)**

- [Runs in Docker?](#q-can-i-run-this-in-docker)
- [Deploy scheduled jobs with systemd?](#q-how-do-i-deploy-scheduled-jobs-with-systemd)
- [Run multiple instances?](#q-can-i-run-multiple-instances)
- [Integrate with Sonarr/Radarr?](#q-how-do-i-integrate-with-sonarrradarr)

## General Questions

### Q: What is qbt-rules?

A: qbt-rules is a client-server automation engine for qBittorrent. A small HTTP server (backed by a persistent job queue and a background worker) evaluates YAML-based rules and automatically categorizes, tags, pauses, resumes, deletes, and manages torrents based on conditions you specify.

### Q: Why not use qBittorrent's built-in RSS automation?

A: qBittorrent's RSS automation only works for adding new torrents based on RSS feeds. This system provides:

- Management of **existing** torrents based on conditions
- Free-form execution contexts (manual, cron sweeps, webhooks — you name them)
- Complex condition logic (AND/OR/NOT groups)
- Reusable references (`refs:`/`$ref`/`${vars.x}`) so you don't repeat the same condition or action block across rules
- Access to all torrent fields and metadata
- Idempotent actions that won't repeat unnecessarily
- Dry-run mode for safe testing

### Q: Does this work with qBittorrent v4.x?

A: Yes — qbt-rules uses the `qbittorrent-api` library, which auto-detects the server's API version and supports qBittorrent v4.1 through v5.1+ without any configuration changes on your part.

### Q: Is this safe to run on my existing torrents?

A: Yes! The system has several safety features:

- **Dry-run mode** (`--dry-run`) shows what would happen without making changes
- **Idempotent actions** skip if torrent already in desired state
- **File-order execution** allows predictable rule evaluation
- **Comprehensive logging** with trace mode for debugging
- **stop_on_match** prevents multiple rules from affecting the same torrent

### Q: Can I run this on Windows?

A: Yes, via Docker — qbt-rules is distributed only as a Docker image (`ghcr.io/andronics/qbt-rules`), so anywhere Docker Desktop runs (Windows, Linux, macOS) works the same way. There's no native Windows install or PyPI package for end users; see [Quick Start](Quick-Start) for the Docker Compose setup.

## Configuration Questions

### Q: Where should I put my config files?

A: In a Docker deployment, mount one host directory at `/etc/qbt-rules` and another at `/var/lib/qbt-rules` (see [Quick Start](Quick-Start)):

- `/etc/qbt-rules/config.yaml` - Connection, server, queue, and global settings (optional: every setting also has an environment variable)
- `/var/lib/qbt-rules/rules.yml` - Your automation rules, in the state directory (writable, so the dashboard's rules editor can save them)
- `/var/lib/qbt-rules/` - State: the job queue (`qbt-rules.db`) and the rules editor's `.history/`

The log goes to the console. Releases before 0.11 used `/config`: that path is no longer read at all (see [In-Depth Configuration](In-Depth-Configuration#migrating-from-010x)).

Nothing is copied in on first start: with no `rules.yml` there are no rules until you write one (the dashboard's rules editor creates it). `QBT_RULES_CONFIG` (or `--config`) points at another config file; `QBT_RULES_STATE_DIR` moves the state directory, `rules.yml` with it, and `rules.file` points at another rules file. See [In-Depth Configuration](In-Depth-Configuration) for the full `config.yaml`/`rules.yml` schema.

### Q: How do I use environment variables in config files?

A: Two ways. `${VAR}` and `${VAR:-default}` inside `config.yaml` are replaced with that environment variable. And every config key has a corresponding `QBT_RULES_*` environment variable that overrides whatever is in the file:

```yaml
# config.yaml — just omit these keys if you're setting them via environment
# qbittorrent:
#   username: ...
#   password: ...
```

```bash
QBT_RULES_QBITTORRENT_USERNAME=admin
QBT_RULES_QBITTORRENT_PASSWORD=your_password
```

Any of those variables also has a `_FILE`-suffixed counterpart (e.g. `QBT_RULES_QBITTORRENT_PASSWORD_FILE=/run/secrets/qbt_password`) that reads the value from a file instead — the standard pattern for Docker/Compose secrets. See [In-Depth Configuration](In-Depth-Configuration) for the complete `QBT_RULES_*` variable table, and [Security](Security#credential-management) for why the `_FILE` form is preferred.

### Q: Can I have multiple rule files?

A: Currently, the system loads a single rules file. However, you can organize rules within the file using YAML comments and logical grouping, and use [Reusable References](Reusable-References) to avoid duplicating shared conditions/actions:

```yaml
# ===== Content Organization =====
- id: categorize-movies
  # ...

# ===== Cleanup =====
- id: remove-old-torrents
  # ...
```

### Q: What happens if qBittorrent is unreachable?

A: The job fails and the error is recorded in that job's status — check it with `qbt-rules jobs status <id>` or `qbt-rules jobs list`. For scheduled context jobs submitted via cron, make sure whatever submits them (curl, or the CLI client) logs or alerts on a non-2xx/failed response. See [Troubleshooting](Troubleshooting#issue-connection-refused-to-qbittorrent) if the connection is failing consistently rather than intermittently.

### Q: How do I enable trace logging?

A: Turn on trace mode on the **server** (the rules run in its worker, not in the CLI): set `QBT_RULES_LOGGING_TRACE_MODE=true` (or `logging.trace_mode: true` in `config.yaml`), restart, and run a job:

```bash
docker exec qbt-rules qbt-rules execute --dry-run --context manual --wait
docker logs qbt-rules
```

This logs all API calls, field accesses, and condition evaluations, for every job until you turn it off. Trace output can include tracker URLs and tag contents — see [Security](Security#log-hygiene) before sharing a trace log with anyone.

## Field & Condition Questions

### Q: How do I know what fields are available?

A: See the [Available Fields](Available-Fields) page for complete tables. You can also:

1. Enable trace mode (`QBT_RULES_LOGGING_TRACE_MODE=true` on the server) to see all field accesses
2. Check qBittorrent Web API documentation
3. Use `/api/v2/torrents/info` to see raw torrent data

### Q: What's the difference between `info.size` and `info.total_size`?

A: They're **not** aliases — they diverge whenever you've deselected files in a multi-file torrent:

- `info.size` - Size of only the files currently *selected* for download
- `info.total_size` - Size of *every* file in the torrent, selected or not

For a fully-selected torrent they're equal. If you're matching on total content size regardless of what's selected, use `info.total_size`.

### Q: Why is my `files.*` condition not working?

A: `files.*` is a **collection field** — it returns a list, so an ordinary positive operator matches if **ANY** file matches, not all of them:

```yaml
# This checks if ANY file name contains "sample" — not every file
- field: files.name
  operator: contains
  value: "sample"
```

If you want "NO file matches," use `not_contains`/`not_in`/`!=` (checks **ALL** items, not the same ANY-match as above) or wrap a positive check in a `none:` block. See [Conditions](Conditions#collection-field-behavior) for the full ANY/ALL rules and why they differ.

### Q: How do I check if a torrent has NO tags?

A: `info.tags` resolves to a list internally (even though it's documented as a comma-separated string), so comparing it to an empty string with `==` will never match. Use `not_contains` instead — it's specifically defined to return `true` for an empty list regardless of the value given:

```yaml
conditions:
  all:
    - field: info.tags
      operator: not_contains
      value: ""
```

### Q: Can I use regex in conditions?

A: Yes! Use the `matches` operator:

```yaml
- field: info.name
  operator: matches
  value: '(?i).*[Ss]\d{2}[Ee]\d{2}.*'  # TV show pattern
```

Use `(?i)` for case-insensitive matching.

### Q: How do `older_than` and `newer_than` work?

A: They compare a Unix timestamp field against a **human-readable duration string** — not a raw number of seconds, despite `info.added_on`/`info.completion_on` themselves being timestamps:

```yaml
# Torrents added more than 7 days ago
- field: info.added_on
  operator: older_than
  value: "7 days"

# Torrents completed less than 24 hours ago
- field: info.completion_on
  operator: newer_than
  value: "24 hours"
```

**A bare number silently breaks this** — `value: 604800` gets stringified to `"604800"`, which has no recognizable unit, so it parses as `0` and the condition becomes "older than 0 seconds" (true for almost every torrent). Always quote a unit: `"7 days"`, `"12 hours"`, `"30 minutes"`.

### Q: What does `info.state` return?

A: A string with one of 19 possible values (`downloading`, `stalledUP`, `error`, `metaDL`, and so on) — see [Available Fields](Available-Fields#core-torrent-data) for the complete, authoritative list rather than a second copy here that can drift out of sync.

### Q: Can I condition on something across all torrents, not just the one being evaluated?

A: Yes, via the `stats.*` namespace — `stats.state.<state>`, `stats.category.<category>`, `stats.tag.<tag>`, `stats.total`, and the fleet-wide sums `stats.dlspeed`/`stats.upspeed`/`stats.seeds`/`stats.leechs` all give you aggregates computed once per run at zero extra API cost. For example, capping how many torrents can be actively uploading at once:

```yaml
- field: stats.state.uploading
  operator: "<"
  value: 5
```

A missing state/category/tag (nothing currently in it) resolves to `0`, not an error. See [Available Fields](Available-Fields#aggregate-statistics) for the full field list and [Conditions](Conditions#fleet-wide-conditions-with-stats) for a worked example — including the snapshot caveat: `stats.*` reflects torrent state as of the start of the run, not live changes made by earlier rules in that same run.

## Context Questions

### Q: How often do scheduled context jobs run?

A: qbt-rules doesn't schedule anything itself — you control the schedule with cron, a systemd timer, or a sidecar container, and it submits a job to the server via the HTTP API or CLI client:

```bash
0 3 * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=nightly"
```

See [Contexts](Contexts#scheduledrecurring-contexts) for the cron and systemd-timer versions side by side.

### Q: Can I test scheduled rules without waiting?

A: Yes! Submit a job with `--dry-run` right now instead of waiting for cron:

```bash
docker exec qbt-rules qbt-rules execute --dry-run --context hourly --wait
```

This evaluates every rule whose `context:` matches (or that has no `context:` at all) immediately.

### Q: How do webhooks work?

A: qBittorrent's "Run external program" hooks (Tools → Options → Downloads) call the server's HTTP API directly, passing the torrent's hash so only that one torrent gets evaluated:

```bash
curl -X POST "http://qbt-rules:5000/api/execute?context=torrent-imported&hash=%I&key=YOUR_API_KEY"
```

See [Contexts](Contexts#wiring-up-qbittorrent-webhooks) for the full wiring steps (added *and* completed events) — and importantly, why a `files.*`-checking rule that's *only* allowed to run in `torrent-imported` can miss magnet-link torrents (see [Security](Security#known-limitation-magnet-link-metadata-timing)).

### Q: Can I filter which torrents a rule processes?

A: There's no separate pre-filter step — the engine fetches the full torrent list once per job and every rule's `conditions:` decides what it matches. To restrict a rule to a category or state, just add that as a condition using the free `info.*` fields:

```yaml
context: manual
conditions:
  all:
    - field: info.category
      operator: "=="
      value: "Movies"
    - field: info.state
      operator: "=="
      value: "downloading"
    - field: info.ratio
      operator: "<"
      value: 1.0
```

Since `info.*` fields are already loaded with the initial torrent list (zero extra API calls), this has no performance cost over a "real" pre-filter.

### Q: What's the difference between `manual` and `scheduled` contexts?

A: There isn't one built into the engine — `manual`, `scheduled`, `on_added`, and `on_completed` were fixed trigger names in versions before v0.4.1. Since then, contexts are just strings you choose; `manual` and `scheduled` are naming *conventions*, not special cases the engine treats differently. Any rule with `context: manual` only runs when a job is submitted with `context=manual`, the same as any other context name:

```yaml
- id: one-off-cleanup-run-by-hand
  context: manual
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
```

See [Contexts](Contexts) for the full picture, including why security-sensitive rules that inspect `files.*` often should omit `context:` entirely.

## Action Questions

### Q: Will `stop` action pause a torrent that's already paused?

A: No - actions are **idempotent**. The engine checks the current state before acting and skips it if the torrent is already in the desired state. The run's summary counts the skips; `logging.level: DEBUG` logs each one with the action that was skipped.

### Q: What's the difference between `start` and `force_start`?

A:

- **start** - Resume normal downloading/seeding (respects queue limits)
- **force_start** - Force the torrent to start regardless of queue limits (useful for private trackers or low-seeded content)

`force_start` doesn't undo itself — a torrent stays force-started until a rule explicitly releases it with `release_force_start` (v0.7.1+), which hands it back to normal queue management without stopping/pausing it. See [Quota-Gated Seed Rotation](Examples#quota-gated-seed-rotation) for a pattern that pairs the two.

### Q: Does `delete_torrent` remove files from disk?

A: By default, yes — `delete_torrent` removes the underlying files unless you explicitly say not to:

```yaml
actions:
  - type: delete_torrent
    params:
      delete_files: false  # Remove from qBittorrent only, keep files on disk
```

Omitting `params` entirely also deletes the files (`delete_files` defaults to `true`).

### Q: Can I set multiple tags at once?

A: Yes! Use `set_tags` with a `tags` **list** — there's no singular `tag` parameter, and a comma-separated string won't be split for you:

```yaml
actions:
  - type: set_tags
    params:
      tags: ["movies", "hd", "private"]
```

This **replaces** all existing tags. To add tags while keeping existing ones, use `add_tag` (same `tags:` list parameter).

### Q: How do I remove all tags?

A: Use `set_tags` with an empty list:

```yaml
actions:
  - type: set_tags
    params:
      tags: []
```

### Q: What does `limit: -1` mean for upload/download limits?

A: `-1` means **unlimited** (removes any speed limit).

### Q: Can I run multiple actions for the same torrent?

A: Yes! Actions execute in order:

```yaml
actions:
  - type: set_category
    params:
      category: "Movies"
  - type: add_tag
    params:
      tags: ["auto-categorized"]
  - type: stop
```

All three actions will execute if conditions match.

### Q: Can I change a torrent's queue position?

A: Yes — `increase_priority`, `decrease_priority`, `set_top_priority`, and `set_bottom_priority` adjust qBittorrent's torrent queue (relevant when queuing is enabled in qBittorrent's own settings). See [Actions](Actions) for the full parameter reference.

## Performance Questions

### Q: How many API calls does the system make?

A: One call for the initial torrent list, then one additional call **per torrent** for each non-`info.*` field category a rule actually accesses (`trackers.*`, `files.*`, `properties.*`, `peers.*`, `webseeds.*`) — see the [Available Fields](Available-Fields#field-categories-overview) overview table for the full per-category cost breakdown.

**Example:** 100 torrents, rules that only check `info.*` fields: **1 call total**. Add a `trackers.url` check: **1 + 100 = 101 calls**.

### Q: How can I reduce API calls?

A: Put cheap `info.*` checks first in each `all:` block — `all()` evaluation short-circuits, so an expensive `trackers.*`/`files.*`/`peers.*` check later in the same list never runs for a torrent that already failed an earlier check. See [Advanced Topics](Advanced-Topics#performance-optimization) for the full pattern, including field reuse and `stop_on_match` guidance.

### Q: Can I run this on a system with 10,000+ torrents?

A: Yes — the engine evaluates torrents one at a time rather than loading everything into memory at once, so memory use stays flat regardless of library size. The same cheap-first ordering from the previous question is what keeps it fast; see [Advanced Topics](Advanced-Topics#large-libraries) for the rest of the levers (webhook scoping, worker count) if a sweep is still slow.

### Q: How long does execution take?

A: There's no fixed number — it depends on torrent count, how many rules touch expensive fields (`trackers.*`/`files.*`/`peers.*`/`webseeds.*`, each an API call per torrent), and network latency to qBittorrent. Rules that only touch `info.*` are effectively instant regardless of library size, since that data is already loaded; anything checking expensive fields scales roughly linearly with the number of torrents that reach that check. Use trace mode (`QBT_RULES_LOGGING_TRACE_MODE=true` on the server) to see actual timing for your own setup rather than relying on a generic benchmark that won't reflect your rule set or hardware.

## Error & Troubleshooting Questions

### Q: I'm getting `401 Unauthorized` errors

A: An HTTP `401` from qbt-rules' own API is **always** a `server.api_key` mismatch — the server checks the key before touching qBittorrent at all. Confirm the `key=`/`X-API-KEY` value you're sending matches `QBT_RULES_SERVER_API_KEY` (or its `_FILE` equivalent).

A *wrong qBittorrent password* is a different failure entirely — it doesn't produce an HTTP 401 to you, since it happens later, inside the worker, while the job is running. The job just fails; check `qbt-rules jobs status <id>` for an authentication error, and verify `QBT_RULES_QBITTORRENT_USERNAME`/`QBT_RULES_QBITTORRENT_PASSWORD` (or `config.yaml`'s `qbittorrent:` block) against what qBittorrent's Web UI actually expects.

### Q: Rules aren't matching torrents I expect

A: Enable trace mode on the server (`QBT_RULES_LOGGING_TRACE_MODE=true`, then restart) to see condition evaluation, and run a job:

```bash
docker exec qbt-rules qbt-rules execute --dry-run --context manual --wait
```

Look for lines like:

```text
[TRACE] Evaluating condition: info.ratio >= 2.0
[TRACE] Result: False (actual value: 1.5)
```

### Q: Getting unexpected `False` results when accessing fields

A: Not all fields exist for all torrents. Missing fields resolve to `None`, and the engine treats `None` as automatically satisfying `!=`/`not_in`/`not_contains` and failing every other operator — so a condition on a missing field quietly evaluates to `False` rather than raising an error. Check that you're using correct field names from the [Available Fields](Available-Fields) table, and use trace mode to confirm what value was actually read.

### Q: My scheduled context job isn't running

A: Context jobs don't run themselves - either list them in `config.yaml`'s `schedule:` for the internal scheduler (check the server log at startup for the entries it loaded; see [Scheduling](Scheduling)), or have something external (cron, a systemd timer, or a sidecar container) submit them:

**Cron example:**

```bash
0 * * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=hourly" >> /var/log/qbt-rules-cron.log 2>&1
```

Confirm the job actually landed in the queue with `qbt-rules jobs list`.

### Q: Webhooks aren't triggering

A: Verify qBittorrent webhook configuration:

1. Check qBittorrent logs for errors running the external program
2. If you're using `curl` against the HTTP API (recommended), test the exact command manually first:

   ```bash
   curl -X POST "http://qbt-rules:5000/api/execute?context=torrent-imported&hash=<actual_torrent_hash>&key=YOUR_API_KEY"
   ```

3. If you're using the CLI client (`qbt-rules execute --context torrent-imported --hash "%I"`, perhaps via `docker exec`) instead, run the exact line by hand, confirm the container name is correct and the server is reachable from inside it. A hook still on 0.10.x's `qbt-rules --context ...` form exits 2: add `execute` after `qbt-rules`.
4. Confirm `QBT_RULES_SERVER_API_KEY` matches the `key=`/`X-API-KEY` value you're sending.

### Q: Changes aren't applying to torrents

A: Check:

1. **Dry-run mode**: Are you using `--dry-run`? Remove it to apply changes.
2. **Idempotency**: Action may be skipped if torrent already in desired state (the run summary's `skipped: already in desired state` count; each skip is logged at `DEBUG`)
3. **Conditions**: Rule may not be matching (use trace mode)
4. **stop_on_match**: Earlier rule may have matched first
5. **Context**: The job's context may not match the rule's `context:` field at all — a mismatched context means the rule is silently skipped, not evaluated-and-failed

## Docker & Deployment Questions

### Q: Can I run this in Docker?

A: Docker is the only supported way to run qbt-rules — there's no PyPI package for end users. See [Quick Start](Quick-Start) and [Deployment](Deployment) for the full Compose setup; the short version:

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
      QBT_RULES_SERVER_API_KEY: "your-secure-api-key-here"
      QBT_RULES_QBITTORRENT_HOST: "http://qbittorrent:8080"
      QBT_RULES_QBITTORRENT_USERNAME: "admin"
      QBT_RULES_QBITTORRENT_PASSWORD: "adminpass"
```

The container runs the HTTP server and worker continuously — there's no cron loop to write yourself; scheduling is handled by the internal scheduler (see [Scheduling](Scheduling)) or by whatever *submits* jobs to it (see below).

### Q: How do I deploy scheduled jobs with systemd?

A: The qbt-rules server itself runs continuously inside its container — a systemd timer on the host is only for triggering a job *submission* on a schedule, not for running the engine itself. See [Contexts](Contexts#scheduledrecurring-contexts) for a complete `.service`/`.timer` pair you can copy.

### Q: Can I run multiple instances?

A: You only need one qbt-rules server per qBittorrent instance — it's a persistent client-server deployment, not a per-schedule process you spin up and tear down. Don't run a second server against the same qBittorrent: its scheduler would fire every entry again. Jobs run one at a time, in order. Separate *workloads* (frequent webhook-driven categorization vs. a daily cleanup sweep) are handled by using different `context` values against the same server, not by running different instances — see [Advanced Topics](Advanced-Topics) for scaling guidance.

### Q: How do I integrate with Sonarr/Radarr?

A: Same mechanism as any other webhook — configure qBittorrent's "Run external program on torrent added" to hit the HTTP API with a context, then write a rule matching whatever category/tag Sonarr or Radarr assigns. See [Advanced Topics](Advanced-Topics#integration-with-sonarrradarr) for the complete webhook command and rule example.
