Reusable references let you define a variable, a condition block, or an action sequence **once** and reuse it across as many rules as you like, instead of copy-pasting the same YAML into every rule that needs it. Introduced in v0.5.0.

### Where They Live

The `refs:` block sits at the top level of `rules.yml`, as a sibling of `rules:` — not nested inside any individual rule:

```yaml
refs:
  vars:
    min_ratio: 2.0
  conditions:
    well-seeded:
      all:
        - field: info.ratio
          operator: ">="
          value: ${vars.min_ratio}
  actions:
    tag-and-categorize:
      - type: add_tag
        params:
          tags: ["auto-tagged"]
      - type: set_category
        params:
          category: "Movies"

rules:
  - id: tag-well-seeded-movies
    conditions:
      - $ref: conditions.well-seeded
    actions:
      - $ref: actions.tag-and-categorize
```

The main groups under `refs:` are `vars`, `conditions`, and `actions` — each a flat mapping of a name you choose to the reusable content. A fourth, optional group, `meta` (v0.7+), holds descriptive metadata about your `conditions`/`actions` blocks rather than content the engine evaluates — see [below](#metadata-refsmeta).

### Variables (`refs.vars` + `${vars.x}`)

`refs.vars` holds plain values — numbers, strings, lists, whatever a condition's `value:` or an action's `params:` might need:

```yaml
refs:
  vars:
    min_ratio: 2.0
    cleanup_age: "30 days"
    protected_categories: ["keep", "seedbox", "archive"]
```

Reference a variable anywhere with `${vars.name}`:

```yaml
conditions:
  all:
    - field: info.ratio
      operator: ">="
      value: ${vars.min_ratio}
    - field: info.category
      operator: not_in
      value: ${vars.protected_categories}
```

**Substitution is type-aware.** If `${vars.x}` is the *entire* string value, the variable's original type is preserved — `value: ${vars.protected_categories}` becomes the actual list, not a stringified version of it. If `${vars.x}` is embedded inside a longer string, it's interpolated as text instead:

```yaml
# Whole-value substitution — value becomes the list [ "keep", "seedbox", "archive" ]
value: ${vars.protected_categories}

# Embedded substitution — value becomes the string "Category: Movies"
category: "Category: ${vars.category_name}"
```

Referencing an undefined variable (a typo, or a name that isn't declared under `refs.vars`) raises an error rather than silently resolving to `null` or an empty string — you'll see it immediately when the config loads or the rule runs, not as a mysteriously-never-matching condition.

### Conditions (`refs.conditions` + `$ref: conditions.name`)

`refs.conditions` holds named condition blocks — anything you could write inside a rule's `conditions:` key:

```yaml
refs:
  conditions:
    private-tracker:
      any:
        - field: trackers.url
          operator: contains
          value: "torrentleech.org"
        - field: trackers.url
          operator: contains
          value: "iptorrents.com"

    protected-content:
      all:
        - field: info.category
          operator: in
          value: ${vars.protected_categories}
```

Use it with `$ref: conditions.<name>` inside a rule's `conditions:`. A rule's `conditions:` can be a bare list — each entry is implicitly AND-ed together — which makes mixing refs and inline conditions natural:

```yaml
- id: force-seed-under-ratio-private
  conditions:
    - $ref: conditions.private-tracker
    - none:
        - $ref: conditions.protected-content
    - field: info.ratio
      operator: "<"
      value: ${vars.min_ratio}
  actions:
    - type: force_start
```

Conditions refs can nest — one named condition can `$ref:` another (as `public-tracker` doing `none: [$ref: conditions.private-tracker]`, for example). Circular chains (A references B references A) are detected and rejected with an error rather than recursing forever.

### Actions (`refs.actions` + `$ref: actions.name`)

`refs.actions` holds named **action sequences** — a named ref is itself a list of one or more action entries:

```yaml
refs:
  actions:
    tag-and-categorize:
      - type: add_tag
        params:
          tags: ["auto-tagged", "hd"]
      - type: set_category
        params:
          category: "Movies-HD"
      - type: set_top_priority
```

Use it with `$ref: actions.<name>` as an entry in a rule's `actions:` list:

```yaml
- id: auto-organize-hd-imports
  context: torrent-imported
  conditions:
    - field: info.name
      operator: matches
      value: '(?i).*(1080p|2160p|4k).*'
  actions:
    - $ref: actions.tag-and-categorize
    - type: reannounce  # you can still mix in inline actions
```

Because an actions ref resolves to a *list* rather than a single action, it's spliced into the surrounding `actions:` list in place — the three actions inside `tag-and-categorize` above run as three ordinary sequential actions, not as one nested list-shaped action (which the engine wouldn't know how to execute). Prior to a fix in v0.5.4, this splicing didn't happen correctly; if you're running an older build, upgrade before relying on multi-action refs.

### Metadata (`refs.meta`)

`refs.meta` (v0.7+) holds optional descriptive information about your
`conditions`/`actions` blocks — a description, tags for organizing a large
block library, whatever a future tool wants — keyed the same way as the
blocks themselves:

```yaml
refs:
  conditions:
    public-tracker:
      field: trackers.url
      operator: not_contains
      value: ".private"
  meta:
    conditions:
      public-tracker:
        description: "Matches when none of a torrent's trackers are private/gated"
        tags: [tracker]
```

Unlike `vars`/`conditions`/`actions`, nothing under `meta` is read during
`$ref:` expansion or rule evaluation — `$ref: conditions.public-tracker`
still resolves to exactly the condition body above, completely unaffected by
whether a matching `meta` entry exists. It's pure storage, there for
external tooling (see [Extending-the-Engine](Extending-the-Engine#programmatic-hooks-for-external-tooling-v07)
for the read API) to build a block-library view on top of, without qbt-rules
itself needing to interpret it. Leaving `refs.meta` out entirely is fine —
every `$ref` block you've already written keeps resolving exactly the same.

**Don't confuse this with a rule's own `meta.description`** (see
[Rules-Architecture](Rules-Architecture#rule-identity-id-and-metadescription))
— that's a sibling field directly on a `rules:` entry, describing the rule
itself (and *is* required-adjacent, since it's the recommended place for the
human-readable text a rule's required `id` deliberately isn't). `refs.meta`
here is a completely separate, fully optional namespace under `refs:`,
describing reusable `conditions`/`actions` blocks instead.

### Type Checking Between Groups

`$ref:` is type-checked by where it's used: a `conditions.*` ref can only be used inside a rule's `conditions:` (or nested inside another conditions ref), and an `actions.*` ref can only be used inside a rule's `actions:`. Using the wrong type in the wrong place — e.g. `$ref: actions.foo` inside a `conditions:` block — raises an error at resolution time rather than silently doing nothing.

### How Resolution Works

Every rule goes through two phases before it's evaluated against a torrent:

1. **Reference expansion** — every `$ref:` node in `conditions:`/`actions:` is recursively replaced with the structure it points to (nested refs are expanded too, with circular-reference detection).
2. **Variable substitution** — every `${vars.x}` in the now-fully-expanded rule is replaced with its value from `refs.vars`, preserving type for whole-value substitutions.

This happens once per rule, per job — you always write and reason about `$ref`/`${vars.x}` in the raw YAML; the expanded form is what the engine actually evaluates, and it's what shows up in `--trace` output.

### Why Use This

- **Single source of truth** for a threshold (`min_ratio`), a tracker list, or a common cleanup-action sequence — change it in one place under `refs:` instead of hunting down every rule that inlined it.
- **Readability** — a rule built from `$ref: conditions.private-tracker` + `$ref: conditions.well-seeded` reads like a sentence; the same rule with both condition blocks inlined can run to dozens of lines.
- **Consistency** — when a security- or safety-sensitive condition (like a "never touch these categories" guard) is defined once and referenced everywhere, there's no risk of one copy drifting out of sync with another.

See [Conditions](Conditions) and [Actions](Actions) for the underlying condition/action syntax that refs are built from.
