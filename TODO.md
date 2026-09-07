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
- [ ] Pin `qbittorrent` compose's `rules` service to a real, reliably-published
      version tag once the fixed workflow produces one (deferred until after
      this fix + a verified tag-triggered build succeeds).
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

### Decided
- Floating "latest build from main" tag renamed to `edge` (was `dev`, which
  never actually existed as a real published tag). `latest` now only applies
  to tag-triggered (semver) builds, matching the conventional meaning of
  "latest stable release." `compose.yml` in the qbittorrent deploy needs to
  move from `:dev` to `:edge` (or a pinned `vX.Y.Z` once available) as a
  follow-up — not done yet, tracked above.
