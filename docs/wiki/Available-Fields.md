### Field Categories Overview

qbt-rules provides access to 10 field categories through dot notation: 9 from qBittorrent's API, plus optional tracker-side stats from trackie.

| Category | API Endpoint | API Calls | Cache Scope | Description |
|----------|--------------|-----------|-------------|-------------|
| `info.*` | /torrents/info | **Pre-loaded** (free) | Per execution | Core torrent data from main list |
| `trackers.*` | /torrents/trackers | 1 per torrent | Per execution | Tracker information (collection) |
| `files.*` | /torrents/files | 1 per torrent | Per execution | File list and details (collection) |
| `peers.*` | /sync/torrentPeers | 1 per torrent | Per execution | Connected peers (collection) |
| `properties.*` | /torrents/properties | 1 per torrent | Per execution | Extended torrent metadata |
| `webseeds.*` | /torrents/webseeds | 1 per torrent | Per execution | Web seed sources (collection) |
| `transfer.*` | /transfer/info | 1 total (global) | Per execution | Global transfer statistics |
| `app.*` | /app/preferences | 1 total (global) | Per execution | Application preferences |
| `stats.*` | *(derived, no call)* | **0** (computed from `info.*`) | Per run, live-updated as actions execute (`state`/`tag`/`category`/`total` only — see below) | Aggregate torrent counts/sums (state, category, tag, speeds, seeds/leechs) |
| `tracker.*` | trackie `/snapshot` *(optional, v0.8.0+)* | 1 total (global), only if a rule uses it | Per execution | Tracker-side seeding stats: H&R status, required seed time, tracker ratio, account ratio |

**Performance Notes:**

