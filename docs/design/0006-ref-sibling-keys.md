# 0006: A `$ref` with keys beside it is refused

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Proposed
Date: 2026-11-04
Authors: the media coordinator

## Context

A condition in `rules.yml` can be a reference to a named block in `refs.conditions`:
`$ref: conditions.<name>`. The resolver (`RuleResolver._expand_refs` in `resolver.py`) treats any mapping
that holds a `$ref` key as that reference and nothing else: it returns the referenced block and never looks
at the other keys in the mapping. So this rule

```yaml
conditions:
  all:
    - $ref: conditions.public
      any:
        - {field: info.ratio, operator: '>=', value: 2.0}
        - {field: info.seeding_time, operator: '>=', value: 604800}
```

reads as "public, and old or well seeded", but runs as "public". The `any:` is dropped without a word. The
same happens to a field condition (`field`/`operator`/`value`) or an `all:`/`none:` written beside a
`$ref`, at the top of a rule's `conditions`, inside a group, or inside a `refs.conditions` block.

The validator does not catch it either. `rules_validation.py` returns early on any mapping with a `$ref`
(in `conditions`, `condition_block` and `condition`), so `qbt-rules validate` and the dashboard's rules
editor pass the file with no error, warning or note.

Verified on 0.11.3 (commit f7398f4): the rule above, plus a second item with a field condition beside the
same `$ref`, resolves to `{"all": [{"all": [<public>]}, {"all": [<public>]}]}`; `validate_rules_text`
returns 0 errors, 0 warnings, 0 notes; `qbt-rules validate` prints `Valid.` and exits 0.

**Why now.** 0.11.3 fixed nested groups that checked only their first part (#65). That bug and this one
have the same shape: part of a rule is silently dropped, so the rule matches far more than it says. In
production, a deletion rule meant to remove old public torrents matched every public torrent and deleted
each new one as it arrived. This is the last known way to write a condition that loads cleanly and is
partly ignored. For a rule whose action deletes, matching more than written is the worst failure there is.

**Constraints.** Changing this changes which rules files load, so it is a public-interface change. No
example, wiki page or test fixture in this repo uses the shape (a scan of every YAML file found none), and
the wiki's Reusable References page says a `$ref` node "is recursively replaced with the structure it
points to", which implies the siblings go but never says so. Files in the wild may use it, believing it
works.

## Decision

**Recommended: option (a), a `$ref` mapping holds only `$ref`; anything beside it is an error**, reached in
two steps so no working installation stops loading without notice.

1. **Next 0.11.x patch.** The validator reports an **error** on a condition mapping that has a `$ref` and
   any other key, naming the keys that are dropped and the fix: "`any` beside `$ref` is ignored: the
   reference replaces this whole mapping. Put the reference and the `any:` as separate items of an
   `all:` list." `qbt-rules validate` then exits 1, and the dashboard editor refuses to save such a file
   (it already refuses any file with errors). Loading is unchanged: the resolver still drops the keys, but
   logs a warning per rule naming the rule, the path and the dropped keys, once per load.
2. **0.12.0.** The resolver raises `InvalidRefError` on such a mapping, as it does today for an unknown
   reference, so the rules file does not load and the job fails with the rule and path named. The
   changelog's breaking-change note gives the rewrite.

The rewrite the messages point to:

```yaml
conditions:
  all:
    - $ref: conditions.public
    - any:
        - {field: info.ratio, operator: '>=', value: 2.0}
        - {field: info.seeding_time, operator: '>=', value: 604800}
```

Scope: condition references everywhere they can appear (a rule's `conditions`, any group inside it, and a
`refs.conditions` block). Action references (`$ref: actions.<name>` with `params:` or `type:` beside it)
drop their siblings the same way; whether this record covers them too is open question 1.

## Alternatives considered

- **(a) Error: refuse to load the file** (recommended). Every rule then means what it says or does not run.
  It matches how the resolver already treats an unknown or circular reference, and it is the simplest rule
  to explain ("a `$ref` stands alone"). Cost: a file that loads today stops loading at 0.12, so every rule
  in it stops, not just the wrong one. That is the safe direction (a rule that does not run deletes
  nothing), and step 1 gives a release of warning first.
- **(b) Warning only, for good.** No file ever stops loading. But the rule keeps running with the wider
  match, and a warning in a log or the validator's output is exactly what was missed in the incident: the
  destructive behaviour continues until someone reads it. Rejected as the end state; it is step 1 of (a).
- **(c) Merge: the siblings and the referenced block as an implicit `all`.** The mapping becomes
  `all: [<referenced block>, <the siblings as one condition>]`, so the example above would run as written.
  JSON Schema made the same move (draft 7 ignored keys beside `$ref`; 2019-09 applies them alongside).
  It never refuses a file. But it silently changes what an existing rule matches: a rule that has run as
  "public" for months becomes "public and old" with no edit and no error, in the narrowing direction for
  this example but not in general (a sibling `none:` or a reference to an `any:` block reads differently to
  different people). It also adds a meaning that is invisible in the file and that every other place a
  `$ref` appears (actions, vars) would not share. Rejected: an implicit rule is what caused the problem.
- **(d) Do nothing; document it.** The wiki would say the siblings are ignored. Rejected: documentation
  does not stop a file that loads cleanly from deleting the wrong torrents.

A rejected option goes into TODO.md's "Decided against" list when this record is approved.

## Consequences

- Easier: a rules file that loads is a rules file whose every key is read. Together with #65, there is no
  known condition shape left that is partly ignored.
- Harder: a file using the shape needs a one-line rewrite before 0.12. Step 1's validator error and load
  warning name each place.
- Rollout: step 1 is a `fix` (patch release): the validator and a log warning, no change to which files
  load. Step 2 is a `feat!` in 0.12.0. Rollback of step 2 is reverting it; step 1's error then still guards
  the editor and `validate`.
- Tests: a validator case and a resolver case per position (top-level `conditions`, group item,
  `refs.conditions` block) and per sibling kind (group key, field condition).
- Wiki pages that change: Reusable References (a `$ref` stands alone; the rewrite), Conditions (the same,
  where references are shown in groups), Troubleshooting (the new error message), and the 0.12 upgrade
  notes.

## Open questions

1. **Do action references get the same rule?** A `$ref: actions.<name>` with `params:` beside it drops
   them the same way. Recommendation: yes, in the same two steps. One rule for every `$ref` is easier to
   explain, and a dropped `params` can change what an action does (for example whether a delete removes
   files).
2. **Error straight away in loading, rather than at 0.12?** Recommendation: no. The validator error in
   0.11.x already stops the editor saving and `validate` passing; making a patch release refuse a file
   that loaded yesterday would stop every rule in it with no warning release. If the arbiter rates the
   risk of the wider match above the risk of all rules stopping, step 2 can ship in the patch instead.
3. **Is any key allowed beside `$ref`?** For example a `description:` for people reading the file.
   Recommendation: no. The resolver would have to know which keys are notes, and `refs.meta` already holds
   descriptions for reusable blocks.
4. **Option (c) as a later opt-in?** Recommendation: no, not without a request. If wanted, it would be a
   new explicit form (for example `all: [$ref, ...]`, which already works), not a new meaning for an
   existing one.
