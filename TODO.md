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

Not yet cut as a release — next patch version (`v0.5.3`?) should include
this fix before the live `compose.yml` rule additions (protected-content,
under-seeded-private force-seed, stalled-torrent pause) go out, since two
of those new rules use bare-list conditions and depend on this fix to work
correctly.

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
