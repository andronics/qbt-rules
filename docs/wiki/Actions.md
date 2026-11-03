Actions execute when rule conditions match. Multiple actions can be specified per rule and execute sequentially.

If the same action sequence shows up in multiple rules, see [Reusable References](Reusable-References) — define it once under `refs.actions` and pull it in anywhere with `$ref: actions.name`.

### Overview

**Available Actions:**

| Action | Description | Idempotent | Parameters |
|--------|-------------|------------|------------|
| `stop` | Stop/pause torrent | Yes | None |
| `start` | Start/resume torrent | Yes | None |
| `force_start` | Force start (bypass queue) | Yes | None |
| `release_force_start` | Release a force-started torrent back to normal queue management | Yes | None |
| `recheck` | Recheck torrent files | No | None |
| `reannounce` | Force reannounce to trackers | No | None |
| `delete_torrent` | Delete torrent from qBittorrent | No | `delete_files` |
| `set_category` | Set torrent category | Yes | `category` |
| `add_tag` | Add tags to torrent | Yes | `tags` |
| `remove_tag` | Remove tags from torrent | Yes | `tags` |
| `set_tags` | Replace all tags | No | `tags` |
| `set_upload_limit` | Set upload speed limit | No | `limit` |
| `set_download_limit` | Set download speed limit | No | `limit` |
| `increase_priority` | Move up one position in the download queue | No | None |
| `decrease_priority` | Move down one position in the download queue | No | None |
| `set_top_priority` | Move to the top of the download queue | No | None |
| `set_bottom_priority` | Move to the bottom of the download queue | No | None |
| `set_file_priority` | Set the download priority of individual files *(v0.9.0+)* | Yes | `priority`, `pattern` |
| `notify` | Send an outbound webhook notification | No | `service`, `url`, `message` (or `body`) |
| `arr_blocklist` | Blocklist a bad download in Sonarr/Radarr, optionally triggering a re-search | No | `service`, `remove_from_client`, `search` |

**Idempotent Actions:**

- **Yes**: Skipped if already in desired state (logged as "skipped")
- **No**: Always execute

### stop

