# 0005: The schedule on interpose 0.4.1

<!-- Add a line for this record to the index in docs/design/README.md (CI checks). -->

Status: Approved
Date: 2026-11-04
Approved: the brain coordinator, 2026-11-04 (for Stephen)
Authors: the brain coordinator (decision e, and that this change is recorded as an amendment of 0001),
the media coordinator and Claude (the rest)
Amends: 0001

## Context

[0001](0001-config-on-interpose.md) put the settings on interpose but kept in qbt-rules' own
`load_config` what interpose couldn't do then: `${VAR}` / `${VAR:-default}` expansion in the file, the
aliases, the `schedule` list with its indexed `QBT_RULES_SCHEDULE_<N>_CRON` / `_CONTEXT` variables, and
the refusals. 0001 also left unknown-key warnings (#11) open, since interpose had no hook for them.

interpose's design record 0009 (settings extensions) has since shipped, up to v0.4.1: step 4 is its own
`${VAR}` expansion, and step 6 is typed list sections with indexed variables, the last piece qbt-rules
needed to drop its own schedule loader. Its step 2 puts warnings for unknown keys and variables on
`Resolved.warnings`. PR #62 pins interpose v0.4.1 and reads `schedule` with it.

Two of issue #61's differences between qbt-rules' expansion and interpose's would silently change a
working configuration: interpose gives a variable set to `""` the `:-` default (qbt-rules keeps `""`), and
reads `$${` as an escape (qbt-rules does not). interpose has no option that keeps the old behaviour.

## Decision

- **(a) The schedule is interpose's typed list section.** `schedule` is a list of items with required
  `cron` (checked with croniter) and `context` fields. The indexed variables
  `QBT_RULES_SCHEDULE_<N>_CRON` / `_CONTEXT`, and their `_FILE` forms, count from 0 as before, and when
  any is set they replace the file's list whole, as every other setting's variable replaces the file's
  value. qbt-rules' own schedule loader (`_load_schedule`, `_variable`) is removed.
- **(b) `QBT_RULES_SCHEDULE_FILE`**, a new public setting, names a YAML file holding the list (for a
  mounted file or secret). `QBT_RULES_SCHEDULE` itself is refused, with an error naming
  `QBT_RULES_SCHEDULE_FILE` and the indexed form.
- **(c) A lone `QBT_RULES_SCHEDULE_<N>_CONTEXT`** without `_N_CRON` now stops start-up with an error naming
  both variables; 0.11.1 ignored it. A variable past the end of the list (no item `N-1`) is ignored, as
  before, now with a warning.
- **(d) interpose's warnings are logged at start-up** (`Configuration: …`) and printed by `qbt-rules
  config` and `qbt-rules validate`: unknown `config.yaml` keys, unknown `QBT_RULES_*` variables and
  unknown fields in a schedule item, each with a did-you-mean where one fits. This delivers #11's
  unknown-key warnings, which 0001 left open.
- **(e) `${VAR}` expansion stays qbt-rules' own until the next major release** (the brain coordinator,
  2026-11-04). It then moves to interpose's strict default, taking the two silent differences of #61 (a
  variable set to `""` gets the `:-` default; `$${` is an escape) as that release's breaking changes.
  Until then, interpose resolves from a `Layer` holding qbt-rules' expanded copy of the file, so file
  values keep the `file` source and their errors name the path. The tests pin today's behaviour, and #61
  stays open.

0001's other decisions (paths, aliases, refusals, first start, no API key) are unchanged.

## Alternatives considered

- **Switch to interpose's expansion now:** two of #61's differences would change a working configuration
  without an error, in a patch release. A major release is where that belongs.
- **Ask interpose for a compatibility option** (keep `""` over the default, no `$${` escape): it would
  carry qbt-rules' old rule in a shared library for one consumer, and interpose's 0009 chose the shell's
  rule on purpose. qbt-rules' own `_expand` is small and already tested.
- **Keep qbt-rules' own schedule loader:** it duplicates what interpose now does, with weaker errors (no
  path, entries counted from 1) and no unknown-field warnings.

## Consequences

User-visible, released as 0.11.2 (PR #62's report):

- Schedule errors count items from 0 and name the file or variable, e.g.
  `schedule[0].cron: … (from /etc/qbt-rules/config.yaml)`, where 0.11.1 said `schedule entry #1 …`.
  Errors about any value from the file, an expanded `${VAR}` included, name the file's path.
- `qbt-rules config` shows the schedule once, one line per item, with its source.
- A lone `_N_CONTEXT` is now a start-up error (c); new start-up warnings (d).
- `QBT_RULES_SCHEDULE_FILE` is new (b).

The upgrade note is on the wiki's Upgrading-to-0.11, "From 0.11.1 to 0.11.2"; In-Depth-Configuration,
Scheduling, Troubleshooting and Architecture-Internals change with it. Production deployments (the
Unraid template and homelab-k8s) set no `QBT_RULES_SCHEDULE_*` variable and no `${...:-...}` or `$${`
form, so they are affected only by warnings for leftover keys or variables. Rollback is 0.11.1's image;
the configuration is the same.

## Open questions

None.