- **info.***: Already loaded, use freely
- **Per-torrent fields**: Cached after first use for that torrent
- **Global fields**: Cached after first use, shared across all torrents
- **Collection fields** (trackers, files, peers, webseeds): Return lists; positive operators check if ANY item matches, but negation operators (`!=`/`not_in`/`not_contains`) check if ALL items satisfy the negation — see [Conditions](Conditions#collection-field-behavior) for why

### Core Torrent Data

**No additional API calls required - already loaded.**

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `info.hash` | string | Torrent info hash (40-char hex) | `"8c9a6e4f3b2d1a..."` |
| `info.name` | string | Torrent name | `"Movie.2160p.BluRay"` |
| `info.state` | string | Current state — see full value list below | `downloading`, `stalledUP` |
| `info.category` | string | Category name | `"movies"`, `""` (empty) |
| `info.tags` | string† | Comma-separated tags | `"hd,private"`, `""` |
| `info.size` | integer | Total size in bytes | `1073741824` (1 GB) |
| `info.progress` | float | Download progress (0.0-1.0) | `0.75` (75%) |
| `info.dlspeed` | integer | Download speed (bytes/s) | `1048576` (1 MB/s) |
| `info.upspeed` | integer | Upload speed (bytes/s) | `524288` (512 KB/s) |
| `info.downloaded` | integer | Downloaded bytes | `1073741824` |
| `info.uploaded` | integer | Uploaded bytes | `2147483648` |
| `info.ratio` | float | Upload/download ratio | `2.0` |
| `info.dl_limit` | integer | Download limit (bytes/s, -1=unlimited) | `1048576`, `-1` |
| `info.up_limit` | integer | Upload limit (bytes/s, -1=unlimited) | `524288`, `-1` |
| `info.num_seeds` | integer | Connected seeds | `5` |
| `info.num_leechs` | integer | Connected leeches | `2` |
| `info.num_complete` | integer | Complete sources (from tracker) | `50` |
| `info.num_incomplete` | integer | Incomplete sources (from tracker) | `10` |
| `info.eta` | integer | Estimated time remaining (seconds) | `3600` (1 hour) |
| `info.seeding_time` | integer | Total seeding time (seconds) | `86400` (1 day) |
| `info.added_on` | integer | Unix timestamp when added | `1609459200` |
| `info.completion_on` | integer | Unix timestamp when completed | `1609545600`, `-1` (not completed) |
| `info.tracker` | string | Primary tracker URL | `"https://tracker.example.com"` |
| `info.save_path` | string | Save directory | `"/downloads/movies"` |
| `info.content_path` | string | Full path to content | `"/downloads/movies/Movie"` |
| `info.priority` | integer | Queue position (`-1` if qBittorrent's queueing feature is disabled; otherwise ascending, `1`=first to run) | `1`, `-1` |
| `info.auto_tmm` | boolean | Automatic Torrent Management enabled | `true`, `false` |
| `info.force_start` | boolean | Force start enabled | `true`, `false` |

† Despite the type, `info.tags` is parsed into a **list**, so it follows collection ANY/ALL rules, not string rules. `info.tags == ""` never matches — use `operator: not_contains, value: ""` to check for no tags.

**`info.state` values:**

| State | Meaning |
|-------|---------|
| `error` | Torrent has an error |
| `missingFiles` | Files missing on disk |
| `uploading` | Actively seeding |
| `pausedUP` | Paused, download complete |
| `queuedUP` | Queued to seed |
| `stalledUP` | Seeding, no upload activity |
| `checkingUP` | Verifying files, download complete |
| `forcedUP` | Force-seeding, bypassing queue |
| `allocating` | Allocating disk space |
| `downloading` | Actively downloading |
| `metaDL` | Fetching magnet metadata |
| `pausedDL` | Paused, download incomplete |
| `queuedDL` | Queued to download |
| `stalledDL` | Downloading, no peers/progress |
| `checkingDL` | Verifying files, download incomplete |
| `forcedDL` | Force-downloading, bypassing queue |
| `checkingResumeData` | Checking resume data on startup |
| `moving` | Moving files to a new location |
| `unknown` | State not recognized |

**Common Use Cases:**

```yaml
# By state
- field: info.state
  operator: ==
  value: stalledUP

# By name pattern
- field: info.name
  operator: matches
  value: '(?i).*(1080p|2160p).*'

# By category
- field: info.category
  operator: ==
  value: ""  # No category

# By ratio
- field: info.ratio
  operator: ">="
  value: 2.0

# By age
- field: info.added_on
  operator: older_than
  value: "30 days"

# By size (v0.3.0+ syntax)
- field: info.size
  operator: larger_than
  value: "10GB"

# By completion
- field: info.completion_on
  operator: "!="
  value: -1  # Has completed
```

### Tracker Collection

**One API call per torrent (cached after first use).**

**Collection:** Returns list of values. Positive operators check if **ANY** tracker matches; negation operators (`!=`/`not_in`/`not_contains`) check if **ALL** trackers satisfy the negation.

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `trackers.url` | string | Tracker announce URL | `"https://tracker.example.com/announce"` |
| `trackers.status` | integer | Tracker status code | `0`=disabled, `1`=not contacted, `2`=working, `3`=updating, `4`=not working |
| `trackers.tier` | integer | Tracker tier (failover priority) | `0`, `1`, `2`... |
| `trackers.num_peers` | integer | Peers reported by this tracker | `50` |
| `trackers.num_seeds` | integer | Seeds reported by this tracker | `30` |
| `trackers.num_leeches` | integer | Leeches reported by this tracker | `20` |
| `trackers.num_downloaded` | integer | Times downloaded (from tracker) | `1000` |
| `trackers.msg` | string | Tracker status message | `"Success"`, `"Unregistered"`, `"Not found"` |

**Collection Behavior:**

```yaml
# Returns TRUE if ANY tracker URL contains ".private"
- field: trackers.url
  operator: contains
  value: ".private"

# Returns TRUE if ANY tracker status is 4 (not working)
- field: trackers.status
  operator: ==
  value: 4

# Returns TRUE only if NO tracker URL contains ".private" (ALL must fail to match)
- field: trackers.url
  operator: not_contains
  value: ".private"
```

**Common Use Cases:**

```yaml
# Private tracker detection
- field: trackers.url
  operator: contains
  value: ".private"

# Specific tracker
- field: trackers.url
  operator: contains
  value: "tracker.example.com"

# Working trackers only
- field: trackers.status
  operator: ==
  value: 2

# Dead trackers
- field: trackers.status
  operator: in
  value: [0, 4]
```

### File Collection

**One API call per torrent (cached after first use).**

**Collection:** Returns list of values. Positive operators check if **ANY** file matches; negation operators (`!=`/`not_in`/`not_contains`) check if **ALL** files satisfy the negation.

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `files.name` | string | File path/name within torrent | `"Movie/movie.mkv"`, `"sample.avi"` |
| `files.size` | integer | File size in bytes | `1073741824` |
| `files.progress` | float | File download progress (0.0-1.0) | `0.95` |
| `files.priority` | integer | File priority (change it with [`set_file_priority`](Actions#set_file_priority)) | `0`=do not download, `1`=normal, `6`=high, `7`=maximum |
| `files.is_seed` | boolean | File is complete | `true`, `false` |
| `files.piece_range` | list[int] | Piece range [start, end] | `[0, 500]` |

**Collection Behavior:**

```yaml
# Returns TRUE if ANY file name ends with .rar
- field: files.name
  operator: matches
  value: '(?i)\.rar$'

# Returns TRUE if ANY file is larger than 10GB
- field: files.size
  operator: ">"
  value: 10737418240

# Returns TRUE only if NO file name ends with .rar (ALL must fail to match)
- field: files.name
  operator: not_contains
  value: ".rar"
```

**Common Use Cases:**

```yaml
# Block specific file extensions
- field: files.name
  operator: matches
  value: '(?i)\.(rar|zip|7z)$'

# Detect sample files
- field: files.name
  operator: contains
  value: "sample"

# Find large files
- field: files.size
  operator: ">"
  value: 5368709120  # > 5GB
```

### Peer Collection

**One API call per torrent (cached after first use)** — sourced from `/sync/torrentPeers`

**Collection:** Returns list of currently connected peers. Positive operators check if **ANY** peer matches; negation operators (`!=`/`not_in`/`not_contains`) check if **ALL** peers satisfy the negation. An empty list (no connected peers) fails every positive check.

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `peers.id` | string | Peer identifier (`ip:port`), added by qbt-rules for uniqueness | `"203.0.113.4:51413"` |
| `peers.ip` | string | Peer's IP address | `"203.0.113.4"` |
| `peers.port` | integer | Peer's port | `51413` |
| `peers.client` | string | Peer's reported client name/version | `"qBittorrent/4.6.0"`, `"Transmission/4.0"` |
| `peers.progress` | float | Peer's download progress (0.0–1.0; `1.0` = seed) | `1.0`, `0.42` |
| `peers.dl_speed` | integer | Download speed from this peer (bytes/s) | `524288` |
| `peers.up_speed` | integer | Upload speed to this peer (bytes/s) | `131072` |
| `peers.country` | string | Peer's country name | `"United States"` |
| `peers.connection` | string | Connection type | `"BT"`, `"uTP"`, `"Web"` |

**Collection Behavior:**

```yaml
# Returns TRUE if ANY connected peer is a seed (has 100% of the torrent)
- field: peers.progress
  operator: "=="
  value: 1.0
```

```yaml
# Returns TRUE only if NO connected peer is a seed — wrap a positive
# check in `none:` rather than trying a numeric not_contains
conditions:
  none:
    - field: peers.progress
      operator: "=="
      value: 1.0
```

**Common Use Cases:**

```yaml
# Detect a torrent with no connected peers at all
# (an empty peers.* collection fails every positive check automatically)
- field: peers.ip
  operator: matches
  value: '.*'
```

**Tip:** If you only need a peer/seed *count* rather than per-peer detail (client, progress, country...), `properties.seeds` and `properties.peers` give you that as plain integers for the cost of the same one API call — no need to fetch and iterate the full peer list.

### Extended Properties

**One API call per torrent (cached after first use).**

Contains extended metadata not available in `info.*`.

| Field | Type | Description |
|-------|------|-------------|
| `properties.save_path` | string | Save directory path |
| `properties.creation_date` | integer | Torrent creation timestamp |
| `properties.piece_size` | integer | Piece size in bytes |
| `properties.comment` | string | Torrent comment field |
| `properties.total_wasted` | integer | Wasted bytes (hash fails) |
| `properties.total_uploaded` | integer | Total uploaded bytes |
| `properties.total_downloaded` | integer | Total downloaded bytes |
| `properties.up_limit` | integer | Upload limit (bytes/s) |
| `properties.dl_limit` | integer | Download limit (bytes/s) |
| `properties.time_elapsed` | integer | Active time (seconds) |
| `properties.seeding_time` | integer | Seeding time (seconds) |
| `properties.nb_connections` | integer | Current connections |
| `properties.nb_connections_limit` | integer | Connection limit |
| `properties.share_ratio` | float | Share ratio |
| `properties.addition_date` | integer | Date added timestamp |
| `properties.completion_date` | integer | Date completed timestamp |
| `properties.created_by` | string | Torrent creator string |
| `properties.dl_speed_avg` | integer | Average download speed |
| `properties.dl_speed` | integer | Current download speed |
| `properties.eta` | integer | ETA in seconds |
| `properties.last_seen` | integer | Last seen complete timestamp |
| `properties.peers` | integer | Connected peers |
| `properties.peers_total` | integer | Total peers in swarm |
| `properties.pieces_have` | integer | Pieces downloaded |
| `properties.pieces_num` | integer | Total pieces |
| `properties.reannounce` | integer | Seconds until next reannounce |
| `properties.seeds` | integer | Connected seeds |
| `properties.seeds_total` | integer | Total seeds in swarm |
| `properties.total_size` | integer | Total size in bytes |
| `properties.up_speed_avg` | integer | Average upload speed |
| `properties.up_speed` | integer | Current upload speed |

**Note:** Most data overlaps with `info.*`. Use `properties.*` only when you need fields not available in `info.*`.

### Web Seed Collection

**One API call per torrent (cached after first use)** — sourced from `/torrents/webseeds`

**Collection:** Returns list of HTTP/FTP web seed sources configured on the torrent (a BEP 19 feature — not every torrent has any). Most torrents have zero web seeds, so this list is often empty.

| Field | Type | Description | Example Values |
|-------|------|-------------|----------------|
| `webseeds.url` | string | Web seed source URL | `"https://example.com/files/movie.mkv"` |

**Collection Behavior:**

```yaml
# Returns TRUE if the torrent has at least one web seed at all
# (an empty webseeds.* collection fails every positive check automatically,
# so checking for *any* value works as an existence check)
- field: webseeds.url
  operator: contains
  value: ""
```

**Common Use Cases:**

```yaml
# Identify torrents backed by a specific web seed host
- field: webseeds.url
  operator: contains
  value: "example.com"
```

### Global Transfer Info

**Single API call per execution (cached, shared across all torrents).**

Global transfer statistics for the entire qBittorrent instance.

| Field | Type | Description |
|-------|------|-------------|
| `transfer.dl_info_speed` | integer | Global download speed (bytes/s) |
| `transfer.up_info_speed` | integer | Global upload speed (bytes/s) |
| `transfer.dl_info_data` | integer | Session downloaded bytes |
| `transfer.up_info_data` | integer | Session uploaded bytes |
| `transfer.connection_status` | string | Connection status: `"connected"`, `"firewalled"`, `"disconnected"` |
| `transfer.dht_nodes` | integer | DHT nodes connected |

**Use Cases:**

```yaml
# Pause torrents if global speed maxed
- field: transfer.dl_info_speed
  operator: ">"
  value: 10485760  # > 10 MB/s

# Check connection before operations
- field: transfer.connection_status
  operator: ==
  value: "connected"
```

### Application Preferences

**Single API call per execution (cached, shared across all torrents).**

qBittorrent application settings.

| Field | Type | Description |
|-------|------|-------------|
| `app.save_path` | string | Default save path |
| `app.temp_path` | string | Temp path for incomplete downloads |
| `app.temp_path_enabled` | boolean | Use temp path |
| `app.max_active_downloads` | integer | Max active downloads |
| `app.max_active_torrents` | integer | Max active torrents |
| `app.max_active_uploads` | integer | Max active uploads |
| `app.dl_limit` | integer | Global download limit (bytes/s, -1=unlimited) |
| `app.up_limit` | integer | Global upload limit (bytes/s, -1=unlimited) |
| `app.max_connec` | integer | Max global connections |
| `app.max_connec_per_torrent` | integer | Max connections per torrent |
| `app.dht` | boolean | DHT enabled |
| `app.pex` | boolean | Peer Exchange enabled |
| `app.lsd` | boolean | Local Service Discovery enabled |
| `app.encryption` | integer | Encryption: `0`=prefer unencrypted, `1`=prefer encrypted, `2`=require encrypted |
| `app.proxy_type` | integer | Proxy type: `-1`=none, `1`=HTTP, `2`=SOCKS5 |
| `app.queueing_enabled` | boolean | Queueing system enabled |
| `app.autorun_enabled` | boolean | Run external program on completion |
| `app.autorun_program` | string | External program path |

**Use Cases:**

```yaml
# Check encryption requirement
- field: app.encryption
  operator: ==
  value: 2  # Require encrypted

# Verify queueing enabled
- field: app.queueing_enabled
  operator: ==
  value: true
```

### Aggregate Statistics

**Zero API calls — computed once per run from the already-fetched torrent list, then kept live as actions execute.**

Unlike every other namespace, `stats.*` isn't a 1:1 mirror of a qBittorrent API
endpoint. It's built in-process over all torrents the engine already fetched
at the start of the run, so it costs nothing extra. `stats.state.*`/
`stats.tag.*` (and `stats.total`/`stats.category.*` on deletion) update live
as rules act on torrents within the same run — see
[Advanced-Topics](Advanced-Topics#stats-snapshot-semantics) for exactly what
that does and doesn't cover.

| Field | Type | Description | Example Values |
|-------|------|--------------|-----------------|
| `stats.total` | integer | Total torrent count for this run | `142` |
| `stats.state.<state>` | integer | Torrents currently in `<state>` (any [`info.state`](#core-torrent-data) value) | `stats.state.queuedUP` → `12` |
| `stats.category.<category>` | integer | Torrents currently in category `<category>` | `stats.category.movies` → `37` |
| `stats.tag.<tag>` | integer | Torrents carrying tag `<tag>` (a torrent with multiple tags counts toward each) | `stats.tag.private` → `28` |
| `stats.dlspeed` | integer | Sum of `info.dlspeed` across all torrents (bytes/s) | `10485760` (10 MB/s) |
| `stats.upspeed` | integer | Sum of `info.upspeed` across all torrents (bytes/s) | `2097152` (2 MB/s) |
| `stats.seeds` | integer | Sum of `info.num_seeds` (connected seeds) across all torrents | `340` |
| `stats.leechs` | integer | Sum of `info.num_leechs` (connected leechers) across all torrents | `58` |

**Missing keys default to `0`, not an error.** `stats.state.forcedUP`
resolves to `0` when nothing is currently `forcedUP` — it's never `None` or a
`FieldError` — so it works directly with the existing numeric operators
(`<`, `>=`, `==`, etc.) with no extra null-handling in your condition.
Torrents with no category (`info.category == ""`) are excluded from
`stats.category` entirely (there is no `stats.category.` key for the empty
string) — use `stats.total` minus the sum of your known categories if you
need that count. Likewise, a torrent with no tags contributes nothing to
`stats.tag`.

`stats.tag.*` costs nothing extra either, despite counting a collection
field: qBittorrent already returns each torrent's tags as a comma-separated
string on the same `/torrents/info` response `info.*`/`stats.state`/
`stats.category` read from, so it's parsed (via the same helper `info.tags`
uses) and tallied in the same in-memory pass — no per-torrent API call like
`trackers.*`/`files.*` require.

`stats.dlspeed`/`stats.upspeed`/`stats.seeds`/`stats.leechs` are also free
for the same reason — they're plain sums over fields already present on
each torrent from the initial fetch, not a new API call. They are **not**
the same figures as `transfer.dl_info_speed`/`transfer.up_info_speed`:
those come from qBittorrent's own global transfer counters (which include
protocol overhead and DHT/PeX/LSD traffic), while `stats.*` only totals
the torrents this run actually evaluated.

**Naming note:** `stats.seeds`/`stats.leechs` are named after the
underlying qBittorrent API fields they sum (`info.num_seeds`/
`info.num_leechs`), not the qBittorrent Web UI's "Seeds"/"Peers" column
labels. This is deliberate — `properties.peers` is a *different* concept
(total connected peers on a single torrent, from `/torrents/properties`),
so naming this field `stats.peers` would have made it easy to mistake for
a fleet-wide sum of that instead of what it actually sums, `num_leechs`.

**Use Cases:**

```yaml
# Cap how many torrents can be actively uploading at once
- field: stats.state.uploading
  operator: "<"
  value: 5

# Only run a rule when nothing at all is queued to download
- field: stats.state.queuedDL
  operator: ==
  value: 0

# Skip a rule once too many torrents already carry a given tag
- field: stats.tag.manual-review
  operator: "<"
  value: 10

# Pause new downloads once combined download speed is already saturated
- field: stats.dlspeed
  operator: ">"
  value: 52428800  # > 50 MB/s

# Reference the fleet-wide count in a notify message
# (works the same as ${info.*}/${trackers.*} templating)
- type: notify
  params:
    message: "${stats.state.queuedUP} torrents queued to seed (${stats.total} total)"
```

### Tracker Seeding Stats (trackie)

**Requires [trackie](https://github.com/andronics/trackie) and `integrations.trackie.url` (v0.8.0+). One request per execution, shared across all torrents, and only made if a rule uses a `tracker.*` field.**

qBittorrent's ratio and seeding time aren't what a private tracker judges you on. trackie reads each tracker's own Peers and Hit & Run pages, matches every entry to its info hash, and serves the result; `tracker.*` exposes it. qbt-rules has no tracker-specific knowledge: it looks torrents up by hash.

**Fail-safe:** if trackie is unreachable, its data for that tracker is older than `integrations.trackie.max_age`, or the torrent has no record (e.g. a public torrent), the field is **not ready** and the rule is skipped for that torrent on that run, like `files.*` before metadata loads. It never evaluates as false, so a `none:` group can't match by accident and a delete rule can't fire because trackie was down. Using `tracker.*` without `url` set, or an unknown field name, is a configuration error.

**Torrent fields** (from the torrent's own record):

| Field | Type | Description |
|-------|------|-------------|
| `tracker.status` | string | `required` (seed time still owed), `satisfied`, or `hnr` (listed as a Hit & Run) |
| `tracker.remaining` | integer | Seconds of seeding still owed; `null` once met |
| `tracker.seed_time` | integer | Seconds seeded, once the requirement is met |
| `tracker.uploaded` / `tracker.downloaded` | integer | Bytes, as the tracker counts them |
| `tracker.ratio` | float | Tracker-side ratio for this torrent |
| `tracker.gap` | integer | H&R only: bytes still needed to reach 1:1 |
| `tracker.hnr_seed_time` | integer | H&R only: seconds seeded toward clearing it |
| `tracker.on_peers` / `tracker.on_hnr` | boolean | Which tracker page(s) list it |
| `tracker.name` / `tracker.id` | string | The tracker's name and ID for the torrent |
| `tracker.tracker` | string | Which tracker, as trackie names it (e.g. `ipt`, `td`) |
| `tracker.match` | string | How the hash was matched: `exact` or `fuzzy` |
| `tracker.match_source` | string | What made the match (e.g. `sonarr`, `prowlarr`, `name+size`) |
| `tracker.age` | integer | Seconds since this record's page was fetched |

**Account fields** (for whichever tracker the torrent is on, found from its record, or else from its tracker URLs, so they work for torrents trackie hasn't matched):

| Field | Type | Description |
|-------|------|-------------|
| `tracker.account.ratio` / `.min_ratio` | float | Account ratio and the site's minimum |
| `tracker.account.ratio_ok` | boolean | `ratio >= min_ratio` |
| `tracker.account.hnr_count` / `.hnr_limit` | integer | Current Hit & Runs and the site's limit |
| `tracker.account.hnr_grace` | integer | Seconds of H&R grace period |
| `tracker.account.uploaded` / `.downloaded` | integer | Account totals in bytes |
| `tracker.account.bonus` | float | Bonus points |
| `tracker.account.seeding` / `.leeching` | integer | The site's active counts |
| `tracker.account.age` | integer | Seconds since the account data was read |

Durations are plain seconds: compare them with numeric operators. `older_than`/`newer_than` take timestamps, not durations. Full field semantics are on trackie's [Using with qbt-rules](https://github.com/andronics/trackie/wiki/Using-with-qbt-rules) page.

**Use Cases:**

```yaml
# Only delete what the tracker itself says is done, on an exact hash match
- field: tracker.status
  operator: ==
  value: satisfied
- field: tracker.match
  operator: ==
  value: exact

# Less than a day of required seeding left
- field: tracker.remaining
  operator: "<="
  value: 86400

# Account under the site's minimum ratio
- field: tracker.account.ratio_ok
  operator: ==
  value: false

# Notify once per Hit & Run (tag-gated so it doesn't repeat every run)
- id: notify-tracker-hnr
  context: [hourly]
  conditions:
    all:
      - field: tracker.status
        operator: ==
        value: hnr
      - field: info.tags
        operator: not_contains
        value: "trackie-hnr"
  actions:
    - type: notify
      params:
        message: "H&R on ${tracker.tracker}: ${info.name} (tracker ratio ${tracker.ratio})"
    - type: add_tag
      params:
        tags: [trackie-hnr]
```
