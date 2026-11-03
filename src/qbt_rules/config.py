"""Configuration.

Every setting can come from four places, and the first one that has it wins:

1. ``QBT_RULES_<NAME>_FILE``: a file that holds the value (Docker / Kubernetes secrets)
2. ``QBT_RULES_<NAME>``: an environment variable
3. the YAML config file (``QBT_RULES_CONFIG``, default ``/etc/qbt-rules/config.yaml``)
4. the default in SETTINGS

``<NAME>`` is the dotted key in upper case, with the dots as underscores:
``qbittorrent.host`` is ``QBT_RULES_QBITTORRENT_HOST``.

The engine (lookup order, strict coercion, ``check=``, ``Secret``) is interpose's
(template-python decision 0003); this module holds the project's settings and its own rules.
Its contract with the template-owned files (``cli.py``, ``scripts/gen-wiki.py``): it exports
SETTINGS (each item has key, env, default, help, secret, is_list), CONFIG_ENV, Config (with
``sources``), ConfigError and ``load_config(path=None, environ=None)``.

The keys are chosen so that every variable keeps the name it had before interpose
(``QBT_RULES_<SECTION>_<FIELD>``, ``QBT_RULES_DRY_RUN``, ``QBT_RULES_RULES_FILE``): Unraid
templates and other deployments set those. What interpose doesn't do, load_config adds:

- ``${VAR}`` and ``${VAR:-default}`` in the YAML file are expanded from the environment.
- ``schedule`` (a list of ``{cron, context}``) comes from the file, or from the indexed
  ``QBT_RULES_SCHEDULE_<N>_CRON`` / ``_CONTEXT`` variables, which replace it.
- ``server.host`` and ``server.port`` (key and variable) are aliases of ``listen.host`` and
  ``listen.port``, the names the image's HEALTHCHECK reads.
- What was removed or renamed is refused with its replacement (REFUSED_VARIABLES,
  RENAMED_KEYS, REMOVED_KEYS), and so is a path under the old ``/config`` volume.
- A missing setting the server can start without (the API key) is listed in
  ``Config.problems``, for ``/api/health`` and the startup log, rather than refused. The
  placeholder key the 0.10.x default config.yml shipped with counts as missing: it is public.

Values are never logged; only where each one came from is.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from croniter import croniter
from interpose.secret import Secret
from interpose.settings import (
    ConfigError,
    Setting,
    Settings,
    Value,
    non_negative,
    one_of,
    port,
    positive,
)

__all__ = [
    "CONFIG_ENV",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_STATE_DIR",
    "ENV_PREFIX",
    "HISTORY_DIRNAME",
    "LOG_LEVELS",
    "PLACEHOLDER_API_KEY",
    "SETTINGS",
    "Config",
    "ConfigError",
    "ScheduleEntry",
    "duration_seconds",
    "load_config",
]

ENV_PREFIX = "QBT_RULES_"
DEFAULT_CONFIG_PATH = Path("/etc/qbt-rules/config.yaml")
DEFAULT_STATE_DIR = Path("/var/lib/qbt-rules")
RULES_FILENAME = "rules.yml"
DB_FILENAME = "qbt-rules.db"
# The rules editor's backups of rules.yml, in the state directory
HISTORY_DIRNAME = ".history"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
NOTIFY_SERVICES = ("generic", "discord", "slack", "ntfy")
# The api_key the 0.10.x default config.yml shipped with: public, so never a real key
PLACEHOLDER_API_KEY = "your-secure-api-key-here-generate-a-random-key"
PLACEHOLDER_SOURCE = "the 0.10.x placeholder, ignored"

# The 0.10.x volume. Nothing reads or writes it any more, and there is no fallback to it.
LEGACY_DIR = PurePosixPath("/config")

_MOVED = (
    "qbt-rules 0.11 keeps its config in /etc/qbt-rules (config.yaml, rules.yml) and its state "
    "in /var/lib/qbt-rules (see the wiki's In-Depth-Configuration page, Migrating from 0.10.x)"
)
_NO_MULTIPROC = (
    "is no longer read: qbt-rules 0.11 is one process, and its metrics live in memory "
    "(interpose, not prometheus_client), so there is no multiprocess directory. Remove it; "
    "metrics.enabled (QBT_RULES_METRICS_ENABLED) alone turns /metrics on"
)
# Variables that no longer apply, and what to set instead. Each is refused at startup.
REFUSED_VARIABLES = {
    "CONFIG_DIR": (
        f"CONFIG_DIR is no longer read: {_MOVED}. Remove it; to use another config file, "
        "set QBT_RULES_CONFIG (rules.yml is read beside it) and QBT_RULES_STATE_DIR"
    ),
    "QBT_RULES_CONFIG_DIR": (
        f"QBT_RULES_CONFIG_DIR is no longer read: {_MOVED}. Remove it; to use another config "
        "file, set QBT_RULES_CONFIG (rules.yml is read beside it) and QBT_RULES_STATE_DIR"
    ),
    "QBT_RULES_LOG_LEVEL": (
        "QBT_RULES_LOG_LEVEL is not a qbt-rules setting: use QBT_RULES_LOGGING_LEVEL"
    ),
    "QBT_RULES_METRICS_MULTIPROC_DIR": f"QBT_RULES_METRICS_MULTIPROC_DIR {_NO_MULTIPROC}",
    "PROMETHEUS_MULTIPROC_DIR": f"PROMETHEUS_MULTIPROC_DIR {_NO_MULTIPROC}",
}
# Config-file keys that were renamed: old dotted key -> new one
RENAMED_KEYS = {"engine.dry_run": "dry_run"}
# Config-file keys that were removed, and why. Each is refused at startup.
REMOVED_KEYS = {"metrics.multiproc_dir": f"metrics.multiproc_dir {_NO_MULTIPROC}"}
# Old key -> the key it is an alias of, in the file and as a variable
ALIASES = {"server.host": "listen.host", "server.port": "listen.port"}

_ENV_REF = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def one_process(value: Value) -> None:
    """server.workers: only 1. Gunicorn's worker processes are gone (template-python 0008)."""
    positive(value)
    if value != 1:
        raise ValueError(
            f"must be 1, got {value}: qbt-rules runs one process now (uvicorn, no Gunicorn), "
            "so its worker and scheduler run exactly once. Remove server.workers (or "
            "QBT_RULES_SERVER_WORKERS); jobs run one at a time either way"
        )


