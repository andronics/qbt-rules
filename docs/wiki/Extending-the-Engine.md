The condition operators and action types documented in [Conditions](Conditions) and [Actions](Actions) cover common cases, but the engine is small enough to extend directly if you need something built-in doesn't offer. See [Architecture Internals](Architecture-Internals) for how `engine.py` fits into the rest of the codebase.

### Adding Custom Operators

Operator comparison logic lives in `ConditionEvaluator._apply_operator` inside `src/qbt_rules/engine.py`:

```python
def _apply_operator(self, actual, operator, expected, field):
    # ... existing code ...

    elif operator == "starts_with":
        return str(actual).startswith(str(expected))
    elif operator == "ends_with":
        return str(actual).endswith(str(expected))
```

Then use it in rules like any built-in operator:

```yaml
- field: info.name
  operator: starts_with
  value: "Ubuntu"
```

Remember that `_apply_operator` is called per-item for collection fields (`trackers.*`, `files.*`, `peers.*`, `webseeds.*`) — your new operator automatically inherits the ANY/ALL-match semantics described in [Conditions](Conditions#collection-field-behavior) without any extra work, as long as it's a simple `actual`/`expected` comparison.

### Adding Custom Actions

Action types are dispatched from `ActionExecutor` inside the same file. Add a method and register it in the dispatch table:

```python
# src/qbt_rules/engine.py, inside ActionExecutor
def _action_set_priority(self, torrent, params):
    priority = params.get("priority", "normal")
    self.api.post(
        "/api/v2/torrents/setPriority", data={"hashes": torrent["hash"], "priority": priority}
    )
```

Register it alongside the existing entries in the executor's action-type dispatch map, then use it in rules exactly like a built-in action:

```yaml
actions:
  - type: set_priority
    params:
      priority: "high"
```

The four built-in priority actions (`increase_priority`, `decrease_priority`, `set_top_priority`, `set_bottom_priority` — see [Actions](Actions)) are implemented the same way and are a good reference for the pattern.

### Programmatic Hooks for External Tooling (v0.7+)

A few additive, opt-in extension points exist specifically for code built
*on top of* qbt-rules (a custom dashboard, a rule-preview tool, etc.) rather
than for `rules.yml` itself. None of these change behavior unless you
explicitly use them.

**Condition evaluation trace** — `ConditionEvaluator.evaluate()` takes an
optional `trace` list. Pass one in and it's populated with a record per
leaf condition actually evaluated (`{'field', 'operator', 'value', 'actual',
'passed'}`), in evaluation order:

```python
trace = []
matched = evaluator.evaluate(
    torrent, rule["conditions"], current_context, rule.get("context"), trace=trace
)
# trace == [{'field': 'info.state', 'operator': '==', 'value': 'queuedUP', 'actual': 'queuedUP', 'passed': True}, ...]
```

Short-circuiting is unchanged either way — an `all:` block still stops at
the first failing condition, so conditions after that point never appear in
the trace, same as they never ran without one. This is the basis for a
"preview this rule against the live fleet" feature: run `evaluate()` once
per torrent with dry-run intent, with a fresh `trace` list each time, and
you get a full pass/fail breakdown for free.

**Reusable-block metadata** — `RuleResolver.get_block_meta(kind, name)`
reads an optional `refs.meta.conditions.<name>`/`refs.meta.actions.<name>`
entry (`kind` is `'conditions'` or `'actions'`), returning `{}` if none was
defined. This is pure descriptive storage — `$ref` resolution itself never
reads it — meant for a block-library UI to store/display a description or
tags on a reusable condition/action block:

```yaml
refs:
  conditions:
    public-tracker: { field: trackers.url, operator: not_contains, value: ".private" }
  meta:
    conditions:
      public-tracker: { description: "Matches non-private trackers", tags: [tracker] }
```

**Per-rule job history** — `RuleStats.by_rule` (surfaced in a completed
job's `result.by_rule` via the HTTP API — see
[HTTP-API-Reference](HTTP-API-Reference#get-apijobsjob_id)) breaks the
existing aggregate counters down per rule, keyed by each rule's required `id`
(see [Rules-Architecture](Rules-Architecture#rule-identity-id-and-metadescription)).

### Building and Deploying Your Changes

qbt-rules is Docker-only distribution — there's no PyPI package for end users, so a code change doesn't ship until it's baked into an image. To run modified code:

```bash
docker build -t qbt-rules:custom .
```

Then point your `compose.yml` at `qbt-rules:custom` instead of `ghcr.io/andronics/qbt-rules:latest`. `uv sync` (an editable install with the dev tools) is still the right way to iterate locally while developing and running the test suite (see [Contributing](Contributing) and [Testing Guide](Testing-Guide)) — it's just not how the change reaches a running deployment.

If you think the change is broadly useful, consider opening a pull request instead of maintaining a private fork — see [Contributing](Contributing) for the workflow, and [Release Process](Release-Process) for how a merged change eventually reaches a tagged image.
