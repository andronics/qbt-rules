This section provides real-world rule examples organised by common use cases. For one complete `rules.yml` that combines them with reusable references, see [Advanced Rules Example](Advanced-Rules-Example).

**Handy reminders while reading these examples:**

- **Human-readable sizes**: Use `larger_than` and `smaller_than` with values like `"50GB"`, `"100MB"`, `"1TB"`
- **Contexts are free-form**: Define your own context names (e.g., `context: hourly`, `context: weekend`) — see [Contexts](Contexts)
- **Context-agnostic rules**: A rule with no `context:` field runs regardless of what context the job was submitted with. To run only those rules, submit a job with no `--context` option at all (`qbt-rules execute`) (not `--context none` — that would be treated as the literal context string `"none"`, not "no context")

### Content Organisation

#### Auto-Categorise Movies

```yaml
- id: auto-categorize-hd-movies
  enabled: true
  stop_on_match: true
  context: on_added
  conditions:
    all:
      - field: info.name
        operator: matches
        value: '(?i).*(1080p|2160p|4k).*\.(mkv|mp4|avi)$'
  actions:
    - type: set_category
      params:
        category: "Movies-HD"
    - type: add_tag
      params:
        tags: ["movies"]
```

#### Auto-Categorize TV Shows

```yaml
- id: auto-categorize-tv-shows
  enabled: true
  stop_on_match: true
  context: on_added
  conditions:
    all:
      - field: info.name
        operator: matches
        value: '(?i).*[Ss]\d{2}[Ee]\d{2}.*'
  actions:
    - type: set_category
      params:
        category: "TV-Shows"
    - type: add_tag
      params:
        tags: ["tv"]
```

#### Organize by Tracker

```yaml
- id: categorize-private-tracker-content
  enabled: true
  stop_on_match: true
  context: on_added
  conditions:
    any:
      - field: trackers.url
        operator: contains
        value: "privatehd.to"
      - field: trackers.url
        operator: contains
        value: "passthepopcorn.me"
  actions:
    - type: set_category
      params:
        category: "Private"
    - type: add_tag
      params:
        tags: ["private-tracker"]
```

### 9.2 Content Filtering

#### Block Archive Files

```yaml
- id: remove-archive-only-torrents
  enabled: true
  stop_on_match: true
  context: on_added
  conditions:
    all:
      - field: files.name
        operator: matches
        value: '(?i).*\.(rar|zip|7z|tar|gz)$'
  actions:
    - type: delete_torrent
      params:
        delete_files: true
```

#### Remove Sample Files

```yaml
- id: delete-torrents-with-sample-files
  enabled: true
  stop_on_match: true
  context: on_added
  conditions:
    any:
      - field: info.name
        operator: contains
        value: "sample"
      - field: files.name
        operator: contains
        value: "sample"
  actions:
    - type: delete_torrent
      params:
        delete_files: true
```

#### Filter by Size (v0.3.0+ Human-Readable Syntax)

```yaml
- id: remove-torrents-too-small
  enabled: true
  context: on_added
  conditions:
    all:
      - field: info.size
        operator: smaller_than
        value: "100MB"  # Human-readable size
      - field: info.category
        operator: "=="
        value: "Movies"
  actions:
    - type: delete_torrent
      params:
        delete_files: true

- id: tag-large-downloads
  enabled: true
  context: on_added
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "50GB"  # Supports KB, MB, GB, TB
  actions:
    - type: add_tag
      params:
        tags: ["large-download"]

- id: pause-huge-torrents-work-hours
  enabled: true
  context: manual
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "100GB"
      - field: info.state
        operator: "=="
        value: "downloading"
  actions:
    - type: stop
```

### 9.3 Tracker Management

#### Tag Private Trackers

```yaml
- id: tag-all-private-tracker-torrents
  enabled: true
  context: manual
  conditions:
    all:
      - field: trackers.url
        operator: not_contains
        value: "public"
  actions:
    - type: add_tag
      params:
        tags: ["private"]
```

#### Force Start on Specific Tracker

