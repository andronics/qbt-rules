# qbt-rules — Ongoing Notes / TODO

Running backlog of known issues and planned work, updated as we go across sessions.
`PLAN.md` is the (mostly complete) v0.4.0 architecture doc — this file is for
day-to-day maintenance items instead.

## 2026-09-07

### Fixed this session
- [x] `ci.yml` "Check for common issues" step false-positives on its own docstring
      in `src/qbt_rules/config.py` (`config_key='server.api_key'` matches the
      credential-detection regex) and hard-fails with `exit 1` on *any* match,
      benign or not. This is why CI has failed on every single run since it was
      added (Dec 2025 – present).
- [x] `ci.yml` "Validate configuration examples" step references
      `config/config.example.yml` / `config/rules.example.yml`, which don't exist —
      the real files are `config/config.default.yml` / `config/rules.default.yml`
      (renamed at some point, workflow never updated). Guaranteed failure every run.
- [x] `docker-build.yml` tag list includes `type=sha,prefix={{branch}}-`, which
      only resolves on branch-triggered builds. On a tag push (`v0.4.1`, `v0.5.0`,
      etc.) `{{branch}}` is empty, producing the invalid tag `-<sha>` and aborting
      the whole multi-arch build. **This means no `vX.Y.Z` image has ever actually
      been published to GHCR** — confirmed via `ghcr.io/v2/andronics/qbt-rules/tags/list`,
      which only shows `main`, `latest`, `main-<sha>`.
- [x] Discovered `ghcr.io/andronics/qbt-rules:dev` (referenced in
      `/mnt/docker/svcs/qbittorrent/compose.yml` production deploy) **does not
      exist in the registry at all**. The running container is on a locally
      cached image from 2025-12-20, manually tagged at some point. If that cache
      is ever lost, a redeploy would fail outright on `docker compose pull`.

### Still to do
- [x] Pin `qbittorrent` compose's `rules` service to a real, reliably-published
      version tag once the fixed workflow produces one (deferred until after
      this fix + a verified tag-triggered build succeeds). **Done**: production
      `compose.yml` now pins `ghcr.io/andronics/qbt-rules:0.5.1`. Verified via
      `docker inspect`, `/api/health`, `/api/version`, a clean `Loaded 7 rules`
      startup, and a manual `context=cron` sweep against the live torrent list.
- [x] **Bug found while verifying the pin**: `/api/version` on the freshly
      deployed `0.5.1` image reported internal version `"0.5.0"`, not `0.5.1`.
      Real root cause: `v0.5.1` was tagged manually (`git tag && git push`)
      instead of via `scripts/bump-version.sh`, which is the only thing that
      bumps the version files *before* creating the tag. `release.yml`'s old
      "Update version in code" + "Commit version update" steps silently
      re-bumped and re-committed to `main` *after* the tag already existed —
      too late for `docker-build.yml`, which had already built from the
      pre-bump commit the tag pointed to. **Fixed**: `release.yml` no longer
      auto-corrects; it now hard-fails ("Verify version matches tag") if the
      tagged commit's `__version__.py`/`pyproject.toml` don't already match
      the tag name, forcing `bump-version.sh` to be used and turning any
      future manual-tag mistake into an immediate CI failure instead of a
      silent, permanent mismatch. Also fixed `bump-version.sh` itself, which
      only ever bumped `__version__.py` — it now bumps `pyproject.toml` too.
      Verified the new check logic locally against both a matching and a
      deliberately mismatched version (correctly passes / hard-fails).
      **Verified live** in `v0.5.2`: ran `scripts/bump-version.sh patch`
      properly this time (bump+commit before tagging), pushed, and watched
      "Verify version matches tag" pass for real in GitHub Actions. Confirmed
      `ghcr.io/andronics/qbt-rules:0.5.2 --version` reports `v0.5.2` —
      tag and baked-in version agree for the first time ever in this project.
