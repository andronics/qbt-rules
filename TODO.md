# qbt-rules — TODO

Currently-open items only. Resolved bugs and their postmortems live in
`BUGS.md`; `PLAN.md` is the (mostly complete) v0.4.0 architecture doc.

## Open

- **Kubernetes-style `kind:`/`metadata:`/`spec:` envelope for rules.yml
  resources** — deferred, not decided against. Rationale for waiting: k8s's
  `kind` earns its keep by routing polymorphic resources through one
  API/validation pipeline, and its `spec`/`status` split exists to protect
  user-declared state from system-written state. Neither applies yet --
  `rules.yml` has one resource shape (`rules:`) and no `status` subresource
  (job results live in the separate `jobs` table's `by_rule`, not written
  back onto the rule). Revisit when qbt-ui's CRUD API becomes real: at that
  point `refs.conditions.<name>`/`refs.actions.<name>` (dict-keyed reusable
  blocks) and `rules:` (list of rule objects) are two structurally
  different resource shapes that a real API needs to route/validate
  differently anyway -- that's when `kind: Rule`/`kind: ConditionBlock`/
  `kind: ActionBlock` stops being cosmetic. Doing it now, with only one
  kind in existence, would just add an indentation level with no new
  capability. Also worth revisiting then: further collapsing config.yml/
  rules.yml toward reusable, addressable elements generally (not just this
  one schema shape) once there's a concrete CRUD surface driving the
  requirements, rather than guessing at the shape in advance.

## Decided against (don't re-propose without reading this first)

- **`priority:` field on rules** — documented in the advanced example,
  never implemented (`engine.py` never reads it; rules run in strict file
  order). Decided not to build it: any `rules.yml` without explicit
  priorities needs a deterministic tie-break, and a subtle bug there
  could silently reorder the security-critical rules to run after
  everything else. Not worth the risk at the current rule count, where
  file order is already sufficient. Revisit only if the ruleset grows
  large enough that physical reordering becomes the actual pain point.
- **Instance-scoped variable overrides** — `resolver.py` fully implements
  per-instance variable overrides, but `config.py` hardcodes
  `instance_id=None`, so it's unreachable. Would matter for running one
  shared ruleset across multiple qBittorrent instances. Decided not to
  wire it up: the rest of the app (single `QBittorrentAPI` client, job
  queue schema, webhook routes, every `AutoRun` hook URL) is built around
  exactly one instance per server process — real support means threading
  an `&instance=` dimension through jobs/webhooks/CLI, with no way to test
  it without an actual second qBittorrent instance. Pure speculative
  infrastructure until a second instance actually exists.
