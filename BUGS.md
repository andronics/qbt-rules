# qbt-rules — Bug Log

Record of bugs found, root-caused, and fixed (or explicitly not fixed, with
why) across this project's development and production deployment. Newest
first. `CHANGELOG.md` is the user-facing release history; this file is the
technical postmortem detail behind the entries that matter.

---

## Added broadened malware blocklist + structural "no video file" security rule

Direct follow-up to the malware-evasion incident above. The exe-block rule
only ever caught the specific `.exe`/`.scr` extensions used in that
incident; a disguise using any other Windows-executable-adjacent extension
would have sailed through untouched, same as before the fix.

- **Broadened `has-executable`**: `.exe|.scr` → `.exe|.scr|.bat|.cmd|.com|
  .msi|.vbs|.ps1|.scf|.pif|.lnk|.jar`. Same rule, same regex-anchor
  approach, just a longer list of Windows-executable/script extensions.
- **New rule: "Remove Fake Video Torrents With No Video File"** — the
  actual incident torrent had *zero* real video files, just the fake
  payload plus subtitles/an image as camouflage. Rather than only relying
  on an extension blocklist (which only catches extensions someone
  thought to list), this catches the pattern structurally: any torrent in
  a video-only category (`tv`, `movies`, `standup`) that contains *none*
  of `.mkv/.mp4/.avi/.m4v/.wmv/.mov/.ts/.m2ts/.webm` gets deleted,
  regardless of what disguise technique produced that state.
- **Explicitly excluded by design, not by omission**: `audiobooks`,
  `ebooks`, `music`, `software`, and any uncategorized torrent are outside
  the `is-video-category` condition entirely — a legitimate audiobook
  (audio files, no video) or a future software download (executables by
  definition) will never even reach this check. Confirmed the `software`
  category has zero torrents in it today, so no live conflict, but the
  category exists in `categories.json` for a reason and this scoping
  keeps it usable for that purpose going forward.

**Verified live** with four real test torrents added via the qBittorrent
API, isolating each mechanism:
1. `category=tv`, fake payload named as the release + a `.exe` — deleted
   by the (broadened) exe-block rule, as before.
2. `category=tv`, same shape but a `.bat` instead of `.exe` — deleted by
   the *broadened* extension list specifically (proves the extension
   addition works, not just the pre-existing `.exe` case).
3. `category=audiobooks`, real `.mp3`, no video file — **survived**,
   proving the category exclusion actually protects legitimate non-video
   content as designed.
4. `category=tv`, no malicious extension at all (just a `.txt` and
   `.jpg`, no video file) — deleted specifically by the new "Remove Fake
   Video Torrents With No Video File" rule, isolating it from the
   extension blocklist and proving the structural check works
   independently.

No image rebuild needed (pure `rules.yml` config change, existing
operators only). `Loaded 11 rules` (was 10).

---

## `docker-build.yml` ran a full multi-arch build on every doc-only commit

**Symptom**: found by chance while verifying the newly-restored
`read:packages` scope — `gh api /user/packages/container/qbt-rules/versions`
returned **251 image versions** for a project with nowhere near that many
real code changes. Cross-checked against `gh run list --workflow=
docker-build.yml`: every single doc-only commit tonight (`TODO.md`/
`BUGS.md` updates with zero source changes) had triggered a full
multi-arch build and published 2-3 more image versions (one manifest list
+ one child manifest per platform) to the registry.

**Root cause**: `docker-build.yml`'s `push`/`pull_request` triggers had no
path filtering at all — every push to `main`, regardless of what changed,
ran the full build-and-publish job.

**Fix**: added `paths-ignore: ['**.md', 'LICENSE', 'docs/**']` to both the
`push` and `pull_request` triggers. Deliberately narrow — doesn't touch
anything that could actually affect the image (`src/`, `Dockerfile`,
`pyproject.toml`, `requirements*.txt`, `config/`, `scripts/`, workflow
files themselves all still trigger normally).

**Verified live**, both directions: pushed a commit that edited the
workflow file itself (not doc-only) — build correctly still ran. Then
pushed a pure `TODO.md` edit — confirmed via `gh run list` that only `CI`
fired, no `Build and Publish Docker Image` run at all for that commit.