```yaml
- id: force-start-low-seeded-private
  enabled: true
  context: manual
  conditions:
    all:
      - field: trackers.url
        operator: contains
        value: "privatehd.to"
      - field: info.num_complete
        operator: "<"
        value: 3
  actions:
    - type: force_start
```

#### Reannounce Stalled Trackers

```yaml
- id: reannounce-tracker-errors
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: trackers.msg
        operator: not_contains
        value: "Working"
      - field: info.state
        operator: "=="
        value: "stalledUP"
  actions:
    - type: reannounce
```

### 9.4 Cleanup & Maintenance

#### Remove Old Completed Torrents

```yaml
- id: delete-old-completed-torrents
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: in
        value: ["uploading", "pausedUP", "stalledUP"]
      - field: info.completion_on
        operator: older_than
        value: "30 days"
      - field: info.ratio
        operator: ">="
        value: 1.0
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

#### Remove Stalled Downloads

```yaml
- id: delete-stalled-downloads-7d
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: "=="
        value: "stalledDL"
      - field: info.added_on
        operator: older_than
        value: "7 days"
  actions:
    - type: delete_torrent
      params:
        delete_files: true
```

#### Clean Up Errored Torrents

```yaml
- id: remove-errored-torrents
  enabled: true
  context: scheduled
  conditions:
    any:
      - field: info.state
        operator: "=="
        value: "error"
      - field: info.state
        operator: "=="
        value: "missingFiles"
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

### 9.5 Seeding Management

#### Pause Well-Seeded Torrents

```yaml
- id: pause-high-ratio-and-seeders
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
      - field: info.num_complete
        operator: ">"
        value: 10
      - field: info.state
        operator: "=="
        value: "uploading"
  actions:
    - type: stop
```

#### Start Underseded Torrents

```yaml
- id: force-start-low-seeder-torrents
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.num_complete
        operator: "<="
        value: 2
      - field: info.state
        operator: in
        value: ["pausedUP", "stalledUP"]
  actions:
    - type: force_start
```

#### Quota-Gated Seed Rotation

