# 0001: Configuration on interpose, config in /etc/qbt-rules, state in /var/lib/qbt-rules

Status: Accepted
Date: 2026-11-03
Authors: Stephen Cox (the path and CLI decisions), the apps coordinator and Claude (the rest, following
template-python's conventions)

## Context

Step 4b of the template migration. 0.10.x resolved settings with its own engine (`config_loader.py`:
`resolve_config`, `ENV_VAR_MAP`, `${VAR}` expansion) and kept everything in one directory: `/config` in
0.10.x, `/var/lib/qbt-rules` after 4a (config.yml, rules.yml, the database, the log and `.history/`),
seeded from packaged defaults on first start. template-python's settings engine is interpose (its decision
0003); its layout is config in `/etc/<project>` and state in `/var/lib/<project>`, and the image's smoke
test starts the container with no configuration. Deployments (the Unraid template, homelab-k8s) set
`QBT_RULES_*` variables, so their names must keep working.

## Decision

Stephen decided (2026-11-03): new paths only with no `/config` fallback, a clean break, and accepting a
one-time logout. The rest below follows template-python's conventions (interpose, console logging, starting
with no configuration) and was chosen in review.

- **Settings** are interpose `Setting`s in `config.py`, with keys chosen so that every documented variable
  keeps its name: `QBT_RULES_<SECTION>_<FIELD>` and its `_FILE` form, `QBT_RULES_DRY_RUN` (key `dry_run`,
  was `engine.dry_run`), `QBT_RULES_RULES_FILE` (`rules.file`, documented in 0.10.x but never read; now
  it is). Seven are secrets (`Secret`, revealed only where the legacy server's dicts are built).
- **Paths (new paths only, no `/config` fallback, no detection of an old directory):**
  `/etc/qbt-rules/config.yaml` (the template's name; `QBT_RULES_CONFIG`, `--config`), `rules.yml` beside it
  (writable: the editor saves it), and `state_dir` `/var/lib/qbt-rules` holding `qbt-rules.db` and the
  editor's `.history/`. The log goes to the console (the template's convention); `logging.file` adds a
  rotated file. A path setting under `/config` is refused.
- **First start:** nothing is copied. No `config.yaml` means defaults; no `rules.yml` means no rules, and
  the editor creates it on its first save. The packaged defaults became `contrib/qbt-rules.example.yaml`
  and `contrib/rules.example.yml`.
- **No API key** is not an error: the server starts, authenticated requests get a 503 naming what to set,
  and `/api/health` stays 200 with `config_problems`. The 0.10.x placeholder key counts as unset.
- **Port:** `listen.port` / `QBT_RULES_LISTEN_PORT` (the image's HEALTHCHECK reads it) is canonical;
  `server.port` / `QBT_RULES_SERVER_PORT` are aliases (a warning at startup; both set to different values is
  refused). `server.host` is an alias of `listen.host` the same way.
- **What interpose doesn't do is `load_config`'s:** `${VAR}` / `${VAR:-default}` in the file (fed to
  interpose as the setting's variable, unless a real one is set), the aliases, the `schedule` list and its
  indexed `QBT_RULES_SCHEDULE_<N>_CRON` / `_CONTEXT` variables, and refusing `CONFIG_DIR`,
  `QBT_RULES_CONFIG_DIR`, `QBT_RULES_LOG_LEVEL`, `--config-dir`, `engine.dry_run` and a `config.yml` left
  beside a missing `config.yaml`, each with what to use instead.

## Alternatives considered

- **Re-point `QBT_RULES_CONFIG_DIR` at the new layout:** it named one directory for config and state alike,
  so any re-pointing guesses wrong for one of them. Refused with the two variables that replace it.
- **Keep copying the packaged defaults:** the template's container starts with no configuration, and the
  old default `config.yml` shipped a public API key that the server then accepted.
- **`server.port` canonical:** the template-owned HEALTHCHECK reads only `QBT_RULES_LISTEN_PORT`.
- **Warn about unknown keys (#11):** interpose has no hook for it, so it stays open.

## Consequences

Breaking for deployments: they move files from `/config` (the wiki's In-Depth-Configuration page, Migrating
from 0.10.x, lists each) and mount two paths. Rollback is the old image with the untouched `/config`. The
Unraid template and homelab-k8s change in step with the release. Wiki pages changed: In-Depth-Configuration
(the settings table is generated from `SETTINGS` again), Deployment, Quick-Start, CLI-Reference,
Troubleshooting, FAQ, HTTP-API-Reference, Architecture-Internals.

## Open questions

None.
