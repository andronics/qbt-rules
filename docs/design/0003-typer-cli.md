# 0003: The Typer CLI

Status: Proposed
Date: 2026-11-03
Authors: Stephen Cox (the clean break: only `qbt-rules serve`, no alias), the apps coordinator and Claude
(the command names, exit codes and the rest, following template-python's skeleton `cli.py`)

## Context

Step 4f of the template migration. The 0.10.x CLI was argparse (`legacy_cli.py`, `arguments.py`): one
flat set of about 28 flags, where the flags present chose what ran (`--serve`, `--list-jobs`,
`--validate`, otherwise "submit a job"). 4a added `serve` as a synonym of `--serve` for the image's
`CMD ["serve"]`. template-python's skeleton is a Typer app with `version`, `config` and `serve`, each
taking only `--config`; every other setting comes from its variable or the config file (interpose).
qBittorrent's "Run external program" hook (`qbt-rules --context torrent-imported --hash %I`) is the main
caller outside the project.

## Decision

- **Commands, following the skeleton** (one verb, or a noun group with verbs as `trackie` would):
  `serve`, `version`, `config`; `validate [RULES_FILE]`; `rules list`; `execute` (was `--context`,
  `--hash`, `--wait`, `--dry-run`); `jobs list`, `jobs status ID`, `jobs cancel ID`; `stats`. `execute`
  matches `POST /api/execute`, so the hook only gains a word:
  `qbt-rules execute --context torrent-imported --hash "%I"`. `validate` stays top level because it
  checks the settings too, not just the rules.
- **A clean break** (Stephen): no `--serve`, no flags-only form, no alias. A command line that starts
  with a removed flag exits 2 with the equivalent new command spelled out (`old_style_hint`), including
  the qBittorrent hook line and the variable that replaced each settings flag.
- **No per-setting flags.** Each command takes `--config`/`-c` only, as in the skeleton; `--server-port`,
  `--client-server-url`, `--log-level` and the rest became their `QBT_RULES_*` variables. `--trace` and
  `--log-level` on a client run never affected the rules (they run in the server's worker), so they're
  not carried over as client options.
- **Output kept:** the 0.10.x tables and detail sections, with `--json` for `--output json`. Results go to
  stdout, errors to stderr. `validate` prints `FILE:LINE:COLUMN: SEVERITY: MESSAGE (PATH)` from
  `rules_validation.validate_rules_text` (the editor's checks), given the notify defaults.
- **Exit codes:** 0 success; 1 a failure (validation errors, a failed, cancelled or timed-out `--wait`, the
  server unreachable or refusing the request, no API key); 2 bad usage or a configuration that can't be
  loaded (Click's usage errors, an invalid `--hash`, the old form, the skeleton's `ConfigError` exit).
- **The client** (`api_client.py`) sends the key as `X-API-Key`, not `?key=`.

## Alternatives considered

- **`run` for `execute`.** Shorter, but reads like "run the server"; `execute` is the API's word.
- **`rules validate` and `list-rules`.** `validate` covers the settings too; `rules list` parallels
  `jobs list`.
- **Per-setting flags on `serve`** (`--port`, ...). The variables cover them, the skeleton has none, and
  two ways to set a value means two sources to explain in `qbt-rules config`.
- **A compatibility shim** for the hook. Decided against by Stephen (clean break); the hint makes the
  failure self-explaining instead.

## Consequences

- Every caller of the flags-only form breaks, by design: the qBittorrent hook, cron jobs, scripts. The
  release notes and the wiki's CLI-Reference "Migrating from 0.10.x" table list each replacement.
- `jobs status`, `jobs cancel`, `jobs list` and `stats` exit 1 when the server refuses the request (0.10.x
  logged the error and exited 0). An invalid `--hash` exits 2 (was 1). `validate` treats an unset
  `qbittorrent.password` and a missing `rules.yml` as warnings, as the server does since 0001.
- The CLI-Reference page's command tables are generated from the Typer app again.
- `log_setup` lost its client mode (bare console lines): only `serve` configures logging now.
