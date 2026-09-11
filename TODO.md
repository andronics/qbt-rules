# qbt-rules — TODO

Currently-open items only. Resolved bugs and their postmortems live in
`BUGS.md`; `PLAN.md` is the (mostly complete) v0.4.0 architecture doc.

## Open

- [ ] **`release.yml` version-bump commit lands on `main` after the tag is
      already pushed** — the tag and `main`'s release state diverge
      slightly (the tag never contains its own version-bump commit).
      Cosmetic, low priority.
- [ ] **`softprops/action-gh-release@v1`'s `make_latest` input is silently
      ignored** (unsupported by that action version) — releases still get
      created fine, but "mark as latest" on GitHub's Releases page
      probably isn't doing anything. Needs a newer action version or drop
      the input.
- [ ] **No `read:packages` scope on the `andronics` GitHub CLI token** —
      `gh api` can't query package versions directly; worked around by
      hitting the GHCR OCI API with an anonymous pull token. Minor
      friction for future debugging sessions, not blocking.
- [ ] **Legacy `/config/scripts/archive_filter.py` and `rules_engine.py`**
      sitting unused inside the deployed `qbittorrent-rules` container
      (pre-package prototypes, not referenced by `config.yml`). Harmless
      but confusing. Cleanup candidate on the deploy side, not this repo.

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