Reserve a share of your active-torrent budget for force-seeding under-ratio
private torrents, and release the slot once each torrent no longer needs it
— so force-starting doesn't just accumulate forever. Relies on
[`stats.tag.*`](Available-Fields#aggregate-statistics) staying live within a
run (v0.7.1+) so the budget check actually stops admitting new torrents once
full, instead of admitting every match in one pass — see
[`stats.*` Snapshot Semantics](Advanced-Topics#stats-snapshot-semantics).

```yaml
refs:
  vars:
    # Static, hand-synced with Session\MaxActiveTorrents in qBittorrent.conf
    private_seed_budget: 80   # e.g. 80% of MaxActiveTorrents=100

  conditions:
    under-private-seed-quota:
      all:
        - field: stats.tag.force-seeding
          operator: "<"
          value: ${vars.private_seed_budget}

    under-seeded-private:
      all:
        - field: info.tags
          operator: contains
          value: "private"
        - field: info.ratio
          operator: "<"
          value: 1.0

rules:
  - id: force-seed-under-ratio-private
    conditions:
      all:
        - $ref: conditions.under-seeded-private
        - $ref: conditions.under-private-seed-quota
    actions:
      - type: force_start
      - type: add_tag
        params:
          tags: [force-seeding]

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

The `force-seeding` tag doubles as both the admission marker and the budget
ledger — `stats.tag.force-seeding` is just "how many torrents currently hold
a slot," so no separate counter is needed. The same pattern works for any
other budget (e.g. reserving slots for active downloads): pick a tag, gate
the admitting rule's `force_start` on `stats.tag.<tag> < budget`, and pair it
with a release rule that removes the tag and calls `release_force_start`
once the torrent no longer needs priority.

#### Throttle Old Torrents

```yaml
- id: limit-upload-speed-old-torrents
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.completion_on
        operator: older_than
        value: "14 days"
      - field: info.ratio
        operator: ">="
        value: 1.5
  actions:
    - type: set_upload_limit
      params:
        limit: 524288  # 512 KB/s
```

### 9.6 Error Handling & Recovery

#### Recheck Missing Files

```yaml
- id: recheck-missing-files
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: "=="
        value: "missingFiles"
  actions:
    - type: recheck
```

#### Remove Errored Torrents After Retry

```yaml
- id: delete-permanently-errored
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: "=="
        value: "error"
      - field: info.added_on
        operator: older_than
        value: "3 days"
  actions:
    - type: delete_torrent
      params:
        delete_files: false
```

#### Auto-Resume Paused Downloads

```yaml
- id: resume-paused-with-activity
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: "=="
        value: "pausedDL"
      - field: info.availability
        operator: ">"
        value: 0.5
  actions:
    - type: start
```

### 9.7 Advanced Multi-Criteria Rules

#### Complex Download Management

```yaml
- id: manage-large-slow-downloads
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.size
        operator: larger_than
        value: "10GB"  # Human-readable size (v0.3.0+)
      - field: info.state
        operator: "=="
        value: "downloading"
      - field: info.dlspeed
        operator: "<"
        value: 102400  # < 100 KB/s (bytes)
      - field: info.added_on
        operator: newer_than
        value: "24 hours"  # < 1 day old
    none:
      - field: info.category
        operator: "=="
        value: "Priority"
  actions:
    - type: set_download_limit
      params:
        limit: 1048576  # 1 MB/s max (bytes/sec)
    - type: add_tag
      params:
        tags: ["throttled"]
```

#### Conditional Seeding Strategy

```yaml
- id: smart-seeding-ratio-and-time
  enabled: true
  context: on_completed
  conditions:
    any:
      # High ratio achieved
      - field: info.ratio
        operator: ">="
        value: 3.0
      # OR seeded for 30 days with ratio >= 1.0
      - all:
          - field: info.completion_on
            operator: older_than
            value: "30 days"
          - field: info.ratio
            operator: ">="
            value: 1.0
  actions:
    - type: stop
    - type: add_tag
      params:
        tags: ["seeding-complete"]
```

#### Private Tracker Automation

```yaml
- id: private-tracker-force-seed-low-seeded
  enabled: true
  context: on_completed
  conditions:
    all:
      - field: trackers.url
        operator: contains
        value: "passthepopcorn.me"
      - field: info.num_complete
        operator: "<="
        value: 5
  actions:
    - type: force_start
    - type: set_category
      params:
        category: "Private-Important"
    - type: add_tag
      params:
        tags: ["must-seed"]
    - type: set_upload_limit
      params:
        limit: -1  # Unlimited
```

#### Nested Conditions (Advanced Logic)

**New Feature:** Nest `all`, `any`, and `none` groups for complex boolean logic.

```yaml
# Complex cleanup rule with nested conditions
- id: smart-cleanup-old-or-well-seeded
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: in
        value: [uploading, stalledUP, pausedUP]
      - any:  # Nested: Either high ratio OR old with decent ratio
          - field: info.ratio
            operator: ">="
            value: 5.0
          - all:  # Nested level 2
              - field: info.completion_on
                operator: older_than
                value: "90 days"
              - field: info.ratio
                operator: ">="
                value: 1.5
  actions:
    - type: add_tag
      params:
        tags: ["cleanup-candidate"]
# Matches: seeding AND (ratio >= 5.0 OR (completed > 90 days AND ratio >= 1.5))
```

```yaml
# Tiered priority based on multiple factors
- id: priority-seeding-underseed-or-private
  enabled: true
  context: on_completed
  conditions:
    any:  # Top-level OR
      - all:  # Nested: Private tracker with low seeders
          - field: trackers.url
            operator: contains
            value: ".private"
          - field: info.num_complete
            operator: "<="
            value: 3
      - all:  # Nested: Public but very low seeders
          - field: trackers.url
            operator: not_contains
            value: ".private"
          - field: info.num_complete
            operator: "=="
            value: 1
  actions:
    - type: force_start
    - type: set_upload_limit
      params:
        limit: -1  # Unlimited
    - type: add_tag
      params:
        tags: ["priority-seed"]
# Matches: (private AND <= 3 seeders) OR (public AND only 1 seeder)
```

```yaml
# Exclude multiple categories with nested NONE
- id: apply-limits-except-important-categories
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.ratio
        operator: ">="
        value: 2.0
      - none:  # Nested: NOT in any important category
          - field: info.category
            operator: in
            value: [keep, seedbox, private-important]
          - field: info.tags
            operator: contains
            value: "must-seed"
  actions:
    - type: set_upload_limit
      params:
        limit: 524288  # 512 KB/s
# Matches: ratio >= 2.0 AND NOT (important category OR must-seed tag)
```

### 9.8 Advanced Field Usage

`peers.*` and `webseeds.*` are the two least-used collection fields — one API call per torrent, same as `trackers.*`/`files.*`, so put cheap `info.*` checks first to avoid paying that cost on torrents that were never going to match anyway. See [Available Fields](Available-Fields#peer-collection) for the full field list.

```yaml
# Force-start and prioritize torrents whose P2P swarm has gone quiet,
# but which can still make progress via an HTTP web seed
- id: fall-back-to-webseed-dead-swarm
  enabled: true
  context: hourly
  conditions:
    all:
      - field: info.state
        operator: in
        value: [stalledDL, downloading]
      - none:  # No connected peer is currently seeding
          - field: peers.progress
            operator: "=="
            value: 1.0
      - field: webseeds.url
        operator: contains
        value: ""  # At least one web seed configured
  actions:
    - type: force_start
    - type: add_tag
      params:
        tags: ["webseed-fallback"]
# Matches: stalled/downloading AND no seeding peer AND has a web seed
```

```yaml
# Flag torrents with a genuinely dead swarm (no peers, no web seed
# fallback either) for manual review rather than auto-deleting
- id: flag-dead-swarm-torrents-review
  enabled: true
  context: nightly
  conditions:
    all:
      - field: info.state
        operator: "=="
        value: stalledDL
      - field: info.added_on
        operator: older_than
        value: "3 days"
      - none:
          - field: peers.ip
            operator: matches
            value: '.*'
      - none:
          - field: webseeds.url
            operator: contains
            value: ""
  actions:
    - type: add_tag
      params:
        tags: ["dead-swarm", "needs-review"]
# Matches: stalled 3+ days AND zero connected peers AND zero web seeds
# (deliberately doesn't auto-delete — a human should confirm before
# giving up on a torrent that might just need a fresh magnet re-add)
```

### Scheduled Maintenance Examples

**Note:** Scheduling is controlled by cron (or a systemd timer), not by rules — the schedule submits a job with `context=scheduled` to the running server; see [Contexts](Contexts) for the full submission options.

```bash
# Daily cleanup at 3 AM
0 3 * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=scheduled"

# Weekly recheck on Sundays at 4 AM
0 4 * * 0 curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=scheduled"
```

```yaml
# Daily cleanup rule
- id: daily-cleanup-remove-completed
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: in
        value: ["pausedUP", "stalledUP"]
      - field: info.ratio
        operator: ">="
        value: 2.0
      - field: info.completion_on
        operator: older_than
        value: "7 days"
  actions:
    - type: delete_torrent
      params:
        delete_files: false

# Weekly integrity check
- id: weekly-integrity-check
  enabled: true
  context: scheduled
  conditions:
    all:
      - field: info.state
        operator: in
        value: ["uploading", "stalledUP"]
  actions:
    - type: recheck
```

### 9.9 Webhook Integration Example

```yaml
# Auto-categorize on add
- id: webhook-categorize-new-downloads
  enabled: true
  context: on_added
  conditions:
    any:
      - field: info.name
        operator: matches
        value: '(?i).*\.(mkv|mp4|avi)$'
      - field: files.name
        operator: matches
        value: '(?i).*\.(mkv|mp4|avi)$'
  actions:
    - type: set_category
      params:
        category: "Videos"
    - type: add_tag
      params:
        tags: ["auto-categorized"]

# Post-completion actions
- id: webhook-tag-completed-downloads
  enabled: true
  context: on_completed
  conditions:
    all:
      - field: info.ratio
        operator: "<"
        value: 1.0
  actions:
    - type: add_tag
      params:
        tags: ["needs-seeding"]
    - type: force_start
```