- [ ] Consider whether `pytest` thread-race warnings in `test_sqlite_queue.py`
      (`sqlite3.OperationalError: database is locked` under
      `TestSQLiteQueueThreadSafety`) indicate a real concurrency bug in
      `sqlite_queue.py`'s locking, or are just test-harness noise. Currently
      non-fatal (pytest doesn't treat them as failures) but worth a look —
      SQLite's default busy_timeout may be too short for the concurrent test.
- [ ] `release.yml` commits a version bump to `main` *after* the tag has already
      been pushed and pointed at the old commit — the tag and the "release" state
      of `main` diverge slightly (the tag never contains its own version-bump
      commit). Low priority, cosmetic, but worth knowing.
- [ ] No `read:packages` scope on the `andronics` GitHub CLI token — couldn't
      query package versions via `gh api`, had to hit the GHCR OCI API directly
      with an anonymous pull token instead. Not blocking, just a minor friction
      point for future debugging sessions.
- [ ] Legacy `/config/scripts/archive_filter.py` and `rules_engine.py` sitting
      unused inside the deployed `qbittorrent-rules` container (pre-package
      prototypes, not referenced by `config.yml`). Harmless but confusing —
      candidate for cleanup on the deploy side, not this repo.

### Resolver layer (v0.5.0+) — two documented-but-unimplemented features

While explaining the refs/resolver layer, found `advanced-rules-example.yml`
documents two capabilities that don't actually exist in the engine:

**1. `priority:` field on rules** — the example gives every rule a numeric
   `priority` (10–100) implying priority-based execution order. Grepped
   `engine.py`: `priority` is never read anywhere. Rules execute strictly in
   file order (confirmed live: "execute in file order" in `qbt-rules.log`).
   The field is currently inert.

   - Pro of implementing: decouples logical importance from physical file
     position; would stop the example file from documenting a lie.
   - Con: real risk to get wrong. Any `rules.yml` without explicit priorities
     (production's, currently) needs a deterministic tie-break — almost
     certainly "preserve file order" — and a subtle bug here could silently
     reorder the two security-critical rules (archive block, exe/scr block)
     to run *after* other rules instead of first. More test surface for a
     ruleset that's currently only 7 rules, where file order is already
     fully sufficient.
   - **Recommendation**: don't implement yet — strip `priority:` from the
     example file instead (done, see below). Revisit only if the ruleset
     grows large enough that physical reordering becomes the real pain
     point.

**2. Instance-scoped variable overrides** — `resolver.py:57-84` fully
   implements per-instance variable overrides (looks complete), but
   `config.py:497` hardcodes `instance_id=None` (there's literally a `TODO`
   comment on config.py:496), so it's unreachable. This would matter for
   running one shared ruleset across *multiple* qBittorrent instances (e.g.
   a private-tracker box + a public seedbox) with per-instance variable
   overrides (different ratio thresholds, hosts, etc.).

   - Pro: exactly what the advanced example's private/public tracker framing
     gestures at; would eliminate near-duplicate rule files if a second
     qBittorrent instance is ever added.
   - Con: much bigger lift than it looks. The rest of the app (single
     `QBittorrentAPI` client, job queue schema, webhook routes, every
     `AutoRun` hook URL) is built around exactly one qBittorrent instance
     per server process. Wiring real multi-instance support through means
     threading an `&instance=` dimension through jobs/webhooks/CLI, plus no
     good way to test it without an actual second qBittorrent instance.
   - **Recommendation**: leave alone entirely. You run one qBittorrent
     instance today — this is speculative infrastructure (YAGNI) until that
     changes.

- [x] Stripped `priority:` from every rule in `advanced-rules-example.yml`
      and removed the now-inaccurate "Priority-based rule ordering" bullet
      from its summary comment, so the example only documents features that
      actually work.

### Bug: bare-list `conditions:` silently matched everything (fixed)

Found while drafting new rules for the live deploy, using the same bare-list
style `advanced-rules-example.yml` uses throughout
(`conditions: [{$ref: ...}, {$ref: ...}, {none: [...]}]`, no `all:`/`any:`
wrapper). `engine.py`'s `evaluate()` only checked `'all' in conditions`,
`'any' in conditions`, `'none' in conditions` — when `conditions` is a
`list` of dicts rather than a dict, none of those checks can ever be true
(`in` on a list checks for a matching *element*, not a dict key), so it fell
through to `return True` unconditionally. **Every one of the 10 rules in
`advanced-rules-example.yml` matched every torrent regardless of its
conditions** — confirmed empirically with `ConditionEvaluator.evaluate()`
directly before touching the fix.

Also confirmed while investigating: `contains` with a *list* value (e.g. a
naive `${vars.trackers_x}` substitution of a URL list into a `contains`
condition) throws inside `_apply_operator` (`'in <string>' requires string
as left operand, not list`), which the engine's broad `try/except` swallows
and just returns `False` — silently never-matches rather than erroring
loudly. If that pattern ever ended up inside a `none:` protection clause,
the protection would silently never trigger, which is the wrong-shaped
failure to have on a destructive-action guard. Not the same bug as the
bare-list issue, but same root cause: an unvalidated shape assumption in the
operator/condition layer failing silently instead of loudly.

**Fixed**: `evaluate()` in `engine.py` now treats a bare list as an
implicit `{'all': [...]}` — `isinstance(conditions, list)` delegates
straight to `_evaluate_all()`, which already handles nested `all`/`any`/
`none` dicts inside each list entry correctly via `_evaluate_condition()`.
Purely additive — dict-wrapped `conditions:` (what production `rules.yml`
uses) is completely unaffected. Added 4 regression tests in
`test_condition_evaluator.py` (`TestBareListConditions`-style, inline in
`TestLogicalGroups`): all-true, one-false, nested-logical-group, and empty
list. Full suite: 1028 passed (was 1024), `engine.py` still 100% coverage.

Side effect: `advanced-rules-example.yml` did **not** need rewriting after
all — its bare-list style is now genuinely supported rather than silently
broken, so it's accurate as originally written (minus the already-stripped
`priority:` field).

**Update**: cut and deployed as `v0.5.3`. `release.yml`/`docker-build.yml`
both succeeded on the real tag push, confirmed via `--version` inside the
published image. Production `compose.yml` now runs `ghcr.io/andronics/
qbt-rules:0.5.3` (was `0.5.1`).

### Bug: `$ref: actions.X` breaks when actions.X is a list (found deploying v0.5.3, fixed)

While deploying the four new rules to production, discovered a second,
separate resolver bug — worked around in production at the time, now fixed
properly in the engine.

`refs.actions.*` blocks are lists (an action sequence, e.g.
`force-seed-private: [force_start, set_upload_limit, add_tag]`). Referencing
one via `$ref: actions.x` from *within* a rule's own `actions:` list (also a
list) doesn't splice/flatten — `_expand_refs`'s list-handling just maps each
list item through expansion and returns the result in place, so the ref gets
replaced by its list value *nested inside* the parent list. The engine then
iterates the parent list expecting each item to be an action dict and
crashes: `TypeError: list indices must be integers or slices, not str`
(`action['type']` on what's actually a list).

Confirmed live: "Tag iptorrent.com Trackers" (using `$ref: actions.tag-private`
alongside an inline `add_tag`) matched correctly but crashed on execute.
This is **not** limited to mixed ref+inline usage — a rule using *only* a
single action ref (no inline actions) breaks identically, same list-in-list
shape. All four of the new rules that referenced `actions.tag-private` /
`actions.force-seed-private` were affected.

This also means `advanced-rules-example.yml` Rule 9 ("Special handling for
private tracker HD TV shows"), which mixes `$ref: actions.process-hd-content`
+ `$ref: actions.force-seed-private` + inline actions in one list, has this
exact same bug — a third real issue in that file, on top of the already-fixed
bare-list-conditions bug and the already-fixed `priority:` field.

Note this is **not symmetric with conditions**: `$ref: conditions.x` used
inside a rule's `conditions: {all/any/none: [...]}` list works correctly,
because `refs.conditions.*` blocks are single dicts, not lists — a dict
nested as one list item is exactly the correct shape. Only `actions.*` refs
have this problem, because they're lists by design.

**Workaround applied to production**: removed the `tag-private` and
`force-seed-private` entries from `refs.actions` entirely and inlined their
action steps directly into each of the four rules (the three tracker-tag
rules now do one `add_tag` with both tags combined instead of two actions;
`Force Seed Under-Ratio Private Torrents` inlines all three steps). Verified
clean: `Loaded 9 rules`, a full `context=cron` sweep against 22 live
torrents — 16 rule matches, 8 actions executed, zero errors.

**Fixed properly in the engine.** `_expand_refs`'s list-handling now tracks
whether each item was itself a `$ref` node; if its expansion is a list, the
list is spliced (`.extend()`) into the parent instead of appended
(`.append()`) as a single nested element. Only triggers for items that were
actually `$ref` nodes — a literal nested list already present in the source
YAML (unrelated edge case, not expected in this rules DSL but worth
guarding) is left untouched. `conditions.*` refs are unaffected by
construction (they resolve to dicts, so nesting as a single list item was
already correct — verified this stays true with a dedicated regression
test).

9 existing tests had encoded the old nested-list shape as expected
behavior (effectively asserting the bug) — updated all of them. Added 4 new
regression tests covering: mixed ref+inline splice, single-ref-only splice,
condition-ref nesting unaffected, and literal nested lists not flattened.
Full suite: 1032 passed (was 1028), CI green on `main`.

**Update**: cut and deployed as `v0.5.4`. Production `compose.yml` restored
to actually use `$ref: actions.tag-private` / `$ref: actions.force-seed-private`
(reverted the `v0.5.3` inlined-actions workaround) to prove the fix live in
the exact scenario that crashed before. Confirmed: `Loaded 9 rules`, full
`context=cron` sweep against 22 live torrents — 16 matches, 8 actions
executed, zero errors, `/api/version` reports `0.5.4`.

- [ ] `advanced-rules-example.yml` Rule 9 ("Special handling for private
      tracker HD TV shows") still mixes `$ref: actions.process-hd-content` +
      `$ref: actions.force-seed-private` + inline actions the way that used
      to crash — worth revisiting now that the engine handles it correctly,
      just to confirm the example actually runs end-to-end for real (never
      verified, only read).

### Aside: Docker Compose's own `${VAR}` interpolation collides with qbt-rules' `${vars.x}` syntax

Also hit while deploying: production's `qbtr_rules` config is an inline
`content: |` block inside `compose.yml`, and Docker Compose does its own
`${VAR}`/`$VAR` interpolation on that text *before* writing it out — which
collides with qbt-rules' own `${vars.x}` resolver syntax **and** the bare
`$ref:` key (Compose treats unbraced `$ref` as short-form variable syntax
too, silently blanking it to `- : actions.x` and emitting "the "ref"
variable is not set" warnings — which explains warnings seen earlier this
session before any refs/vars were in use). Fixed by escaping every literal
`$` the resolver needs as `$$` (`${vars.x}` → `$${vars.x}`, `$ref:` →
`$$ref:`) so Compose collapses it back to a single `$` in the file it
actually writes to the bind mount. Verified via the real file inside the
container (`docker exec ... cat /config/rules.yml`), not `docker compose
config`'s preview — the preview keeps showing the doubled `$$` form even
after correct interpolation, so it's not a reliable way to check this.

### Decided
- Floating "latest build from main" tag renamed to `edge` (was `dev`, which
  never actually existed as a real published tag). `latest` now only applies
  to tag-triggered (semver) builds, matching the conventional meaning of
  "latest stable release." `compose.yml` in the qbittorrent deploy needs to
  move from `:dev` to `:edge` (or a pinned `vX.Y.Z` once available) as a
  follow-up — not done yet, tracked above.

### Verified fixed (v0.5.1 release, 2026-09-07)
- Cut and pushed `v0.5.1` from `main` with the workflow fixes in place.
  Both `release.yml` and `docker-build.yml` completed successfully on the
  real tag-push trigger (previously: 100% failure on every version tag ever
  pushed). Confirmed via `ghcr.io/v2/andronics/qbt-rules/tags/list` that
  `0.5.1`, `0.5`, and `0` now exist in the registry for the first time ever,
  alongside `latest` and the new `edge`.
- Minor non-blocking warning surfaced in `release.yml`'s "Create Release"
  step: `softprops/action-gh-release@v1` doesn't actually support the
  `make_latest` input (`Unexpected input(s) 'make_latest'`) — it's silently
  ignored rather than failing, so releases still get created fine, but the
  "mark as latest release" behavior on GitHub's Releases page probably isn't
  doing anything. Low priority; would need bumping to a newer major version
  of that action or dropping the input.

### Feature: `contains`/`not_contains` now accept a list value (v0.5.5)

Follow-up to the actions-ref splice fix. Rather than hand-writing regex
alternation strings for the tracker-matching conditions
(`'(?i)(domain1|domain2|domain3)'`), extended `_apply_operator` in
`engine.py`: `contains` with a list `value` now matches if ANY item is a
substring of the actual value; `not_contains` is true only if none are.
Single-string values keep their exact original behavior — fully backward
compatible, confirmed via test.

This also closes the silent-failure gap noted earlier in this file: a list
value previously threw inside `_apply_operator` and was swallowed by
`evaluate()`'s broad `try/except` into an always-`False` result. Now it
does the intuitive thing.

Production `rules.yml` updated to match: `trackers_iptorrent` /
`trackers_torrentday` / `trackers_myanonamouse` vars are now plain lists of
domains instead of regex strings, and the tracker-matching conditions were
extracted into `refs.conditions.tag-iptorrent` / `tag-torrentday` /
`tag-myanonamouse` (referenced via `$ref`, matching how actions already
work) instead of being inlined per rule.

5 new tests, full suite 1035 passed (was 1032), `engine.py` still 100%
coverage. Cut as `v0.5.5`, deployed live: `Loaded 9 rules`, sweep against
22 real torrents produced **identical match counts** to the regex version
(2 iptorrent, 6 torrentday, 0 myanonamouse — same as pre-change), zero
errors, `/api/version` reports `0.5.5`.

### Bug: negation operators against list fields used ANY instead of ALL (found + fixed, v0.5.6)

Found while drafting a `tagged-private`/`tagged-public` condition pair at
andronics' request — the exact `not_contains "private"` pattern already
live in production's "Delete Public Torrents" rule.

`info.tags` resolves to a **list** (`parse_tags` splits on comma).
`_apply_operator`'s collection handling applied `any(...)` uniformly across
every operator. Correct for positive checks (`contains`/`==`/`in`: "does at
least one item match"), **wrong** for negations (`not_contains`/`!=`/
`not_in`): `any(item satisfies negation)` is true if even one item fails to
match, which is true for almost any multi-item collection — it doesn't mean
"none of the items match."

Confirmed live: for tags `['private', 'iptorrent.com']` (exactly what the
tag rules produce), `not_contains "private"` incorrectly returned `True`
because the `iptorrent.com` tag alone satisfied "doesn't contain private,"
regardless of the `private` tag sitting right next to it. Verified all 8
current production torrents have this exact multi-tag shape. They're
currently shielded from the bug by the `protected-content` category check
(`Seed Private Torrents After Download` moves them to `seedbox` category
within 30 minutes of completion) — but there's a real window before that
reassignment (during download, and up to 30 min after) where a private
torrent that happened to already read as 3+ days old or ratio ≥ 2.0 (e.g. a
re-imported older private torrent) would have wrongly matched the public
deletion rule.

**Fixed**: when `actual` is a list, negation operators now use `all(...)`
— true only when *no* item positively matches. Positive operators
unchanged. The empty-list early return was already vacuously correct for
negations and needed no change. 7 new regression tests (not_contains/!=/
not_in against lists with one match, no matches, and the empty-list edge
case). Full suite: 1042 passed (was 1035), `engine.py` back to 100%
coverage. Cut as `v0.5.6`, deployed live: `Loaded 9 rules`, clean sweep
against 22 real torrents (16 matches, 8 actions, zero errors),
`/api/version` reports `0.5.6`. Confirmed via direct qBittorrent API query
that real production torrents carry the exact tag shape this fixes.

### Added `tagged-private` / `tagged-public` / `is-complete` conditions

Requested by andronics once the negation-semantics fix above made
`not_contains` safe to build on. Added to production `refs.conditions`:

```yaml
tagged-private:
  all: [{field: info.tags, operator: contains, value: "private"}]
tagged-public:
  all: [{field: info.tags, operator: not_contains, value: "private"}]
is-complete:
  all: [{field: info.completion_on, operator: older_than, value: ${vars.public_max_age}}]
```

Refactored both rules that previously inlined these checks to use the
refs instead: `Seed Private Torrents After Download` (swapped its inline
`info.tags operator: in value: ["private"]` for `$ref: conditions.tagged-private`
— same practical effect for a single-value list) and `Delete Public
Torrents After 3 Days or 2.0 Ratio` (swapped its inline tags/completion-age
checks for `$ref: conditions.tagged-public` / `$ref: conditions.is-complete`).
No image rebuild needed (`v0.5.6` already supports everything used) — just
a config redeploy. Verified live: `Loaded 9 rules`, identical match/action
counts to the pre-refactor run (16 matches, 8 actions, zero errors).

### Added `has-archive` / `has-executable` / `seed-grace-period` / `public-ratio`

Requested by andronics ("what other conditions can we do"). These were the
last remaining raw `field:`/`operator:`/`value:` blocks inlined directly in
rules rather than expressed as refs — after this, **every** condition
check in the whole ruleset goes through a named `$ref`, no exceptions:

- `has-archive` / `has-executable`: extracted from "Remove Archive Based
  Torrents" / "Remove Torrents Containing Windows Executables" (the two
  security-critical, `stop_on_match: true`, `context: added` rules).
- `seed-grace-period`: extracted from "Seed Private Torrents After
  Download"'s inline `completion_on older_than` check.
- `public-ratio`: extracted from "Delete Public Torrents"'s inline
  `info.ratio >= ...` check.
- Bonus cleanup: `under-seeded-private` no longer duplicates the tags
  check — it now nests `$ref: conditions.tagged-private` instead of
  repeating `field: info.tags, operator: contains, value: "private"`
  inline. Confirmed nested refs-within-refs resolve correctly (already
  relied on transitively by the resolver's recursive `$ref` expansion,
  just hadn't been exercised by production config until now).

No image rebuild needed. Verified live twice: (1) a full sweep against 25
real torrents produced identical match/action counts to the pre-refactor
run (16 matches, 8 actions, zero errors) — including the two
security-critical rules processing without error; (2) re-ran the
fake-exe-torrent test from earlier in the session against the *refactored*
"Remove Torrents Containing Windows Executables" rule specifically, since
it's the most safety-critical rule in the system and "processes without
erroring" isn't the same as "still actually catches the exe" — confirmed
it still deletes the torrent + files within ~1 second, same as before the
refactor.

### Added seed counterbalance rule for private torrents (10th rule)

Requested by andronics to address the "private torrents seed forever, no
upper bound" gap flagged earlier. Non-destructive by design — tags only,
never auto-deletes private content (real H&R risk on their trackers if
automated wrong).

- `vars`: `archive_candidate_seed_time: 3888000` (45 days, in seconds —
  `info.seeding_time` is a raw duration field, not a timestamp, so
  `older_than` doesn't apply; used a plain `>=` comparison instead, same
  approach `advanced-rules-example.yml` uses for `info.seeding_time`),
  `archive_candidate_min_ratio: 2.0`.
- `conditions.private-archive-candidate`: `$ref: conditions.tagged-private`
  AND `seeding_time >= 45 days` AND `ratio >= 2.0` — explicitly AND, not
  OR (confirmed with andronics; OR would have matched the existing
  "Delete Public Torrents" pattern but was deliberately not what was
  wanted here).
- New rule "Flag Long-Seeded Private Torrents for Archive Review":
  `add_tag: [archive-candidate]` when matched. That's it — no category
  change, no force actions, no deletion. Purely a signal for manual
  review.

No image rebuild needed. Verified live: `Loaded 10 rules`, clean sweep
(zero errors, zero matches yet since nothing in the library has 45+ days
seeding time). Since there's no way to wait 45 real days to prove the
match logic itself, verified synthetically instead: 4 torrents (meets
both thresholds / old-but-low-ratio / high-ratio-but-young / public with
identical stats) all evaluated correctly against the exact condition
shape deployed — only the one meeting every criterion (private + old +
well-seeded) matched.

## 2026-09-11

### INCIDENT: 15 malware torrents evaded the exe-block rule — root cause: `context: added` gate

andronics reported a completed torrent with an executable despite the
exe-block rule. Investigation found **15 torrents**, not 1 — all
disguised with fake "YTS" branding, subtitle files and an NFO-style
`.txt` as camouflage, with the actual "video" being a ~1GB `.exe` sharing
the exact filename the real video file would have had.

**Root cause**: both `"Remove Archive Based Torrents"` and `"Remove
Torrents Containing Windows Executables"` had `context: added` — meaning
they only ever got evaluated once, at the exact instant qBittorrent fires
its `OnTorrentAdded` webhook. Confirmed via qBittorrent's own log
(`qbittorrent.log`) that the webhook *did* fire correctly for the affected
torrent (`06:22:01`, immediately after "Added new torrent") — so this
was never a webhook-delivery failure. The failure is that `files.name`
isn't necessarily populated yet at that exact moment for a torrent added
by magnet link (no embedded file list — qBittorrent has to fetch it from
peers/DHT after joining the swarm), so the condition evaluated against an
empty/incomplete file list and silently passed. By the time the torrent
*finished* downloading and its files were 100% known (`06:49:31`,
confirmed via the `context=finished` webhook also firing correctly), the
rule's `context: added` restriction meant it was never even attempted —
and no other context (`finished`, `cron`) was ever allowed to re-check it.
Every earlier test tonight of this rule used a pre-built `.torrent` file
upload (metadata known synchronously at add-time), which is exactly why
the bug never surfaced until real magnet-link content hit the queue.

**Remediation** (immediate): retroactively re-triggered `context=added`
for all 15 known hashes against qbt-rules directly — now that their files
are 100% known (all long since finished downloading), the exe-block
condition correctly matched every one and deleted them (`Deleted <name>
(keep_files=False)`). Rescanned all remaining torrents (30) via
`qBittorrent /api/v2/torrents/files` for any other `.exe`/`.scr` —
confirmed zero remaining.

**Fix** (engine/config, not a bug in `qbt-rules` itself — this was a
rules-authoring gap from before this repo's fixes started): removed
`context: added` entirely from both security rules in production
`rules.yml`. With no `context` key, `required_context` is `None`, and
`evaluate()`'s context check is documented to skip entirely when that's
the case ("Rules WITHOUT context execute regardless of runtime context")
— so both rules now evaluate on **every** trigger: `added` (catches the
common case immediately, same as before), `finished` (new — catches
anything whose metadata wasn't ready at add-time, once the download
completes and the full file list is known), and the recurring `cron`
sweep every 30 minutes (new — a persistent safety net that eventually
catches anything that slipped past both of the above for any reason).

**Verified live, isolating the fix from the `added` path specifically**:
temporarily disabled qBittorrent's `autorun_on_torrent_added_enabled` via
its own API (not the rules config) so the `added` webhook wouldn't fire
at all, added a fresh fake-exe test torrent, confirmed it survived (proof
the `added` path was fully bypassed), then manually triggered
`context=cron` alone — confirmed it caught and deleted the torrent.
Re-enabled the autorun setting afterward. This is airtight proof that a
context other than `added` now independently catches what `added` alone
would have missed — the exact failure mode of the incident.

No image rebuild needed (config-only change). No new tests added to the
`qbt-rules` repo itself for this one, since it isn't an engine bug — it's
a rules-authoring pattern (don't gate security rules to a single context
when file metadata isn't guaranteed available at that context) worth
remembering for any future rule design, not something to unit-test in
the engine.
