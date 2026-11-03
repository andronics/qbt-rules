### Performance Optimization

#### Field Access Optimization

The system caches API responses per-torrent to minimize calls:

```python
# First access to trackers.url: API call made and cached
if torrent["trackers.url"] contains "example.com":
    ...

# Second access to trackers.url: Uses cached data (no API call)
if torrent["trackers.url"] contains "private":
    ...
```

**Best practices:**

1. **Access fields in order of expense:**

   ```yaml
   # Check cheap fields first
   all:
     - field: info.category    # Free
       operator: "=="
       value: "Movies"
     - field: files.name        # Expensive, but only if category matches
       operator: matches
       value: '.*\.mkv$'
   ```

2. **Reuse field references:**

   ```yaml
   # BAD: Multiple string operations
   any:
     - field: info.name
       operator: contains
       value: "1080p"
     - field: info.name
       operator: contains
       value: "2160p"

   # GOOD: Single regex
   any:
     - field: info.name
       operator: matches
       value: '(?i).*(1080p|2160p).*'
   ```

#### `stats.*` Snapshot Semantics

`stats.*` ([Available-Fields](Available-Fields#aggregate-statistics)) isn't
cached the way `trackers.*`/`transfer.*`/etc are — there's no API call to
cache in the first place. It's built once, in-process (`Counter`s for
`state`/`category`/`tag`, plain sums for `dlspeed`/`upspeed`/`seeds`/`leechs`),
from the same torrent list the engine already fetched to know what to
iterate over.

**As of v0.7.1**, that initial snapshot is kept live for the rest of the run:
after each successful, non-skipped action, the engine diffs the acted-on
torrent's `state`/`tags` before and after and adjusts `stats.state.*`/
`stats.tag.*` (and `stats.total`/`stats.category.*` on deletion) accordingly
— no extra API call, since the diff is computed from the same per-torrent
refresh the engine already does after every action. So if an earlier rule in
the same run force-starts a queued torrent, `stats.state.queuedDL` for a
*later* rule's condition in that same run **does** reflect that change — the
torrent has already been moved out of the `queuedDL` count and into whatever
state `force_start` put it in. The same applies to `stats.category.*` and
`stats.tag.*` after `set_category`/`add_tag`/`remove_tag`.

This live-updating is what makes budget-style conditions correct rather than
approximate — a condition like `stats.tag.force-seeding < 80` can gate a
`force_start` rule and actually stop admitting torrents once the budget is
full mid-run, instead of every remaining match in that run passing the same
stale count. See [Quota-Gated Seed Rotation](Examples#quota-gated-seed-rotation)
for the full pattern, and [`release_force_start`](Actions#release_force_start)
for handing a slot back once it's no longer needed.

`stats.dlspeed`/`stats.upspeed`/`stats.seeds`/`stats.leechs` are **not**
live-updated the same way — those are plain sums over `info.dlspeed`/
`info.upspeed`/`info.num_seeds`/`info.num_leechs`, which qBittorrent itself
only updates on its own polling interval, not synchronously in response to
an action. Treat those four as accurate as of the run's initial torrent
fetch, same as before v0.7.1.

Across separate runs, `stats.*` is always rebuilt from scratch at the start
of that run's torrent fetch, regardless of any live updates from a previous
run.

#### Rule Ordering

Rules execute top-to-bottom. Order matters for performance:

```yaml
# GOOD: Specific rules first, then general
- id: high-priority-private-trackers
  stop_on_match: true
  conditions:
    all:
      - field: trackers.url
        operator: contains
        value: "privatehd.to"

- id: general-cleanup
  conditions:
    # This only runs if private tracker rule didn't match
```

Credential management, network exposure, and content-safety rules have moved to their own page — see [Security](Security).

### Integration Patterns

#### Integration with Sonarr/Radarr

This section covers auto-*categorizing* torrents Sonarr/Radarr already added — a different capability from replacing a bad download. If a rule detects a torrent is bad (fake, wrong content, stalled) and you want Sonarr/Radarr to blocklist it and search for a replacement, use the [`arr_blocklist`](Actions#arr_blocklist) action instead — it correlates via the arr's own download queue, not category.

**Scenario:** Auto-categorize torrents added by Sonarr/Radarr

1. **Configure qBittorrent webhook:**
   - Open qBittorrent → Tools → Options → Downloads
   - Set "Run external program on torrent added" to hit the server's HTTP API directly (fastest, no CLI process spawn):

   ```bash
   curl -X POST "http://qbt-rules:5000/api/execute?context=on_added&hash=%I&key=YOUR_API_KEY"
   ```

   Or, if you'd rather use the CLI client from inside the server's container:

   ```bash
   docker exec qbt-rules qbt-rules --context on_added --hash "%I" --wait
   ```

2. **Create categorization rules:**

   ```yaml
   - id: categorize-sonarr-downloads
     context: on_added
     conditions:
       all:
         - field: info.category
           operator: "=="
           value: "tv-sonarr"
     actions:
       - type: add_tag
         params:
           tags: ["sonarr"]
   ```

#### Integration with External Scripts

**Scenario:** Run custom script after specific condition

While the system doesn't directly support script execution, you can:

1. **Tag torrents** with automation rules
2. **Monitor tags** with external script:

   ```bash
   #!/bin/bash
   # Watch for "process-me" tag
   TAGGED=$(curl -s http://localhost:8080/api/v2/torrents/info | \
     jq -r '.[] | select(.tags | contains("process-me")) | .hash')

   for hash in $TAGGED; do
     # Run your custom logic
     ./process-torrent.sh "$hash"
   done
   ```

#### Integration with Notification Services

**Scenario:** Send notifications when rules match

Use the built-in [`notify`](Actions#notify) action — Discord, Slack, ntfy, and a generic JSON webhook escape hatch are all supported without any code changes:

```yaml
actions:
  - type: notify
    params:
      service: ntfy
      url: "https://ntfy.sh/qbittorrent"
      message: "Torrent {name} completed!"
```

If you need a service `notify` doesn't cover natively, `service: generic` with a manually-built `body:` handles most webhook-shaped APIs without writing any Python — see [Actions](Actions#notify) for the full parameter reference and the duplicate-notification caveat (it fires every time a rule matches, with no built-in "already notified" tracking). Adding custom operators or actions the engine has no equivalent for at all has moved to [Extending the Engine](Extending-the-Engine). For scheduling jobs against arbitrary context names — no code changes needed, since contexts are already free-form — see [Contexts](Contexts).

### Scaling Strategies

There's one server per qBittorrent instance — you don't run multiple standalone "instances" the way older, pre-v0.4.0 versions worked. Everything below scales *within* that single client-server deployment.

#### Concurrent Job Processing

Jobs are queued (SQLite or Redis, see [In-Depth Configuration](In-Depth-Configuration)) and run one at a time by the server's single worker thread. The server is one process: there is no worker count to raise (`server.workers` must be `1`), and a second server against the same qBittorrent would fire every scheduled job twice.

Multiple submitters (webhooks firing rapidly, a cron sweep, a manual run) are safe to fire concurrently — they all land in the same queue and get worked off in order. For genuinely high torrent counts, switching `queue.backend` from `sqlite` to `redis` reduces lock contention under heavy concurrent submission.

**Separating workloads by context** still makes sense — just point every submitter at the same server:

```bash
# Frequent, single-torrent categorization (webhook, not cron)
curl -X POST "http://qbt-rules:5000/api/execute?context=on_added&hash=%I&key=YOUR_KEY"

# Daily cleanup sweep across the whole library
0 3 * * * curl -s -X POST -H "X-API-KEY: $QBT_RULES_API_KEY" "http://qbt-rules:5000/api/execute?context=cleanup"
```

#### Large Libraries

For very large torrent libraries (10,000+), there's no manual batching to configure — the engine already evaluates torrents one at a time against the rule set and issues qBittorrent API calls per-torrent, so memory use stays flat regardless of library size. The practical levers if a sweep is taking too long are:

- Order conditions cheap-first within `all:` blocks so expensive fields (`files.*`, `peers.*`) are only checked once cheap fields (`info.category`, `info.state`) have already narrowed the match (see [Performance Optimization](#performance-optimization) above).
- Scope webhook-triggered jobs to a single torrent with `&hash=%I` instead of re-evaluating the whole library on every event.
- Scope cron sweeps by context, so a big cleanup doesn't hold up the webhook jobs queued behind it.