def duration_seconds(value: str) -> int | None:
    """Seconds in a duration: ``604800``, ``7d`` (s, m, h, d, w) or ``30 days``. None: invalid."""
    text = value.strip().lower()
    if text.isdigit():
        return int(text)
    match = re.fullmatch(r"(\d+)\s*([smhdw])", text)
    if match:
        return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]
    match = re.fullmatch(r"(\d+)\s*(second|minute|hour|day|week)s?", text)
    if match:
        return int(match.group(1)) * _UNIT_SECONDS[match.group(2)[0]]
    return None


def _duration(value: Value) -> None:
    if duration_seconds(str(value)) is None:
        raise ValueError(f"expected seconds or a duration such as 7d or 3 hours, got {value!r}")


def _decimal(value: Value) -> None:
    """A positive number written as text (interpose has no float settings)."""
    try:
        number = float(str(value))
    except ValueError:
        raise ValueError(f"expected a number, got {value!r}") from None
    if not number > 0:  # also rejects nan
        raise ValueError(f"must be greater than 0, got {value!r}")


def _not_legacy_path(value: Value) -> None:
    """Refuse a path on the 0.10.x /config volume: it would silently point at nothing."""
    path = PurePosixPath(str(value))
    if path == LEGACY_DIR or LEGACY_DIR in path.parents:
        raise ValueError(
            f"{value} is under /config, which is no longer used: {_MOVED}. Remove the setting "
            "to use its default"
        )


