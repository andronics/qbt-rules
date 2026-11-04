Conditions determine which torrents match a rule. Three logical groups are available: `all`, `any`, and `none`.

If you find yourself writing the same condition block into multiple rules, see [Reusable References](Reusable-References) — you can define it once under `refs.conditions` and pull it in anywhere with `$ref: conditions.name`.

### Overview

**Condition Groups:**

| Group | Logic | Description | Use When |
|-------|-------|-------------|----------|
| `all` | AND | Every condition must be true | Need multiple criteria simultaneously |
| `any` | OR | At least one condition must be true | Match alternatives or broad filtering |
| `none` | NOT | No conditions can be true | Exclusions or inverse matching |

**Combining Groups:**

- All three groups can be used together
- **All groups must pass** for the rule to match
- Empty/missing groups are ignored (treated as pass)
- The same holds for a nested group, or a `$ref` to a named condition, that has more than one of `all`/`any`/`none`: all of them must pass (before 0.11.3 only the first was checked below the top level)

### ALL Conditions (AND Logic)

**Description:** Every condition in the `all` list must be true for the group to pass.

**Structure:**

```yaml
conditions:
  all:
    - field: info.name
      operator: contains
      value: "1080p"
    - field: info.category
      operator: ==
      value: ""
    - field: info.size
      operator: ">"
      value: 1073741824
# ALL three must be true: name has "1080p" AND no category AND size > 1GB
```

**Use Cases:**

- **Narrow down matches** - Require multiple criteria
- **Precise filtering** - All conditions must align
- **Most common pattern** - Default choice for most rules

**Examples:**

```yaml
# HD movies without category
conditions:
  all:
    - field: info.name
      operator: matches
      value: '(?i).*(1080p|2160p).*'
    - field: info.category
      operator: ==
      value: ""
```

```yaml
# Private tracker torrents over 2.0 ratio
conditions:
  all:
    - field: info.ratio
      operator: ">="
      value: 2.0
    - field: trackers.url
      operator: contains
      value: ".private"
```

```yaml
# Old completed torrents not in keep category
conditions:
  all:
    - field: info.completion_on
      operator: older_than
      value: 30 days
    - field: info.ratio
      operator: ">="
      value: 1.0
    - field: info.category
      operator: "!="
      value: keep
```

### ANY Conditions (OR Logic)

**Description:** At least one condition in the `any` list must be true for the group to pass.

**Structure:**

```yaml
conditions:
  any:
    - field: info.state
      operator: ==
      value: error
    - field: info.state
      operator: ==
      value: missingFiles
    - field: info.state
      operator: ==
      value: stalledDL
# ANY one must be true: state=error OR state=missingFiles OR state=stalledDL
```

**Use Cases:**

- **Match alternatives** - Multiple acceptable patterns
- **Broad filtering** - "Either this OR that"
- **List of exceptions** - Match any of several values

**Examples:**

```yaml
# Remove torrents in error states
conditions:
  any:
    - field: info.state
      operator: ==
      value: error
    - field: info.state
      operator: ==
      value: missingFiles
```

```yaml
# Match either 1080p or 2160p resolution
conditions:
  any:
    - field: info.name
      operator: contains
      value: "1080p"
    - field: info.name
      operator: contains
      value: "2160p"
```

```yaml
# Block multiple file extensions
conditions:
  any:
    - field: files.name
      operator: matches
      value: '(?i)\.rar$'
    - field: files.name
      operator: matches
      value: '(?i)\.zip$'
    - field: files.name
      operator: matches
      value: '(?i)\.7z$'
```

**Tip:** For list matching, use `in` operator instead:

```yaml
# Simpler alternative to above
conditions:
  any:
    - field: info.state
      operator: in
      value: [error, missingFiles, stalledDL]
```

### NONE Conditions (NOT Logic)

**Description:** No conditions in the `none` list can be true for the group to pass.

**Structure:**

```yaml
conditions:
  none:
    - field: info.category
      operator: in
      value: [keep, seedbox]
    - field: info.tags
      operator: contains
      value: "permanent"
# NONE can be true: NOT (category in [keep, seedbox]) AND NOT (has "permanent" tag)
```