**Description:** Stop/pause torrent (qBittorrent v5.0+ calls this "stop"; older v4.x servers call the same operation "pause" — qbt-rules' `qbittorrent-api` dependency handles the naming difference for you, so `stop` works regardless of your qBittorrent version)

**Parameters:** None

**Idempotent:** Yes (skips if already paused/stopped)

**Syntax:**

```yaml
actions:
  - type: stop
```

**Use Cases:**

- Pause well-seeded torrents to free bandwidth
- Stop torrents in error state
- Pause torrents exceeding ratio requirements
- Stop downloading after categorization for review

**Example:**

```yaml
- id: pause-well-seeded-torrents
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 3.0
      - field: info.num_leechs
        operator: ==
        value: 0
  actions:
    - type: stop
```

### start

**Description:** Start/resume torrent (qBittorrent v5.0+ calls this "start"; older v4.x servers call it "resume" — handled transparently regardless of your qBittorrent version)

**Parameters:** None

**Idempotent:** Yes (skips if already running)

**Syntax:**

```yaml
actions:
  - type: start
```

**Use Cases:**

- Resume paused torrents
- Auto-start torrents meeting criteria
- Re-enable stopped torrents after fixes

**Example:**

```yaml
- id: resume-torrents-under-ratio
  conditions:
    all:
      - field: info.ratio
        operator: "<"
        value: 1.0
      - field: info.state
        operator: ==
        value: pausedUP
  actions:
    - type: start
```

### force_start

**Description:** Force start torrent (bypasses queue limits)

**Parameters:** None

**Idempotent:** Yes (skips if `info.force_start` is already `true`)

**Syntax:**

```yaml
actions:
  - type: force_start
```

**Use Cases:**

- Prioritize private tracker torrents under ratio
- Force-seed important torrents
- Override queue limits for specific content

**Example:**

```yaml
- id: force-start-private-under-ratio
  conditions:
    all:
      - field: info.ratio
        operator: "<"
        value: 1.0
      - field: trackers.url
        operator: contains
        value: ".private"
  actions:
    - type: force_start
```

**Note:** Use sparingly - bypasses qBittorrent's queue management. `force_start` is a one-way override on its own — nothing un-sets it later unless a rule explicitly calls `release_force_start`. If you're using `force_start` to enforce a budget (e.g. via [`stats.tag.*`](Available-Fields#aggregate-statistics)), pair it with a `release_force_start` rule so slots free up again — see [Quota-Gated Seed Rotation](Examples#quota-gated-seed-rotation).

### release_force_start

**Description:** Release a force-started torrent back to qBittorrent's normal queue management (the reverse of `force_start`)

**Parameters:** None

**Idempotent:** Yes (skips if `info.force_start` is already `false`)

**Syntax:**

```yaml
actions:
  - type: release_force_start
```

**Use Cases:**

- Hand a torrent back to the queue once it's met the condition that justified force-starting it (e.g. ratio target reached)
- Free up a budget slot in a quota-gated rotation scheme once a torrent no longer needs priority
- Undo a `force_start` applied by an earlier rule without also pausing the torrent

**Example:**

```yaml
- id: release-seed-quota-when-ratio-met
  conditions:
    all:
      - field: info.tags
        operator: contains
        value: "force-seeding"
      - field: info.ratio
        operator: ">="
        value: 1.0
  actions:
    - type: release_force_start
    - type: remove_tag
      params:
        tags: [force-seeding]
```

**Note:** Releasing a torrent doesn't stop or pause it — it just stops overriding qBittorrent's own queue limits for that torrent, so its active/inactive state afterward is decided by qBittorrent's normal queue management again.

### recheck

**Description:** Recheck torrent files for integrity

**Parameters:** None

**Idempotent:** No (always executes)

**Syntax:**

```yaml
actions:
  - type: recheck
```

**Use Cases:**

- Fix stalled downloads near completion
- Verify files after external modification
- Troubleshoot corrupted data

**Example:**

```yaml
- id: recheck-stalled-near-completion
  conditions:
    all:
      - field: info.state
        operator: ==
        value: stalledDL
      - field: info.progress
        operator: ">"
        value: 0.9
  actions:
    - type: recheck
```

### reannounce

**Description:** Force reannounce to all trackers

**Parameters:** None

**Idempotent:** No (always executes)

**Syntax:**

```yaml
actions:
  - type: reannounce
```

**Use Cases:**

- Update tracker stats immediately
- Fix tracker communication issues
- Refresh peer list

**Example:**

```yaml
- id: reannounce-private-periodically
  context: scheduled
  conditions:
    all:
      - field: trackers.url
        operator: contains
        value: ".private"
  actions:
    - type: reannounce
```

### delete_torrent

**Description:** Delete torrent from qBittorrent

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `delete_files` | boolean | No | `true` | Also delete the downloaded files from disk |

**Idempotent:** No (deletes permanently)

**Syntax:**

```yaml
# Delete torrent and files (also the default if params are omitted entirely)
actions:
  - type: delete_torrent
    params:
      delete_files: true

# Delete torrent, keep files
actions:
  - type: delete_torrent
    params:
      delete_files: false
```

**Use Cases:**

- Remove old completed torrents
- Clean up errored torrents
- Delete torrents with missing files
- Space management

**Examples:**

```yaml
# Delete old completed torrents (including files)
- id: delete-old-completed
  conditions:
    all:
      - field: info.completion_on
        operator: older_than
        value: 30 days
      - field: info.ratio
        operator: ">="
        value: 1.0
  actions:
    - type: delete_torrent
      params:
        delete_files: true
```

```yaml
# Remove errored torrents (keep files)
- id: remove-errored-torrents
  conditions:
    any:
      - field: info.state
        operator: ==
        value: error
      - field: info.state
        operator: ==
        value: missingFiles
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

**WARNING:** Deletion is permanent! Always test with `--dry-run` first.

### set_category

**Description:** Set torrent category

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | string | Yes | Category name (empty string `""` to remove) |

**Idempotent:** Yes (skips if already set)

**Syntax:**

```yaml
# Set category
actions:
  - type: set_category
    params:
      category: movies-hd

# Remove category
actions:
  - type: set_category
    params:
      category: ""
```

**Use Cases:**

- Auto-categorize by content type
- Organize by tracker
- Group by resolution or quality
- Migrate between categories

**Examples:**

```yaml
# Auto-categorize HD movies
- id: categorize-hd-movies
  conditions:
    all:
      - field: info.name
        operator: matches
        value: '(?i).*(1080p|2160p).*'
      - field: info.category
        operator: ==
        value: ""
  actions:
    - type: set_category
      params:
        category: movies-hd
```

```yaml
# Categorize by tracker
- id: categorize-private-tracker-content
  conditions:
    all:
      - field: trackers.url
        operator: contains
        value: ".private"
  actions:
    - type: set_category
      params:
        category: private
```

**Important:** Category must exist in qBittorrent (create manually first)

### add_tag

**Description:** Add one or more tags to torrent

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tags` | list[string] | Yes | Tag names to add |

**Idempotent:** Yes (skips if all tags already present)

**Syntax:**

```yaml
actions:
  - type: add_tag
    params:
      tags:
        - hd
        - private
        - auto-tagged
```

**Use Cases:**

- Tag by content attributes
- Mark torrents by tracker
- Flag for manual review
- Track automation actions

**Examples:**

```yaml
# Tag HD content
- id: tag-hd-content
  conditions:
    all:
      - field: info.name
        operator: matches
        value: '(?i).*(1080p|2160p|4k).*'
  actions:
    - type: add_tag
      params:
        tags:
          - hd
```

```yaml
# Tag completed large downloads
- id: tag-large-completed-downloads
  context: on_completed
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "10GB"
  actions:
    - type: add_tag
      params:
        tags:
          - completed-large
          - needs-seeding
```

### remove_tag

**Description:** Remove one or more tags from torrent

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tags` | list[string] | Yes | Tag names to remove |

**Idempotent:** Yes (skips if tags not present)

**Syntax:**

```yaml
actions:
  - type: remove_tag
    params:
      tags:
        - temporary
        - review-needed
```

**Use Cases:**

- Clean up temporary tags
- Remove outdated markers
- Clear automation flags

**Example:**

```yaml
# Remove temporary tag after processing
- id: clean-up-temp-tags
  conditions:
    all:
      - field: info.tags
        operator: contains
        value: "temp"
      - field: info.completion_on
        operator: older_than
        value: 1 days
  actions:
    - type: remove_tag
      params:
        tags:
          - temp
```

### set_tags

**Description:** Replace all tags with new set (removes existing first)

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tags` | list[string] | Yes | Complete tag list |

**Idempotent:** No (always executes)

**Syntax:**

```yaml
actions:
  - type: set_tags
    params:
      tags:
        - hd
        - verified
```

**Use Cases:**

- Reset tagging completely
- Enforce specific tag set
- Clear all tags and apply new ones

**Example:**

```yaml
# Reset tags for completed torrents (no conditions — matches every torrent
# in this context). `conditions` is a required key, so use an explicit
# empty object `{}` for an unconditional rule rather than leaving it blank —
# a blank `conditions:` parses as null and logs an evaluation error per torrent.
- id: reset-tags-on-completion
  context: on_completed
  conditions: {}
  actions:
    - type: set_tags
      params:
        tags:
          - completed
          - seeding
```

### set_upload_limit

**Description:** Set per-torrent upload speed limit

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | Yes | Upload limit in bytes/s (`-1` for unlimited) |

**Idempotent:** No (always executes)

**Syntax:**

```yaml
# Limit to 100 KB/s
actions:
  - type: set_upload_limit
    params:
      limit: 102400

# Remove limit (unlimited)
actions:
  - type: set_upload_limit
    params:
      limit: -1
```

**Use Cases:**

- Throttle well-seeded torrents
- Prioritize bandwidth for new uploads
- Limit old torrents to free bandwidth
- Manage bandwidth allocation

**Examples:**

```yaml
# Throttle old torrents
- id: limit-upload-old-torrents
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 5.0
      - field: info.seeding_time
        operator: ">"
        value: 2592000  # 30 days
  actions:
    - type: set_upload_limit
      params:
        limit: 102400  # 100 KB/s
```

**Common Speed Conversions:**

| Speed | Bytes/Second |
|-------|--------------|
| 50 KB/s | 51200 |
| 100 KB/s | 102400 |
| 500 KB/s | 512000 |
| 1 MB/s | 1048576 |
| 5 MB/s | 5242880 |
| 10 MB/s | 10485760 |

### set_download_limit

**Description:** Set per-torrent download speed limit

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | Yes | Download limit in bytes/s (`-1` for unlimited) |

**Idempotent:** No (always executes)

**Syntax:**

```yaml
# Limit to 1 MB/s
actions:
  - type: set_download_limit
    params:
      limit: 1048576

# Remove limit (unlimited)
actions:
  - type: set_download_limit
    params:
      limit: -1
```

**Use Cases:**

- Throttle large downloads
- Prevent bandwidth saturation
- Prioritize specific torrents
- Time-based speed management

**Example:**

```yaml
# Limit large downloads
- id: throttle-large-downloads
  context: on_added
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "20GB"
  actions:
    - type: set_download_limit
      params:
        limit: 2097152  # 2 MB/s
```

### increase_priority / decrease_priority / set_top_priority / set_bottom_priority

**Description:** Move a torrent's position in qBittorrent's download queue by one step (`increase_priority`/`decrease_priority`) or straight to the front/back (`set_top_priority`/`set_bottom_priority`).

**Parameters:** None

**Idempotent:** No (always executes — these are relative queue moves, not a check against a target state)

**Requires:** qBittorrent's queue management feature must be enabled (Options → Downloads → Torrent Queueing) for these calls to have any effect. If queueing is disabled, `info.priority` reports `-1` for every torrent and these actions are effectively no-ops.

**Syntax:**

```yaml
actions:
  - type: increase_priority

actions:
  - type: decrease_priority

actions:
  - type: set_top_priority

actions:
  - type: set_bottom_priority
```

**Use Cases:**

- Bump newly-imported episodes of an actively-watched show to the front of the queue
- Push large, low-priority archival torrents to the back so active downloads finish first
- De-prioritize torrents that are close to a ratio/seeding-time cleanup threshold anyway

**Example:**

```yaml
# Jump new episodes of a tracked show to the front of the queue
- id: prioritize-new-episodes-on-import
  context: torrent-imported
  conditions:
    all:
      - field: info.category
        operator: "=="
        value: "tv-sonarr"
  actions:
    - type: set_top_priority
```

```yaml
# Deprioritize very large torrents so smaller ones finish first
- id: deprioritize-large-torrents
  context: torrent-imported
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "50GB"
  actions:
    - type: set_bottom_priority
```

### set_file_priority

**Description:** Set the download priority of a torrent's individual files: all of them, or only those whose path matches a pattern. Use it to stop downloading samples, extras or other unwanted files without removing the torrent. *(v0.9.0+)*

Not to be confused with the `*_priority` actions above, which move the whole torrent in the download queue.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `priority` | integer or string | Yes | `0` / `skip` (do not download), `1` / `normal`, `6` / `high`, `7` / `maximum` |
| `pattern` | string (regex) | No | Only change files whose path within the torrent matches (searched anywhere in the path, as `files.name` reports it). Omit to change every file |

**Idempotent:** Yes. Files already at the requested priority are left alone, and if no matching file needs changing the action is skipped. The new priorities are visible to `files.priority` in later rules of the same run.

**Notes:**

- Shares the per-run file list with `files.*` conditions, so a rule that matched on `files.name` doesn't fetch it twice.
- Right after a torrent is added, qBittorrent may not have loaded its file list yet. The action then logs a warning, does nothing, and is retried on the next run. Run it from `torrent-imported` and a scheduled context, or a later context, to be sure it applies.
- An invalid `priority` or `pattern` is logged as an error when the rule runs and nothing is changed.
- Setting priority `0` on a file that has already downloaded doesn't delete it from disk; qBittorrent just stops tracking it for completion.

**Syntax:**

```yaml
# Don't download sample files
actions:
  - type: set_file_priority
    params:
      priority: skip
      pattern: '(?i)(^|/)sample'

# Every file at maximum priority
actions:
  - type: set_file_priority
    params:
      priority: maximum
```

**Use Cases:**

- Skip sample files, extras, or `.nfo`/`.txt` clutter
- Download only the main video in a multi-file release
- Raise the priority of the first files of a large pack so they finish first

**Example:**

```yaml
# Skip samples and extras on movie torrents
- id: skip-movie-extras
  context: [torrent-imported, hourly]
  conditions:
    all:
      - field: info.category
        operator: "=="
        value: movies
      - field: files.name
        operator: matches
        value: '(?i)(^|/)(sample|extras|featurettes)/'
  actions:
    - type: set_file_priority
      params:
        priority: skip
        pattern: '(?i)(^|/)(sample|extras|featurettes)/'
```

### notify

**Description:** Send an outbound webhook notification when a rule matches — Discord, Slack, ntfy, or a generic JSON webhook.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `service` | string | No | `notifications.service` config, or `generic` | One of `discord`, `slack`, `ntfy`, `generic` |
| `url` | string | No* | `notifications.webhook_url` config | Webhook URL. *Required if no config default is set |
| `message` | string | No** | — | Template string, supports `{field}` placeholders from the torrent's fields (e.g. `{name}`, `{ratio}`, `{tags}`). **Required unless `service: generic` and `body:` is given |
| `body` | object | No | — | `generic` only: a literal JSON payload sent as-is, **not** templated — a manual escape hatch for services with a different required shape |

**Idempotent:** No (always fires — see [Reduce Duplicate Notifications](#reduce-duplicate-notifications) below)

**Payload shape per service:**

| Service | Body sent | Content-Type |
|---|---|---|
| `discord` | `{"content": message}` | `application/json` |
| `slack` | `{"text": message}` | `application/json` |
| `ntfy` | raw `message` text (not JSON-wrapped) | `text/plain` |
| `generic` | `{"message": message}`, or `body:` verbatim if given | `application/json` |

**Syntax:**

```yaml
actions:
  - type: notify
    params:
      service: discord
      url: "https://discord.com/api/webhooks/your-webhook-here"
      message: "Torrent {name} matched, ratio {ratio}, tags: {tags}"
```

**Message templating:** any field from [Available Fields](Available-Fields)'s `info.*` category works as a `{placeholder}` — the torrent dict is passed to Python's `str.format()` directly. `{tags}` is a special case: `info.tags` is qBittorrent's raw comma-separated string (`"hd,new"`, no space), so `notify` cleans it up into a friendly `", "`-joined list before templating. Referencing a field the torrent doesn't have logs a warning and skips firing — it won't crash the rule.

**Use Cases:**

- Get pinged when a rule deletes something, so you can catch a bad rule before it does real damage
- Track down auto-categorization or cleanup activity without digging through logs
- Alert on rules that flag content for manual review (see [Security](Security#content-safety-rules))

**Examples:**

```yaml
# Notify on Discord whenever a torrent gets auto-deleted
- id: notify-on-cleanup
  context: nightly
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
  actions:
    - type: delete_torrent
      params:
        delete_files: true
    - type: notify
      params:
        service: discord
        message: "Deleted {name} (ratio {ratio})"
```

```yaml
# ntfy, relying on a configured notifications.webhook_url
# so no url: is needed per-rule
- id: flag-suspicious-file-types
  context: torrent-imported
  conditions:
    any:
      - field: files.name
        operator: matches
        value: '(?i)\.(exe|scr|bat)$'
  actions:
    - type: add_tag
      params:
        tags: ["needs-review"]
    - type: notify
      params:
        service: ntfy
        message: "{name} flagged for review — unexpected executable file"
```

```yaml
# generic, with a manually-built body for a service with its own shape
- id: custom-webhook-on-completion
  context: download-finished
  conditions: {}
  actions:
    - type: notify
      params:
        service: generic
        url: "https://example.com/my-webhook"
        body:
          event: "torrent_completed"
          source: "qbt-rules"
```

**Chaining after `delete_torrent`:** placing `notify` right after `delete_torrent` in the same rule's `actions:` list is safe and renders the correct (pre-deletion) torrent name — the engine's per-rule action loop keeps working from the same in-memory torrent snapshot even after the torrent stops existing in qBittorrent; only the *next* rule's iteration would skip it.

### arr_blocklist

**Description:** Blocklist a torrent's queue entry in Sonarr or Radarr, and by default trigger a re-search — the automated version of manually clicking "blocklist and search" in the arr's UI when a download turns out to be bad (fake, wrong content, stalled indefinitely). Correlates the torrent to the arr's own download queue via `downloadId`, not category — this is a different mechanism from the category-based auto-tagging pattern in [Advanced Topics](Advanced-Topics#integration-with-sonarrradarr).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `service` | string | **Yes** | — | `sonarr` or `radarr` |
| `remove_from_client` | boolean | No | `false` | Whether the arr should also remove the download from qBittorrent. Defaults to `false` because this action is meant to run *after* `delete_torrent` already removed it — see the warning below |
| `search` | boolean | No | `true` | Whether to trigger a replacement search after blocklisting. Set `false` for blocklist-only — e.g. reviewing candidates before letting the arr re-grab anything |

**Idempotent:** No (always makes the API calls; if the torrent isn't in the arr's queue anymore, it's a non-fatal skip — see below)

**Requires configuration:** `integrations.sonarr.url`/`.api_key` and/or `integrations.radarr.url`/`.api_key` in `config.yml` — see [In-Depth Configuration](In-Depth-Configuration). The action fails (logs an error, doesn't crash the rule) if the referenced service isn't configured.

**Syntax:**

```yaml
actions:
  - type: delete_torrent
    params:
      delete_files: true
  - type: arr_blocklist
    params:
      service: sonarr
```

**⚠️ Ordering matters.** `remove_from_client` defaults to `false` because the expected pattern is `delete_torrent` first, `arr_blocklist` second — qBittorrent has already been cleaned up by the time this action runs. If you use this action **without** a preceding `delete_torrent`, override `remove_from_client: true`, or the download keeps running in qBittorrent even after Sonarr/Radarr blocklists it and starts a new search — you'll end up downloading the bad release again alongside the new one.

**What "no match" means:** most torrents in your client aren't managed by an arr at all (manual downloads, other categories). If the torrent's hash isn't found in the arr's queue, this logs a warning and the action reports success — it's a skip, not an error, so it won't inflate your job's error count.

**Season packs / multi-episode downloads:** a single torrent can produce multiple queue records in Sonarr (one per episode) sharing the same `downloadId`. This action collects all of them, blocklists every record, and triggers one combined search covering every affected episode — not just the first.

**Example:**

```yaml
- id: replace-failed-downloads-via-sonarr
  context: torrent-imported
  conditions:
    any:
      - field: info.name
        operator: contains
        value: "SAMPLE"
      - field: trackers.status
        operator: "=="
        value: 4  # tracker reports not registered / fake
  actions:
    - type: delete_torrent
      params:
        delete_files: true
    - type: arr_blocklist
      params:
        service: sonarr
    - type: notify
      params:
        service: discord
        message: "Blocklisted and re-searching: {name}"
```

```yaml
# Blocklist only, no automatic re-search -- flag for manual review instead
- id: blocklist-suspected-fakes
  context: torrent-imported
  conditions:
    any:
      - field: info.name
        operator: contains
        value: "SAMPLE"
  actions:
    - type: delete_torrent
      params:
        delete_files: true
    - type: arr_blocklist
      params:
        service: sonarr
        search: false
    - type: notify
      params:
        service: discord
        message: "Blocklisted {name} -- review before re-searching"
```

### Reduce Duplicate Notifications

`notify` has no idempotency tracking — a rule re-evaluated across multiple contexts (`torrent-imported`, `download-finished`, a recurring sweep) fires again every time it still matches. If that's not what you want, pair it with `add_tag` plus a condition excluding already-tagged torrents:

```yaml
- id: notify-once-per-torrent
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
      - field: info.tags
        operator: not_contains
        value: "notified"
  actions:
    - type: notify
      params:
        service: discord
        message: "{name} hit ratio {ratio}"
    - type: add_tag
      params:
        tags: ["notified"]
```