SETTINGS = Settings(
    ENV_PREFIX,
    (
        Setting(
            "listen.host",
            "0.0.0.0",  # noqa: S104  container default; the image sets it too
            "Address the HTTP server binds to. `server.host` (`QBT_RULES_SERVER_HOST`) is an "
            "alias.",
        ),
        Setting(
            "listen.port",
            5000,
            "Port the HTTP server listens on, and the one the image's healthcheck polls. "
            "`server.port` (`QBT_RULES_SERVER_PORT`) is an alias, which the healthcheck doesn't "
            "read.",
            check=port,
        ),
        Setting(
            "state_dir",
            str(DEFAULT_STATE_DIR),
            "Directory for state: the SQLite job database and the rules editor's history "
            "(`.history/`).",
            check=_not_legacy_path,
        ),
        Setting(
            "dry_run",
            False,
            "Log what rules would do without doing it. Replaces 0.10.x's `engine.dry_run`.",
        ),
        Setting(
            "rules.file",
            "",
            "The rules file. Empty: `rules.yml` beside the config file "
            "(`/etc/qbt-rules/rules.yml`). A relative path is relative to the config file's "
            "directory. It must be writable for the dashboard's editor to save it.",
            check=_not_legacy_path,
        ),
        Setting(
            "server.api_key",
            "",
            "Key for the HTTP API and the dashboard login (`openssl rand -hex 32`). Unset, the "
            "server starts but refuses every authenticated request, and `/api/health` says so.",
            secret=True,
        ),
        Setting(
            "server.workers",
            1,
            "Must be 1: the server is one process, so its worker and scheduler run once. "
            "Kept so a 0.10.x config that sets it to 1 still loads.",
            check=one_process,
        ),
        Setting(
            "server.editor_enabled",
            True,
            "Allow saving `rules.yml` from the dashboard's rules editor. `false` keeps it "
            "read-only.",
        ),
        Setting(
            "client.server_url",
            "http://localhost:5000",
            "Server the CLI client submits jobs to.",
        ),
        Setting(
            "client.api_key",
            "",
            "API key the CLI client sends. Empty: `server.api_key`, right for `docker exec` into "
            "the server's own container.",
            secret=True,
        ),
        Setting(
            "queue.backend",
            "sqlite",
            "Job queue: `sqlite` or `redis`.",
            check=one_of("sqlite", "redis"),
        ),
        Setting(
            "queue.sqlite_path",
            "",
            "SQLite job database. Empty: `qbt-rules.db` in `state_dir`. A relative path is "
            "relative to `state_dir`.",
            check=_not_legacy_path,
        ),
        Setting(
            "queue.redis_url",
            "redis://localhost:6379/0",
            "Redis URL, for `queue.backend: redis`: `redis://[:password@]host[:port][/db]`.",
            secret=True,
        ),
        Setting(
            "queue.cleanup_after",
            "7d",
            "Delete finished jobs older than this: seconds or a duration (`7d`, `2w`, "
            "`30 days`). `0` keeps them.",
            check=_duration,
        ),
        Setting("qbittorrent.host", "http://localhost:8080", "qBittorrent's Web UI address."),
        Setting("qbittorrent.username", "admin", "qBittorrent Web UI user."),
        Setting("qbittorrent.password", "", "qBittorrent Web UI password.", secret=True),
        Setting(
            "notifications.webhook_url",
            "",
            "Default webhook for the `notify` action when a rule gives no `url`.",
            secret=True,
        ),
        Setting(
            "notifications.service",
            "generic",
            "Default `notify` service: `generic`, `discord`, `slack` or `ntfy`.",
            check=one_of(*NOTIFY_SERVICES),
        ),
        Setting(
            "integrations.sonarr.url",
            "",
            "Sonarr's address, for the `arr_blocklist` action.",
        ),
        Setting("integrations.sonarr.api_key", "", "Sonarr's API key.", secret=True),
        Setting(
            "integrations.radarr.url",
            "",
            "Radarr's address, for the `arr_blocklist` action.",
        ),
        Setting("integrations.radarr.api_key", "", "Radarr's API key.", secret=True),
        Setting(
            "integrations.trackie.url",
            "",
            "trackie's address, for the `tracker.*` fields. Empty: not used.",
        ),
        Setting(
            "integrations.trackie.max_age",
            "3 hours",
            "Older tracker data counts as no data: seconds or a duration.",
            check=_duration,
        ),
        Setting(
            "integrations.trackie.timeout",
            "10",
            "Seconds for trackie's `/snapshot` request.",
            check=_decimal,
        ),
        Setting(
            "metrics.enabled",
            False,
            "Serve Prometheus metrics on `/metrics` (needs the API key).",
        ),
        Setting(
            "logging.level",
            "INFO",
            "Log level: `DEBUG`, `INFO`, `WARNING` or `ERROR`. DEBUG logs every rule evaluation.",
            check=one_of(*LOG_LEVELS),
        ),
        Setting(
            "logging.file",
            "",
            "Also log to this file, rotated by size. Empty: the console only (`docker logs`). A "
            "relative path is relative to `state_dir`.",
            check=_not_legacy_path,
        ),
        Setting(
            "logging.max_bytes",
            10 * 1024 * 1024,
            "Rotate the log file at this size; `0` never rotates.",
            check=non_negative,
        ),
        Setting(
            "logging.backup_count",
            5,
            "Rotated log files to keep.",
            check=non_negative,
        ),
        Setting(
            "logging.trace_mode",
            False,
            "Add module, function and line to each log line.",
        ),
        Setting(
            "logging.http_access",
            False,
            "Log every HTTP request, health checks included.",
        ),
    ),
    default_path=DEFAULT_CONFIG_PATH,
)
CONFIG_ENV = SETTINGS.config_env
_BY_KEY = {s.key: s for s in SETTINGS}