**Use Cases:**

- **Exclusions** - Exclude specific cases
- **Inverse filtering** - "Everything except..."
- **"Unless" clauses** - Do action unless condition is true

**Examples:**

```yaml
# Delete old torrents NOT in keep category
conditions:
  all:
    - field: info.completion_on
      operator: older_than
      value: 30 days
  none:
    - field: info.category
      operator: ==
      value: keep
```

```yaml
# Apply limits EXCEPT to private trackers
conditions:
  all:
    - field: info.ratio
      operator: ">="
      value: 2.0
  none:
    - field: trackers.url
      operator: contains
      value: ".private"
```

```yaml
# Stop seeding UNLESS in seedbox category
conditions:
  all:
    - field: info.ratio
      operator: ">="
      value: 3.0
    - field: info.seeding_time
      operator: ">"
      value: 2592000  # 30 days
  none:
    - field: info.category
      operator: ==
      value: seedbox
```

### Combining Condition Groups

You can use multiple groups together. **All groups must pass** for the rule to match.

#### Pattern 1: all + none ("Match these, except...")

```yaml
conditions:
  all:
    - field: info.ratio
      operator: ">="
      value: 2.0
    - field: info.completion_on
      operator: older_than
      value: 7 days
  none:
    - field: info.category
      operator: in
      value: [keep, seedbox, long-term]
# Match: ratio >= 2.0 AND completed > 7 days ago
# Except: NOT in categories keep/seedbox/long-term
```

#### Pattern 2: any + all ("Match any of these, but also require...")

```yaml
conditions:
  any:
    - field: info.name
      operator: contains
      value: "1080p"
    - field: info.name
      operator: contains
      value: "2160p"
  all:
    - field: info.size
      operator: ">"
      value: 5368709120  # > 5GB
    - field: info.category
      operator: ==
      value: ""
# Match: (1080p OR 2160p) AND size > 5GB AND no category
```

#### Pattern 3: all + any + none (Complex filtering)

```yaml
conditions:
  all:
    - field: info.completion_on
      operator: older_than
      value: 14 days
  any:
    - field: info.ratio
      operator: ">="
      value: 3.0
    - field: info.num_leechs
      operator: ==
      value: 0
  none:
    - field: info.category
      operator: in
      value: [seedbox, permanent]
    - field: trackers.url
      operator: contains
      value: ".private"
# Match: completed > 14 days ago
#    AND (ratio >= 3.0 OR no leeches)
#    AND NOT (in seedbox/permanent categories)
#    AND NOT (private tracker)
```

### Nested Conditions (Advanced)

**New Feature:** You can nest `all`, `any`, and `none` groups inside each other for complex logical expressions.

**How It Works:**

- Instead of a field condition, provide another group (`all`, `any`, or `none`)
- Nesting can be multiple levels deep
- Useful for expressing complex boolean logic

A `$ref` item stands alone: a group or a field condition written beside it is ignored, because the reference replaces the whole item. Make them separate items of the list:

```yaml
all:
  - $ref: conditions.public          # one item
  - any:                             # another item, not under the $ref
      - {field: info.ratio, operator: '>=', value: 2.0}
      - {field: info.seeding_time, operator: '>=', value: 604800}
```