Known, accepted residual risk: GitHub Actions' `paths-ignore` applies
uniformly to the whole `push` trigger, including the `tags: 'v*'` pattern
— there's no way to exempt tag pushes from the same filter within one
`on.push` block. In practice this can't actually skip a real release,
since `scripts/bump-version.sh` always touches `pyproject.toml` and
`src/qbt_rules/__version__.py` as part of any legitimate version bump, so
a tag push is never doc-only. Worth knowing if the release process ever
changes.

**Status**: Fixed.

**Follow-up — the "251 accumulated versions" turned out not to be
waste.** Built the actual reference graph before deleting anything:
fetched every one of the 56 currently-published tags' manifests, and for
each multi-arch index, its child manifest digests. Result: of 256 total
versions, **255 were legitimately referenced** by a current tag (every
`main-<sha>` tag permanently owns its own per-platform child manifests —
that's the tagging scheme working as designed, not clutter). Only **1**
version was genuinely orphaned (from 2026-01-13, pre-dating this session's
work entirely). The "251 versions, that's a lot of waste" framing used to
propose this cleanup was wrong — it was based on total version count
without checking what was actually still referenced.

Deleted just that 1 confirmed-orphaned version after re-verifying it was
still untagged and unreferenced immediately before deletion (`DELETE
/user/packages/container/qbt-rules/versions/640970704` → `204`). Verified
afterward: total version count dropped by exactly 1 (256 → 255), all 56
tags remained intact, and `docker pull ghcr.io/andronics/qbt-rules:latest`
still succeeded.

The real opportunity to shrink the registry is pruning the 50+ permanent
`main-<sha>` tags themselves (one per historical commit, most of which
will never be pulled again) — but that's revoking previously-published
tags, a different and more consequential decision than deleting orphaned
data, deliberately left for a separate explicit decision rather than
folded into this cleanup.

---

## `release.yml`/`main` version-bump divergence — already resolved, closing the TODO

**Symptom** (as originally logged): `release.yml` used to commit a
version-bump to `main` *after* the tag was already pushed, so the tag and
`main`'s release state diverged slightly — the tag itself never contained
its own version-bump commit.

**Investigation**: re-checked the current `release.yml` while working
through the TODO list. The "Commit version update" step this described no
longer exists at all — it was removed entirely back when the
version/tag-mismatch bug was fixed (see the `v0.5.2` entry below):
`release.yml` now hard-fails via "Verify version matches tag" instead of
ever committing anything itself. The only thing that commits a version
bump is `scripts/bump-version.sh`, run locally *before* the tag is
created — so by construction there's nothing left for a tag to diverge
from.

**Verified**: checked `git merge-base --is-ancestor` for the three most
recent tags (`v0.5.7`, `v0.5.8`, `v0.5.9`) against `main` — each tag's
commit is a direct ancestor of `main`, not a divergent branch. `main`
simply moves forward afterward with normal, unrelated commits, which is
expected, healthy history, not the bug originally described.

**Status**: Already fixed as a side effect of the earlier version-mismatch
fix; nobody had gone back to close this TODO item until now. No code
change needed here.

---

## `release.yml`'s `make_latest` input silently did nothing (v0.5.9)

**Symptom**: every "Create Release" step logged `Unexpected input(s)
'make_latest', valid inputs are [...]` — release.yml had passed
`make_latest: true` since it was written, but it was silently ignored
every single time. Releases were created fine; "mark as latest" on
GitHub's Releases page was never actually happening.

**Root cause**: `softprops/action-gh-release@v1` — confirmed by pulling
`v1`'s actual `action.yml` from GitHub: zero mentions of `make_latest`
anywhere in it. The input simply doesn't exist in v1. It was added in v2
and remains in v3 (the current major version, which also runs on Node 24
rather than v1's deprecated Node 20 — a bonus fix for the "Node.js 20 is
deprecated" warnings that were showing up everywhere in CI).

**Fix**: bumped to `softprops/action-gh-release@v3`. Confirmed first that
every input `release.yml` actually uses (`tag_name`, `name`, `body_path`,
`draft`, `prerelease`, `make_latest`) is unchanged in v3 — no renames, a
safe drop-in bump. Used the floating `@v3` tag to match every other
third-party action in these workflows (`actions/checkout@v4`,
`docker/build-push-action@v5`, etc. — none of them pinned to an exact
version either).

**Verified**: cut a real release (`v0.5.9`). The "Unexpected input(s)"
warning is gone from the Actions log. More importantly, confirmed the
actual *behavior* now works, not just the absence of a warning: `gh
release list` shows `v0.5.9` marked `Latest`, with `v0.5.8` correctly
un-marked, and `GET /repos/andronics/qbt-rules/releases/latest` resolves
to `v0.5.9`.

**Status**: Fixed.

---

## `SQLiteQueue` missing `busy_timeout` caused real thread-race failures (v0.5.8)

**Symptom**: found while investigating the `pytest` thread-race warnings
(a TODO item) — `sqlite3.OperationalError: database is locked` raised
inside worker threads under `TestSQLiteQueueThreadSafety`, in
`test_concurrent_dequeue`, `test_dequeue_atomic_operation`, and
`test_cancel_job_transaction_safe`. Confirmed this was **not** test-harness
noise — it's a real, 100%-reproducible bug that just happened to only ever
surface as a warning rather than a failure, because pytest doesn't fail on
`PytestUnhandledThreadExceptionWarning` by default.

**Root cause**: `_get_connection()` never set `PRAGMA busy_timeout`
(SQLite's default is `0` — fail immediately on a contended lock instead of
waiting). `_transaction()` used a plain deferred `BEGIN`, so concurrent
threads each acquire a *read* lock via their own `SELECT` and only try to
upgrade to a *write* lock afterward. When multiple threads do this at
nearly the same time, none of them will release their read lock until they
win or their transaction ends — a genuine deadlock among mutually-blocking
readers, not a "wait a bit longer" problem. Confirmed empirically before
touching source: adding `busy_timeout` alone did **not** fix it (still
failed ~4/5 in an isolated repro, completing near-instantly — proof it
wasn't actually waiting). WAL mode doesn't help either; SQLite only ever
allows one writer at a time regardless of journal mode.

**Fix**: `BEGIN IMMEDIATE` instead of plain `BEGIN`, so the write lock is
acquired up front — only one transaction is ever "in" at a time, and
everyone else cleanly queues via `busy_timeout` (set to 5000ms) instead of
racing to upgrade. Verified empirically: `BEGIN IMMEDIATE` + `busy_timeout`
= 5/5 succeed; `busy_timeout` alone = still 4/5 fail.

**Verified**: hardened the three affected tests to explicitly capture and
assert on thread exceptions instead of relying on pytest's default
warn-only behavior — confirmed by *reverting* the fix that these now fail
loudly with a real `AssertionError` (`dequeue() raised in 2 thread(s):
[OperationalError('database is locked'), ...]`) instead of just warning,
then re-applied the fix. Full suite: 1048 passed, `sqlite_queue.py` 98.93%
coverage, zero thread warnings for the first time. Deployed as `v0.5.8`
(no production redeploy strictly needed — production's single worker
thread never calls `dequeue()`/`cancel_job()` concurrently today, but the
`SQLiteQueue` class itself is now actually thread-safe as advertised,
which matters if `server.workers`/gunicorn ever runs with more than one
worker).

**Status**: Fixed.

---

## `increase_priority`/`decrease_priority`/`set_top_priority`/`set_bottom_priority` never wired into the action dispatch (v0.5.7)

**Symptom**: found while verifying `advanced-rules-example.yml` Rule 9
end-to-end (a TODO item, following up on the actions-ref splice fix
below). The splice fix itself checked out — all 8 actions in Rule 9
resolved as flat dicts and no longer threw the old `TypeError` — but
actually *executing* the resolved rule surfaced a second, separate gap:
`increase_priority` (used by `actions.process-hd-content`) fell through to
`ActionExecutor`'s "Unknown action type" branch, silently did nothing, and
logged an ERROR every time the rule matched.

**Root cause**: `api.py`'s `QBittorrentAPI` already had all four priority
methods (wrapping qBittorrent's real priority endpoints), they were just
never wired into `_execute_action`'s dispatch table.

**Fix**: added all four as real action types, matching the existing
dispatch pattern exactly. Also added the same four methods to the shared
`MockAPI` test fixture (`tests/conftest.py`), which didn't have them
either.

**Verified**: 4 new unit tests, plus a new integration test file
(`tests/integration/test_advanced_example.py`) that loads the real
committed `advanced-rules-example.yml` (not a re-typed copy) and drives
Rule 9 through the actual `RulesEngine.run()` path — both the matching and
non-matching cases — so this stays verified going forward. Full suite:
1048 passed (was 1042), `engine.py` 100% coverage. Deployed as `v0.5.7`
(no production redeploy needed — the live `rules.yml` doesn't use any
priority actions today).

**Status**: Fixed.

---

## INCIDENT: 15 malware torrents evaded the exe-block rule (2026-09-11)

**Symptom**: andronics found a completed torrent with an executable despite
the "Remove Torrents Containing Windows Executables" rule. Investigation
found 15, not 1 — all disguised with fake "YTS" branding, subtitle files,
and an NFO-style `.txt` as camouflage, with the actual "video" being a
~1GB `.exe` sharing the exact filename the real video file would have had.

**Root cause**: both security rules (`"Remove Archive Based Torrents"` and
`"Remove Torrents Containing Windows Executables"`) had `context: added` —
evaluated exactly once, at the instant qBittorrent's `OnTorrentAdded`
webhook fires. Confirmed via `qbittorrent.log` that the webhook *did* fire
correctly (`06:22:01`, immediately after "Added new torrent") — not a
webhook-delivery failure. The real issue: `files.name` isn't necessarily
populated yet at that exact moment for a torrent added by magnet link (no
embedded file list — qBittorrent fetches it from peers/DHT after joining
the swarm), so the condition evaluated against an empty/incomplete file
list and silently passed. By the time the torrent *finished* downloading
and its files were 100% known (`06:49:31`, `context=finished` webhook also
confirmed firing), the rule's `context: added` restriction meant it was
never even attempted again — and no other context (`finished`, `cron`)
was ever allowed to re-check it. Every test of this rule before the
incident used a pre-built `.torrent` file upload (metadata known
synchronously at add-time), which is exactly why the bug never surfaced
until real magnet-link content hit the queue.

**Remediation** (immediate): retroactively re-triggered `context=added`
for all 15 known hashes — now that their files were 100% known, the
exe-block condition correctly matched and deleted every one. Rescanned all
remaining torrents via `/api/v2/torrents/files` for any other `.exe`/
`.scr` — confirmed zero remaining.

**Fix**: removed `context: added` entirely from both security rules in
production `rules.yml`. With no `context` key, `required_context` is
`None`, and `evaluate()` skips the context check entirely in that case —
so both rules now evaluate on *every* trigger: `added` (unchanged),
`finished` (new — catches anything whose metadata wasn't ready at
add-time), and the recurring 30-minute `cron` sweep (new — a persistent
safety net).

**Verified**: isolated the fix from the `added` path specifically by
temporarily disabling qBittorrent's `autorun_on_torrent_added_enabled` via
its own API, adding a fresh fake-exe test torrent, confirming it survived
(proof `added` was fully bypassed), then manually triggering `context=cron`
alone — confirmed it caught and deleted the torrent. Re-enabled autorun
afterward.

**Status**: Fixed and deployed. Not an engine bug — a rules-authoring
pattern (don't gate security rules to a single context when file metadata
isn't guaranteed available at that context). No engine tests added for
this one; the lesson is about rule design, not `qbt-rules` code.

---

## Negation operators against list fields used ANY instead of ALL (v0.5.6)

**Symptom**: found while drafting a `tagged-private`/`tagged-public`
condition pair — the exact `not_contains "private"` pattern already live
in production's "Delete Public Torrents" rule.

**Root cause**: `info.tags` resolves to a list (`parse_tags` splits on
comma). `_apply_operator`'s collection handling applied `any(...)`
uniformly across every operator — correct for positive checks
(`contains`/`==`/`in`), wrong for negations (`not_contains`/`!=`/`not_in`):
`any(item satisfies negation)` is true if even one item fails to match,
which is true for almost any multi-item collection. For tags
`['private', 'iptorrent.com']`, `not_contains "private"` incorrectly
returned `True` because the `iptorrent.com` tag alone satisfied "doesn't
contain private," regardless of the `private` tag right next to it.
Confirmed all production torrents at the time had this exact multi-tag
shape; they were incidentally shielded by the `protected-content` category
check, but a real window existed (before that category reassignment)
where a private torrent could have wrongly matched the public-deletion
rule.

**Fix**: when `actual` is a list, negation operators now use `all(...)` —
true only when *no* item positively matches. Positive operators unchanged.

**Verified**: 7 new regression tests, full suite 1042 passed (was 1035),
`engine.py` back to 100% coverage. Deployed as `v0.5.6`, confirmed live
against real production torrents carrying the affected tag shape.

**Status**: Fixed.

---

## `$ref: actions.X` breaks when `actions.X` is a list (v0.5.4)

**Symptom**: found deploying new rules — "Tag iptorrent.com Trackers"
(using `$ref: actions.tag-private` alongside an inline `add_tag`) matched
correctly but crashed on execute: `TypeError: list indices must be
integers or slices, not str`.

**Root cause**: `refs.actions.*` blocks are lists (an action sequence).
Referencing one via `$ref: actions.x` from inside a rule's own `actions:`
list (also a list) didn't splice/flatten — `_expand_refs`'s list-handling
just mapped each item through expansion and returned the result in place,
nesting the ref's list value inside the parent list instead of merging it.
Not limited to mixed ref+inline usage — a rule using only a single action
ref broke identically. Also affected `advanced-rules-example.yml` Rule 9,
which mixes multiple action refs with inline actions the same way.

**Fix**: `_expand_refs`'s list-handling now tracks whether each item was
itself a `$ref` node; if its expansion is a list, it's spliced (`.extend()`)
into the parent instead of appended as a nested element. Only triggers for
items that were actually `$ref` nodes. `conditions.*` refs are unaffected
by construction (they resolve to dicts, so nesting as a single list item
was already correct).

**Verified**: 9 existing tests had encoded the old nested-list shape as
expected behavior (effectively asserting the bug) — corrected all of them.
4 new regression tests. Full suite 1032 passed (was 1028). Deployed as
`v0.5.4`, production restored to actually use the action refs (reverting
the temporary inlining workaround) to prove the fix live in the exact
scenario that crashed.

**Status**: Fixed.

---

## Bare-list `conditions:` silently matched everything (v0.5.3)

**Symptom**: found while drafting new rules using the same bare-list style
`advanced-rules-example.yml` uses throughout
(`conditions: [{$ref: ...}, {none: [...]}]`, no `all:`/`any:` wrapper).

**Root cause**: `engine.py`'s `evaluate()` only checked `'all' in
conditions`, `'any' in conditions`, `'none' in conditions`. When
`conditions` is a `list` of dicts rather than a dict, none of those `in`
checks can ever be true (`in` on a list checks for a matching *element*,
not a dict key), so it fell through to `return True` unconditionally.
Every one of the 10 rules in `advanced-rules-example.yml` matched every
torrent regardless of its conditions — confirmed empirically before
touching the fix.

Also found while investigating: `contains` with a *list* value threw
inside `_apply_operator` (`'in <string>' requires string as left operand,
not list`), silently swallowed by `evaluate()`'s broad `try/except` into
an always-`False` result — dangerous if that pattern ever landed inside a
`none:` protection clause. (Later addressed properly — see "Feature:
`contains`/`not_contains` accept a list value" below.)

**Fix**: a bare list is now treated as an implicit `{'all': [...]}`.
Purely additive — dict-wrapped `conditions:` is unaffected.

**Verified**: 4 new regression tests. Full suite 1028 passed (was 1024),
`engine.py` 100% coverage. Deployed as `v0.5.3`.

**Status**: Fixed. Side effect: `advanced-rules-example.yml` did not need
rewriting — its bare-list style is now genuinely supported.

---

## `release.yml` silently re-bumped version after the tag already existed (v0.5.2)

**Symptom**: `/api/version` on freshly deployed `v0.5.1` reported internal
version `"0.5.0"`.

**Root cause**: `v0.5.1` was tagged manually (`git tag && git push`)
instead of via `scripts/bump-version.sh`, the only thing that bumps
version files *before* creating the tag. `release.yml`'s old "Update
version in code" + "Commit version update" steps silently re-bumped and
re-committed to `main` *after* the tag already existed — too late for
`docker-build.yml`, which had already built from the pre-bump commit the
tag pointed to.

**Fix**: `release.yml` no longer auto-corrects. It now hard-fails
("Verify version matches tag") if the tagged commit's version files don't
already match the tag name, forcing `bump-version.sh` to be used. Also
fixed `bump-version.sh`, which only ever bumped `__version__.py` — now
bumps `pyproject.toml` too.

**Verified**: locally (matching and deliberately-mismatched cases), then
live in `v0.5.2` — "Verify version matches tag" passed for real in GitHub
Actions, and `ghcr.io/andronics/qbt-rules:0.5.2 --version` correctly
reported `v0.5.2` for the first time ever in this project.

**Status**: Fixed.

---

## `docker-build.yml` produced an invalid tag on every version-tag push

**Symptom**: every tag-triggered release build failed. No `vX.Y.Z` image
had ever actually been published to GHCR — confirmed via
`ghcr.io/v2/andronics/qbt-rules/tags/list`, which only showed `main`,
`latest`, `main-<sha>`. Production's `compose.yml` referenced
`ghcr.io/andronics/qbt-rules:dev`, a tag that didn't exist in the registry
at all — the running container was on a locally-cached image from
2025-12-20, manually tagged at some point.

**Root cause**: the tag list included `type=sha,prefix={{branch}}-`, which
only resolves on branch-triggered builds. On a tag push, `{{branch}}` is
empty, producing the invalid tag `-<sha>` and aborting the whole
multi-arch build before any of the other (valid) tags could be pushed.

**Fix**: gated the sha-prefix tag to branch events only
(`enable=${{ github.ref_type == 'branch' }}`), and while fixing it, also
renamed the floating "latest build from main" tag from the
never-actually-published `dev` to `edge`, with `latest` now only applying
to tag-triggered (semver) builds.

**Verified**: cut `v0.5.1` — both `release.yml` and `docker-build.yml`
succeeded on the real tag-push trigger for the first time. Confirmed
`0.5.1`, `0.5`, `0`, `latest`, `edge` all present in the registry.

**Status**: Fixed. Production later pinned to a real version instead of
the phantom `:dev`.

---

## `ci.yml` failed on every single run since it was added (Dec 2025 – Sep 2026)

**Symptom**: CI red on every commit for ~9 months.

**Root cause**: two independent, unconditional failures —
1. The "Check for common issues" credential-detection regex
   false-positived on its own docstring in `config.py`
   (`config_key='server.api_key'` matches the pattern) and hard-failed
   with `exit 1` on any match, benign or not.
2. The "Validate configuration examples" step referenced
   `config/config.example.yml` / `config/rules.example.yml`, which don't
   exist — renamed to `config/config.default.yml` / `rules.default.yml`
   at some point, workflow never updated.

**Fix**: excluded the `config_key=` false-positive pattern from the
credential check; corrected the file paths.

**Verified**: CI green for the first time since it was introduced.

**Status**: Fixed.

---

## Known, not fixed (by design or low priority)

- **`contains`/`not_contains` accepting a list value** isn't a bug fix so
  much as a feature added in `v0.5.5` to close the silent-failure gap
  noted above — `contains` with a list `value` now matches if *any* item
  is a substring; `not_contains` only if none are. Mentioned here for
  completeness since it originated from a bug investigation.
- **`release.yml` commits the version-bump to `main` *after* the tag is
  already pushed** — the tag and `main`'s "release state" diverge
  slightly (the tag never contains its own version-bump commit). Cosmetic,
  low priority.
- **`softprops/action-gh-release@v1`'s `make_latest` input is silently
  ignored** (`Unexpected input(s) 'make_latest'`) — releases still get
  created fine, but "mark as latest" on GitHub's Releases page probably
  isn't doing anything. Would need bumping to a newer action version or
  dropping the input.
- **`pytest` thread-race warnings** in `test_sqlite_queue.py`
  (`sqlite3.OperationalError: database is locked` under
  `TestSQLiteQueueThreadSafety`) — not yet determined whether this is a
  real concurrency issue in `sqlite_queue.py`'s locking or just
  test-harness noise. Non-fatal today.