@dataclass(frozen=True)
class ScheduleEntry:
    cron: str
    context: str


@dataclass(frozen=True)
class Config:
    config_file: Path
    rules_file: Path
    state_dir: Path
    history_dir: Path
    host: str
    port: int
    dry_run: bool
    api_key: Secret
    workers: int
    editor_enabled: bool
    client_server_url: str
    client_api_key: Secret
    queue_backend: str
    sqlite_path: Path
    redis_url: Secret
    cleanup_after: int | None  # seconds; None keeps finished jobs
    qbt_host: str
    qbt_username: str
    qbt_password: Secret
    webhook_url: Secret
    notify_service: str
    sonarr_url: str
    sonarr_api_key: Secret
    radarr_url: str
    radarr_api_key: Secret
    trackie_url: str
    trackie_max_age: int  # seconds
    trackie_timeout: float
    metrics_enabled: bool
    log_level: str
    log_file: Path | None  # None: the console only
    log_max_bytes: int
    log_backup_count: int
    trace_mode: bool
    http_access: bool
    schedule: tuple[ScheduleEntry, ...] = ()
    # Setting key -> where its value came from ("default", "file", an env var name).
    sources: Mapping[str, str] = field(default_factory=dict)
    # Setting key -> its value, for `qbt-rules config` (a secret stays a Secret).
    values: Mapping[str, object] = field(default_factory=dict)

    @property
    def problems(self) -> tuple[str, ...]:
        """What the server starts without but can't fully work without: /api/health lists them"""
        if self.api_key:
            return ()
        if PLACEHOLDER_SOURCE in self.sources.get("server.api_key", ""):
            return (
                "server.api_key is still the placeholder from the 0.10.x default config.yml, "
                "which is public, so it is ignored: set a real key "
                "(QBT_RULES_SERVER_API_KEY_FILE) and restart",
            )
        return (
            "server.api_key is not set, so the API and the dashboard refuse every request: set "
            "QBT_RULES_SERVER_API_KEY_FILE (or QBT_RULES_SERVER_API_KEY) and restart",
        )