`qbt-rules validate` and the rules editor report the other shape as an error; see [Reusable References](Reusable-References#a-ref-stands-alone).

#### Pattern 1: Nested ANY inside ALL

```yaml
conditions:
  all:
    - field: info.state
      operator: in
      value: [uploading, stalledUP, pausedUP]
    - any:  # Nested any group
        - field: info.ratio
          operator: ">="
          value: 5.0
        - field: info.completion_on
          operator: older_than
          value: "90 days"
# Match: (state is uploading/stalledUP/pausedUP) AND (ratio >= 5.0 OR completed > 90 days ago)
```

#### Pattern 2: Nested ALL inside ANY

```yaml
conditions:
  any:
    - all:  # Nested all group
        - field: info.ratio
          operator: ">="
          value: 1.0
        - field: info.state
          operator: "=="
          value: uploading
    - field: info.ratio
      operator: "<"
      value: 0.1
# Match: ((ratio >= 1.0 AND state = uploading) OR ratio < 0.1)
```

#### Pattern 3: Nested NONE inside ALL

```yaml
conditions:
  all:
    - field: info.size
      operator: larger_than
      value: "10GB"
    - none:  # Nested none group
        - field: info.category
          operator: in
          value: [keep, seedbox]
        - field: trackers.url
          operator: contains
          value: ".private"
# Match: size > 10GB AND NOT (in keep/seedbox OR private tracker)
```

#### Pattern 4: Multiple Nesting Levels

```yaml
conditions:
  all:
    - field: info.state
      operator: "=="
      value: uploading
    - any:  # Level 1 nesting
        - field: info.ratio
          operator: ">="
          value: 3.0
        - all:  # Level 2 nesting
            - field: info.completion_on
              operator: older_than
              value: "30 days"
            - none:  # Level 3 nesting
                - field: info.category
                  operator: "=="
                  value: keep
# Match: state = uploading AND (ratio >= 3.0 OR (completed > 30 days AND NOT keep category))
```

**Use Cases:**

- **Complex cleanup rules** - Multiple criteria with fallbacks
- **Conditional seeding** - Different strategies based on tracker type
- **Priority management** - Tiered priority based on multiple factors
- **Smart categorization** - Category selection with multiple decision paths

**Performance Note:** Nested conditions are evaluated depth-first. Place cheaper conditions (e.g., `info.*` fields) at outer levels when possible.

### Fleet-Wide Conditions with `stats.*`

Every field seen so far is scoped to the single torrent a rule is currently
evaluating. `stats.*` ([Available-Fields](Available-Fields#aggregate-statistics))
is the exception — it's an aggregate count across **all** torrents for this
run, so a condition can gate on "how many torrents are already in state X"
rather than only on the current torrent's own state.

#### Example: force-start queued public torrents, capped at N concurrently uploading

```yaml
conditions:
  all:
    - field: info.state
      operator: "=="
      value: queuedUP
    - field: trackers.url
      operator: not_contains
      value: ".private"
    - any:
        - field: stats.state.uploading
          operator: "<"
          value: 5
        - field: stats.state.forcedUP
          operator: "<"
          value: 5
actions:
  - type: force_start
# Match: torrent is queued to seed, isn't on a private tracker, and fewer
# than 5 torrents are already uploading/forcedUP fleet-wide
```

Without `stats.*` there's no way to express the count-based guard — every
other namespace only ever sees the one torrent being evaluated.

`stats.tag.<tag>` works the same way for tag-based caps:

```yaml
# Only auto-tag a torrent for manual review if fewer than 10 are already
# waiting on one
- field: stats.tag.manual-review
  operator: "<"
  value: 10
```

`stats.dlspeed`/`stats.upspeed`/`stats.seeds`/`stats.leechs` swap a count for
a sum, for throughput-based guards instead of state/category/tag caps:

```yaml
# Don't force-start anything new once combined upload is already saturated
conditions:
  all:
    - field: info.state
      operator: "=="
      value: queuedUP
    - field: stats.upspeed
      operator: "<"
      value: 10485760  # < 10 MB/s fleet-wide
actions:
  - type: force_start
```

**Remember the snapshot caveat:** `stats.*` is computed once, before any
rule in the run executes, and is **not** updated by actions earlier rules
take in that same run (see
[Advanced-Topics](Advanced-Topics#stats-snapshot-semantics)). If this rule's
`force_start` action pushes the `uploading` count past your cap, a second
rule later in the *same* run checking `stats.state.uploading` won't
see that increment — it'll see next run's fetch instead.

### Operator Reference

#### Equality Operators

| Operator | Description | Value Types | Example |
|----------|-------------|-------------|---------|
| `==` | Exact match (equals) | string, number, boolean | `info.category == "movies"` |
| `!=` | Not equal | string, number, boolean | `info.state != "error"` |

#### Comparison Operators

| Operator | Description | Value Types | Example |
|----------|-------------|-------------|---------|
| `>` | Greater than | number | `info.ratio > 2.0` |
| `<` | Less than | number | `info.size < 1073741824` |
| `>=` | Greater than or equal | number | `info.ratio >= 1.0` |
| `<=` | Less than or equal | number | `info.progress <= 0.5` |
| `larger_than` | Greater than (human-readable sizes) | string with units (KB, MB, GB, TB) | `info.size larger_than "10GB"` |
| `smaller_than` | Less than (human-readable sizes) | string with units (KB, MB, GB, TB) | `info.size smaller_than "100MB"` |

**Size Operators (v0.3.0+):**

- `larger_than` and `smaller_than` accept human-readable size strings
- Supported units: `KB`, `MB`, `GB`, `TB` (case-insensitive)
- Examples: `"50GB"`, `"100MB"`, `"1TB"`, `"500KB"`

#### String Operators

| Operator | Description | Case Sensitive | Example |
|----------|-------------|----------------|---------|
| `contains` | Substring match | Yes | `info.name contains "1080p"` |
| `not_contains` | Does not contain | Yes | `info.name not_contains "sample"` |
| `matches` | Regex pattern match | Depends on regex | `info.name matches "(?i).*s\d{2}e\d{2}.*"` |

#### List Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `in` | Value is in list | `info.state in ["error", "missingFiles"]` |
| `not_in` | Value is not in list | `info.category not_in ["keep", "seedbox"]` |

#### Time Operators

| Operator | Description | Value Format | Example |
|----------|-------------|--------------|---------|
| `older_than` | Unix timestamp older than | "N days" or "N hours" | `info.added_on older_than "30 days"` |
| `newer_than` | Unix timestamp newer than | "N days" or "N hours" | `info.completion_on newer_than "7 days"` |

**Time Value Formats:**

- Days: `"7 days"`, `"30 days"`, `"1 day"`
- Hours: `"12 hours"`, `"48 hours"`, `"1 hour"`
- Minutes: `"30 minutes"`, `"90 minutes"`, `"1 minute"`

A time qBittorrent hasn't recorded (`completion_on` of a torrent that has never finished, `seen_complete` that was never seen) is sent as `-1`, or `0`/`4294967295` by older releases. Such a time is neither `older_than` nor `newer_than` anything. Inside `none`, that `false` becomes `true`, so use `info.progress` or `info.state` there to tell unfinished torrents apart.

**Operator Behavior with None/Missing Values:**

| Operator Type | Behavior when field is None/missing |
|---------------|-------------------------------------|
| `!=`, `not_in`, `not_contains` | Returns `true` |
| All others | Returns `false` |

#### Collection Field Behavior

For collection fields (`trackers.*`, `files.*`, `peers.*`, `webseeds.*`):

- **Positive operators** (`==`, `contains`, `in`, `matches`, `>`, `<`, ...) check if **ANY item** in the collection matches — returns `true` if at least one item matches.
- **Negation operators** (`!=`, `not_in`, `not_contains`) are the exception and check if **ALL items** satisfy the negation — i.e. none of the items positively match. This is intentional: with tags `["private", "iptorrent.com"]`, `not_contains: "private"` must be `false` (the torrent *is* tagged private), which only holds if every item independently fails to match "private". An ANY-based negation would incorrectly return `true` because the `"iptorrent.com"` tag alone "doesn't contain private".
- An empty collection satisfies negation operators (`true`) and fails every positive operator (`false`).

**Examples:**

```yaml
# Equality
- field: info.category
  operator: ==
  value: "movies"

# Comparison
- field: info.ratio
  operator: ">="
  value: 2.0

# String contains
- field: info.name
  operator: contains
  value: "1080p"

# Regex (case-insensitive TV show pattern)
- field: info.name
  operator: matches
  value: '(?i).*s\d{2}e\d{2}.*'

# List membership
- field: info.state
  operator: in
  value: ["error", "missingFiles", "stalledDL"]

# Time-based (older than 30 days)
- field: info.added_on
  operator: older_than
  value: "30 days"

# Collection (ANY tracker contains ".private")
- field: trackers.url
  operator: contains
  value: ".private"

# Size comparison (human-readable, v0.3.0+)
- field: info.size
  operator: larger_than
  value: "50GB"

# Size comparison (human-readable, v0.3.0+)
- field: info.size
  operator: smaller_than
  value: "100MB"
```