def load_config(path: Path | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Load the configuration. A missing config file is not an error: defaults apply."""
    env = dict(os.environ if environ is None else environ)
    _refuse_variables(env)
    if path is None:
        path = Path(env.get(CONFIG_ENV, str(DEFAULT_CONFIG_PATH)))
    _refuse_misnamed_file(path)

    raw = _read_yaml(path)
    _refuse_renamed_keys(raw, path)
    data = _expand(raw, env)
    alias_sources = _apply_variable_aliases(env)
    _apply_key_aliases(data, path)

    # interpose reads the file itself, so a value this module changed (an expanded ${VAR}, or an
    # aliased key) reaches it as its variable, unless a real variable already overrides it.
    overlay: dict[str, str] = {}
    for setting in SETTINGS:
        if setting.env in env or f"{setting.env}_FILE" in env:
            continue
        value, before = _lookup(data, setting.key), _lookup(raw, setting.key)
        if value is not None and value != before:
            overlay[setting.env] = _as_text(value)
    r = SETTINGS.resolve(path, {**env, **overlay})
    sources = dict(r.sources)
    for setting in SETTINGS:
        if setting.env in overlay:
            sources[setting.key] = "file"
    sources.update(alias_sources)
    values: dict[str, object] = dict(r.values)

    state_dir = Path(r.str("state_dir"))

    def under(base: Path, key: str, default: str) -> Path:
        given = r.str(key)
        resolved = base / (given or default)
        if not given:
            sources[key] = f"default: {resolved}"
            values[key] = str(resolved)
        return resolved

    rules_file = under(path.parent, "rules.file", RULES_FILENAME)
    sqlite_path = under(state_dir, "queue.sqlite_path", DB_FILENAME)
    log_name = r.str("logging.file")
    log_file = state_dir / log_name if log_name else None

    def key(name: str) -> Secret:
        """A key setting; the public placeholder 0.10.x shipped counts as unset"""
        value = r.secret(name)
        if value.reveal() == PLACEHOLDER_API_KEY:
            sources[name] = f"{sources[name]}: {PLACEHOLDER_SOURCE}"
            return Secret("")
        return value

    retention = duration_seconds(r.str("queue.cleanup_after")) or None
    max_age = duration_seconds(r.str("integrations.trackie.max_age"))
    assert max_age is not None  # noqa: S101  its check= accepted it

    return Config(
        config_file=path,
        rules_file=rules_file,
        state_dir=state_dir,
        history_dir=state_dir / HISTORY_DIRNAME,
        host=r.str("listen.host"),
        port=r.int("listen.port"),
        dry_run=r.bool("dry_run"),
        api_key=key("server.api_key"),
        workers=r.int("server.workers"),
        editor_enabled=r.bool("server.editor_enabled"),
        client_server_url=r.str("client.server_url"),
        client_api_key=key("client.api_key"),
        queue_backend=r.str("queue.backend"),
        sqlite_path=sqlite_path,
        redis_url=r.secret("queue.redis_url"),
        cleanup_after=retention,
        qbt_host=r.str("qbittorrent.host"),
        qbt_username=r.str("qbittorrent.username"),
        qbt_password=r.secret("qbittorrent.password"),
        webhook_url=r.secret("notifications.webhook_url"),
        notify_service=r.str("notifications.service"),
        sonarr_url=r.str("integrations.sonarr.url"),
        sonarr_api_key=r.secret("integrations.sonarr.api_key"),
        radarr_url=r.str("integrations.radarr.url"),
        radarr_api_key=r.secret("integrations.radarr.api_key"),
        trackie_url=r.str("integrations.trackie.url"),
        trackie_max_age=max_age,
        trackie_timeout=float(r.str("integrations.trackie.timeout")),
        metrics_enabled=r.bool("metrics.enabled"),
        log_level=r.str("logging.level"),
        log_file=log_file,
        log_max_bytes=r.int("logging.max_bytes"),
        log_backup_count=r.int("logging.backup_count"),
        trace_mode=r.bool("logging.trace_mode"),
        http_access=r.bool("logging.http_access"),
        schedule=_load_schedule(data, env, path),
        sources=sources,
        values=values,
    )


# -- what interpose doesn't do ------------------------------------------------------------------


def _refuse_variables(env: Mapping[str, str]) -> None:
    for name, message in REFUSED_VARIABLES.items():
        forms = (name, f"{name}_FILE") if name.startswith(ENV_PREFIX) else (name,)
        if any(form in env for form in forms):
            raise ConfigError(message)


def _refuse_misnamed_file(path: Path) -> None:
    """A config.yml beside a missing config.yaml was meant to be read: say so, don't ignore it."""
    old = path.with_name("config.yml")
    if path.name == "config.yaml" and not path.exists() and old.is_file():
        raise ConfigError(
            f"{old} is not read: the config file is now {path}. Rename it (and check the wiki's "
            "In-Depth-Configuration page, Migrating from 0.10.x, for the keys that changed)"
        )


def _refuse_renamed_keys(data: Mapping[str, Any], path: Path) -> None:
    for old, new in RENAMED_KEYS.items():
        if _lookup(data, old) is not None:
            raise ConfigError(f"{path}: {old} is now {new}")
    for key, message in REMOVED_KEYS.items():
        if _lookup(data, key) is not None:
            raise ConfigError(f"{path}: {message}")


def _read_yaml(path: Path) -> Mapping[str, Any]:
    """The file as parsed, for this module's own rules. interpose reports anything wrong with it."""
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _expand(value: Any, env: Mapping[str, str]) -> Any:
    """``${VAR}`` and ``${VAR:-default}`` in every string, from the environment."""
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: env.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    return value


def _apply_variable_aliases(env: dict[str, str]) -> dict[str, str]:
    """QBT_RULES_SERVER_PORT feeds listen.port, unless QBT_RULES_LISTEN_PORT is set too."""
    sources: dict[str, str] = {}
    for old, new in ALIASES.items():
        old_env, new_env = _env_name(old), _BY_KEY[new].env
        for suffix in ("", "_FILE"):
            if f"{old_env}{suffix}" not in env:
                continue
            value = env[f"{old_env}{suffix}"]
            others = {env[n] for n in (new_env, f"{new_env}_FILE") if n in env}
            if others and others != {value}:
                raise ConfigError(
                    f"{old_env}{suffix} and {new_env} are both set, to different values: "
                    f"{old_env} is an alias of {new_env}, so set only {new_env}"
                )
            if not others:
                env[f"{new_env}{suffix}"] = value
                sources[new] = f"{old_env}{suffix} (alias of {new_env})"
    return sources


def _apply_key_aliases(data: dict[str, Any], path: Path) -> None:
    """server.port in the file is listen.port, unless listen.port is there too."""
    for old, new in ALIASES.items():
        value = _lookup(data, old)
        if value is None:
            continue
        current = _lookup(data, new)
        if current is not None and current != value:
            raise ConfigError(
                f"{path}: {old} and {new} are both set, to different values: {old} is an alias "
                f"of {new}, so set only {new}"
            )
        section, name = new.split(".")
        if isinstance(data.get(section), dict):
            data[section].setdefault(name, value)
        else:
            data[section] = {name: value}


def _load_schedule(
    data: Mapping[str, Any], env: Mapping[str, str], path: Path
) -> tuple[ScheduleEntry, ...]:
    """schedule: the indexed variables if any are set (they replace the file's list), else the file.

    Indices start at 0 and must be contiguous: the first missing _CRON ends the list.
    """
    entries: list[Any] = []
    where = str(path)
    i = 0
    while (cron := _variable(env, f"{ENV_PREFIX}SCHEDULE_{i}_CRON")) is not None:
        context = _variable(env, f"{ENV_PREFIX}SCHEDULE_{i}_CONTEXT")
        if context is None:
            raise ConfigError(
                f"{ENV_PREFIX}SCHEDULE_{i}_CRON is set but {ENV_PREFIX}SCHEDULE_{i}_CONTEXT is "
                "missing"
            )
        entries.append({"cron": cron, "context": context})
        where = f"{ENV_PREFIX}SCHEDULE_<N>"
        i += 1
    if not entries:
        listed = data.get("schedule") or []
        if not isinstance(listed, list):
            raise ConfigError(f"{path}: schedule must be a list")
        entries = listed

    out: list[ScheduleEntry] = []
    for n, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: schedule entry #{n} must be a mapping")
        for required in ("cron", "context"):
            if required not in entry:
                raise ConfigError(f"{where}: schedule entry #{n} has no {required!r}")
        cron, context = str(entry["cron"]), str(entry["context"])
        if not croniter.is_valid(cron):
            raise ConfigError(
                f"{where}: schedule entry #{n} has an invalid cron expression {cron!r}"
            )
        out.append(ScheduleEntry(cron=cron, context=context))
    return tuple(out)


def _variable(env: Mapping[str, str], name: str) -> str | None:
    """A variable's value, its _FILE variant first (the same order as every setting)."""
    file_var = f"{name}_FILE"
    if file_var in env:
        try:
            return Path(env[file_var]).read_text(encoding="utf-8").rstrip()
        except OSError as e:
            raise ConfigError(f"cannot read {file_var} ({env[file_var]}): {e.strerror}") from None
    return env.get(name)


def _env_name(key: str) -> str:
    return ENV_PREFIX + key.upper().replace(".", "_")


def _lookup(data: Mapping[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)
