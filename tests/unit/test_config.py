"""The project's settings and its own rules.

The engine (lookup order, coercion, ``_FILE``, YAML errors) is interpose's and tested there;
these tests pin what is the project's: the keys and variables, the defaults, the checks, and
what load_config adds (${VAR} expansion, aliases, refusals, the schedule, the problems list).
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from interpose.secret import Secret
from interpose.settings import Setting, Settings

from qbt_rules.config import (
    CONFIG_ENV,
    DEFAULT_CONFIG_PATH,
    ENV_PREFIX,
    LOG_LEVELS,
    PLACEHOLDER_API_KEY,
    SETTINGS,
    ConfigError,
    ScheduleEntry,
    duration_seconds,
    load_config,
)

# Every variable name the 0.10.x releases documented, with the setting it feeds. Deployments
# (the Unraid template, compose files, Kubernetes manifests) set these: a renamed variable
# breaks them, so this table changes only on purpose.
VARIABLES = [
    ("listen.host", "QBT_RULES_LISTEN_HOST"),
    ("listen.port", "QBT_RULES_LISTEN_PORT"),
    ("state_dir", "QBT_RULES_STATE_DIR"),
    ("dry_run", "QBT_RULES_DRY_RUN"),
    ("rules.file", "QBT_RULES_RULES_FILE"),
    ("server.api_key", "QBT_RULES_SERVER_API_KEY"),
    ("server.workers", "QBT_RULES_SERVER_WORKERS"),
    ("server.editor_enabled", "QBT_RULES_SERVER_EDITOR_ENABLED"),
    ("client.server_url", "QBT_RULES_CLIENT_SERVER_URL"),
    ("client.api_key", "QBT_RULES_CLIENT_API_KEY"),
    ("queue.backend", "QBT_RULES_QUEUE_BACKEND"),
    ("queue.sqlite_path", "QBT_RULES_QUEUE_SQLITE_PATH"),
    ("queue.redis_url", "QBT_RULES_QUEUE_REDIS_URL"),
    ("queue.cleanup_after", "QBT_RULES_QUEUE_CLEANUP_AFTER"),
    ("qbittorrent.host", "QBT_RULES_QBITTORRENT_HOST"),
    ("qbittorrent.username", "QBT_RULES_QBITTORRENT_USERNAME"),
    ("qbittorrent.password", "QBT_RULES_QBITTORRENT_PASSWORD"),
    ("notifications.webhook_url", "QBT_RULES_NOTIFICATIONS_WEBHOOK_URL"),
    ("notifications.service", "QBT_RULES_NOTIFICATIONS_SERVICE"),
    ("integrations.sonarr.url", "QBT_RULES_INTEGRATIONS_SONARR_URL"),
    ("integrations.sonarr.api_key", "QBT_RULES_INTEGRATIONS_SONARR_API_KEY"),
    ("integrations.radarr.url", "QBT_RULES_INTEGRATIONS_RADARR_URL"),
    ("integrations.radarr.api_key", "QBT_RULES_INTEGRATIONS_RADARR_API_KEY"),
    ("integrations.trackie.url", "QBT_RULES_INTEGRATIONS_TRACKIE_URL"),
    ("integrations.trackie.max_age", "QBT_RULES_INTEGRATIONS_TRACKIE_MAX_AGE"),
    ("integrations.trackie.timeout", "QBT_RULES_INTEGRATIONS_TRACKIE_TIMEOUT"),
    ("metrics.enabled", "QBT_RULES_METRICS_ENABLED"),
    ("metrics.multiproc_dir", "QBT_RULES_METRICS_MULTIPROC_DIR"),
    ("logging.level", "QBT_RULES_LOGGING_LEVEL"),
    ("logging.file", "QBT_RULES_LOGGING_FILE"),
    ("logging.max_bytes", "QBT_RULES_LOGGING_MAX_BYTES"),
    ("logging.backup_count", "QBT_RULES_LOGGING_BACKUP_COUNT"),
    ("logging.trace_mode", "QBT_RULES_LOGGING_TRACE_MODE"),
    ("logging.http_access", "QBT_RULES_LOGGING_HTTP_ACCESS"),
]

SECRETS = {
    "server.api_key",
    "client.api_key",
    "queue.redis_url",
    "qbittorrent.password",
    "notifications.webhook_url",
    "integrations.sonarr.api_key",
    "integrations.radarr.api_key",
}

# (variable, value, Config field, expected): each variable, set on its own, reaches its field
# with its type. The _FILE form of each is checked by test_every_variable_has_a_file_form.
ENV_CASES = [
    ("QBT_RULES_LISTEN_HOST", "127.0.0.1", "host", "127.0.0.1"),
    ("QBT_RULES_LISTEN_PORT", "8080", "port", 8080),
    ("QBT_RULES_STATE_DIR", "/srv/state", "state_dir", Path("/srv/state")),
    ("QBT_RULES_DRY_RUN", "true", "dry_run", True),
    ("QBT_RULES_DRY_RUN", "0", "dry_run", False),
    ("QBT_RULES_RULES_FILE", "/srv/rules.yml", "rules_file", Path("/srv/rules.yml")),
    ("QBT_RULES_SERVER_API_KEY", "k3y", "api_key", Secret("k3y")),
    ("QBT_RULES_SERVER_WORKERS", "1", "workers", 1),
    ("QBT_RULES_SERVER_EDITOR_ENABLED", "false", "editor_enabled", False),
    ("QBT_RULES_CLIENT_SERVER_URL", "http://qbtr:5000", "client_server_url", "http://qbtr:5000"),
    ("QBT_RULES_CLIENT_API_KEY", "c1ient", "client_api_key", Secret("c1ient")),
    ("QBT_RULES_QUEUE_BACKEND", "redis", "queue_backend", "redis"),
    ("QBT_RULES_QUEUE_SQLITE_PATH", "/srv/q.db", "sqlite_path", Path("/srv/q.db")),
    ("QBT_RULES_QUEUE_REDIS_URL", "redis://r:6379/1", "redis_url", Secret("redis://r:6379/1")),
    ("QBT_RULES_QUEUE_CLEANUP_AFTER", "2w", "cleanup_after", 1209600),
    ("QBT_RULES_QUEUE_CLEANUP_AFTER", "0", "cleanup_after", None),
    ("QBT_RULES_QBITTORRENT_HOST", "http://qbt:8080", "qbt_host", "http://qbt:8080"),
    ("QBT_RULES_QBITTORRENT_USERNAME", "me", "qbt_username", "me"),
    ("QBT_RULES_QBITTORRENT_PASSWORD", "pw", "qbt_password", Secret("pw")),
    ("QBT_RULES_NOTIFICATIONS_WEBHOOK_URL", "https://h/x", "webhook_url", Secret("https://h/x")),
    ("QBT_RULES_NOTIFICATIONS_SERVICE", "ntfy", "notify_service", "ntfy"),
    ("QBT_RULES_INTEGRATIONS_SONARR_URL", "http://s:8989", "sonarr_url", "http://s:8989"),
    ("QBT_RULES_INTEGRATIONS_SONARR_API_KEY", "s", "sonarr_api_key", Secret("s")),
    ("QBT_RULES_INTEGRATIONS_RADARR_URL", "http://r:7878", "radarr_url", "http://r:7878"),
    ("QBT_RULES_INTEGRATIONS_RADARR_API_KEY", "r", "radarr_api_key", Secret("r")),
    ("QBT_RULES_INTEGRATIONS_TRACKIE_URL", "http://t:8080", "trackie_url", "http://t:8080"),
    ("QBT_RULES_INTEGRATIONS_TRACKIE_MAX_AGE", "2 hours", "trackie_max_age", 7200),
    ("QBT_RULES_INTEGRATIONS_TRACKIE_TIMEOUT", "2.5", "trackie_timeout", 2.5),
    ("QBT_RULES_METRICS_ENABLED", "yes", "metrics_enabled", True),
    ("QBT_RULES_METRICS_MULTIPROC_DIR", "/run/m", "metrics_multiproc_dir", Path("/run/m")),
    ("QBT_RULES_LOGGING_LEVEL", "debug", "log_level", "DEBUG"),
    ("QBT_RULES_LOGGING_FILE", "/srv/q.log", "log_file", Path("/srv/q.log")),
    ("QBT_RULES_LOGGING_MAX_BYTES", "0", "log_max_bytes", 0),
    ("QBT_RULES_LOGGING_BACKUP_COUNT", "2", "log_backup_count", 2),
    ("QBT_RULES_LOGGING_TRACE_MODE", "on", "trace_mode", True),
    ("QBT_RULES_LOGGING_HTTP_ACCESS", "true", "http_access", True),
    # Aliases: server.host and server.port feed listen.host and listen.port
    ("QBT_RULES_SERVER_HOST", "127.0.0.1", "host", "127.0.0.1"),
    ("QBT_RULES_SERVER_PORT", "8080", "port", 8080),
]

# (variables, the error names): refused at startup with what to set instead
REFUSED = [
    (
        {"CONFIG_DIR": "/config"},
        r"CONFIG_DIR is no longer read: .*/etc/qbt-rules.*QBT_RULES_CONFIG",
    ),
    (
        {"QBT_RULES_CONFIG_DIR": "/config"},
        r"QBT_RULES_CONFIG_DIR is no longer read: .*/var/lib/qbt-rules.*QBT_RULES_STATE_DIR",
    ),
    ({"QBT_RULES_CONFIG_DIR_FILE": "/x"}, r"QBT_RULES_CONFIG_DIR is no longer read"),
    ({"QBT_RULES_LOG_LEVEL": "DEBUG"}, r"use QBT_RULES_LOGGING_LEVEL"),
    ({"QBT_RULES_QUEUE_SQLITE_PATH": "/config/qbt-rules.db"}, r"queue\.sqlite_path: .* /config"),
    ({"QBT_RULES_RULES_FILE": "/config/rules.yml"}, r"rules\.file: /config/rules\.yml is under"),
    ({"QBT_RULES_LOGGING_FILE": "/config/qbt-rules.log"}, r"logging\.file: .*Remove the setting"),
    ({"QBT_RULES_STATE_DIR": "/config"}, r"state_dir: /config is under /config"),
    (
        {"QBT_RULES_SERVER_PORT": "8080", "QBT_RULES_LISTEN_PORT": "9090"},
        r"QBT_RULES_SERVER_PORT and QBT_RULES_LISTEN_PORT are both set, to different values",
    ),
    ({"QBT_RULES_SCHEDULE_0_CRON": "* * * * *"}, r"QBT_RULES_SCHEDULE_0_CONTEXT is missing"),
    (
        {"QBT_RULES_SCHEDULE_0_CRON": "nope", "QBT_RULES_SCHEDULE_0_CONTEXT": "c"},
        r"QBT_RULES_SCHEDULE_<N>: schedule entry #1 has an invalid cron expression 'nope'",
    ),
    ({"QBT_RULES_QUEUE_BACKEND": "postgres"}, r"queue\.backend: expected one of sqlite, redis"),
    ({"QBT_RULES_QUEUE_CLEANUP_AFTER": "soon"}, r"queue\.cleanup_after: expected seconds"),
    ({"QBT_RULES_NOTIFICATIONS_SERVICE": "irc"}, r"notifications\.service: expected one of"),
    ({"QBT_RULES_INTEGRATIONS_TRACKIE_TIMEOUT": "0"}, r"trackie\.timeout: must be greater"),
    ({"QBT_RULES_SERVER_WORKERS": "0"}, r"server\.workers: must be greater than 0"),
    # One process now (template-python decision 0008): Gunicorn's workers are gone
    ({"QBT_RULES_SERVER_WORKERS": "2"}, r"server\.workers: must be 1, got 2: .* one process"),
    ({"QBT_RULES_LOGGING_LEVEL": "loud"}, r"logging\.level: expected one of DEBUG"),
]

# (config file, the error names): what was renamed or is in the wrong place
REFUSED_FILES = [
    ("engine:\n  dry_run: true\n", r"engine\.dry_run is now dry_run"),
    ("queue:\n  sqlite_path: /config/qbt-rules.db\n", r"queue\.sqlite_path: .* /config"),
    ("rules:\n  file: /config/rules.yml\n", r"rules\.file: /config/rules\.yml is under"),
    (
        "server:\n  port: 8080\nlisten:\n  port: 9090\n",
        r"server\.port and listen\.port are both set, to different values",
    ),
    ("schedule: hourly\n", r"schedule must be a list"),
    ("schedule:\n  - just a string\n", r"schedule entry #1 must be a mapping"),
    ("schedule:\n  - {context: c}\n", r"schedule entry #1 has no 'cron'"),
    ("schedule:\n  - {cron: '* * * * *'}\n", r"schedule entry #1 has no 'context'"),
    ("schedule:\n  - {cron: nope, context: c}\n", r"schedule entry #1 has an invalid cron"),
]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Where the tests' config file goes; nothing is written until a test writes it."""
    return tmp_path / "config.yaml"


def test_keys_and_variables() -> None:
    assert [(s.key, s.env) for s in SETTINGS] == VARIABLES
    assert {s.key for s in SETTINGS if s.secret} == SECRETS
    assert CONFIG_ENV == "QBT_RULES_CONFIG"
    assert Path("/etc/qbt-rules/config.yaml") == DEFAULT_CONFIG_PATH


def test_defaults_when_no_file(config_path: Path) -> None:
    cfg = load_config(config_path, environ={})
    assert (cfg.host, cfg.port) == ("0.0.0.0", 5000)  # noqa: S104
    assert cfg.config_file == config_path
    assert cfg.rules_file == config_path.parent / "rules.yml"
    assert cfg.state_dir == Path("/var/lib/qbt-rules")
    assert cfg.sqlite_path == Path("/var/lib/qbt-rules/qbt-rules.db")
    assert cfg.history_dir == Path("/var/lib/qbt-rules/.history")
    assert cfg.log_file is None
    assert (cfg.log_level, cfg.log_max_bytes, cfg.log_backup_count) == ("INFO", 10485760, 5)
    assert cfg.dry_run is False
    assert cfg.cleanup_after == 7 * 86400
    assert (cfg.trackie_max_age, cfg.trackie_timeout) == (3 * 3600, 10.0)
    assert cfg.schedule == ()
    assert not cfg.api_key
    assert cfg.sources["listen.port"] == "default"
    assert cfg.sources["rules.file"] == f"default: {config_path.parent / 'rules.yml'}"
    assert cfg.values["queue.sqlite_path"] == "/var/lib/qbt-rules/qbt-rules.db"


def test_default_config_path(tmp_path: Path) -> None:
    path = tmp_path / "from-env.yaml"
    path.write_text("dry_run: true\n", encoding="utf-8")
    assert load_config(environ={"QBT_RULES_CONFIG": str(path)}).dry_run is True


@pytest.mark.parametrize(("variable", "value", "attr", "expected"), ENV_CASES)
def test_each_variable(
    config_path: Path, variable: str, value: str, attr: str, expected: object
) -> None:
    cfg = load_config(config_path, environ={variable: value})
    assert getattr(cfg, attr) == expected


@pytest.mark.parametrize(("variable", "value", "attr", "expected"), ENV_CASES)
def test_every_variable_has_a_file_form(
    tmp_path: Path, config_path: Path, variable: str, value: str, attr: str, expected: object
) -> None:
    secret = tmp_path / "value"
    secret.write_text(f"{value}\n", encoding="utf-8")
    cfg = load_config(config_path, environ={f"{variable}_FILE": str(secret)})
    assert getattr(cfg, attr) == expected


@pytest.mark.parametrize(("environ", "match"), REFUSED)
def test_refused_variables(config_path: Path, environ: dict[str, str], match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        load_config(config_path, environ=environ)


@pytest.mark.parametrize(("text", "match"), REFUSED_FILES)
def test_refused_files(config_path: Path, text: str, match: str) -> None:
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        load_config(config_path, environ={})


def test_old_config_yml_beside_a_missing_config_yaml(tmp_path: Path) -> None:
    (tmp_path / "config.yml").write_text("server:\n  port: 5000\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"config\.yml is not read: the config file is now"):
        load_config(tmp_path / "config.yaml", environ={})


def test_file_values(config_path: Path) -> None:
    config_path.write_text(
        "listen: {port: 9000}\ndry_run: true\nqbittorrent: {host: 'http://q:1'}\n"
        "logging: {level: warning, file: qbt-rules.log}\nrules: {file: my-rules.yml}\n",
        encoding="utf-8",
    )
    cfg = load_config(config_path, environ={"QBT_RULES_STATE_DIR": "/srv"})
    assert (cfg.port, cfg.dry_run, cfg.qbt_host, cfg.log_level) == (
        9000,
        True,
        "http://q:1",
        "WARNING",
    )
    # Relative paths: the log under state_dir, rules.yml beside the config file
    assert cfg.log_file == Path("/srv/qbt-rules.log")
    assert cfg.rules_file == config_path.parent / "my-rules.yml"
    assert cfg.sources["listen.port"] == "file"


def test_env_overrides_file(config_path: Path) -> None:
    config_path.write_text("dry_run: true\n", encoding="utf-8")
    cfg = load_config(config_path, environ={"QBT_RULES_DRY_RUN": "false"})
    assert cfg.dry_run is False
    assert cfg.sources["dry_run"] == "QBT_RULES_DRY_RUN"


def test_variable_expansion(config_path: Path) -> None:
    config_path.write_text(
        "qbittorrent:\n  host: ${QB_HOST:-http://localhost:8080}\n  username: ${QB_USER}\n"
        "listen:\n  port: ${PORT:-5001}\n"
        "schedule:\n  - {cron: '${CRON:-0 * * * *}', context: hourly}\n",
        encoding="utf-8",
    )
    cfg = load_config(config_path, environ={"QB_HOST": "http://custom:9090", "QB_USER": "me"})
    assert (cfg.qbt_host, cfg.qbt_username, cfg.port) == ("http://custom:9090", "me", 5001)
    assert cfg.schedule == (ScheduleEntry(cron="0 * * * *", context="hourly"),)
    assert cfg.sources["qbittorrent.host"] == "file"
    # A real variable still beats the expanded file value
    cfg = load_config(config_path, environ={"QBT_RULES_LISTEN_PORT": "6000"})
    assert cfg.port == 6000
    assert cfg.sources["listen.port"] == "QBT_RULES_LISTEN_PORT"


def test_unset_reference_without_default_is_empty(config_path: Path) -> None:
    config_path.write_text("qbittorrent:\n  password: ${QB_PASS}\n", encoding="utf-8")
    assert not load_config(config_path, environ={}).qbt_password


def test_key_aliases(config_path: Path) -> None:
    # A 0.10.x config.yml has server.host and server.port: they still work
    config_path.write_text("server:\n  host: 127.0.0.1\n  port: 8080\n", encoding="utf-8")
    cfg = load_config(config_path, environ={})
    assert (cfg.host, cfg.port) == ("127.0.0.1", 8080)
    assert cfg.sources["listen.port"] == "file"
    # The same value under both names is fine
    config_path.write_text("server: {port: 8080}\nlisten: {port: 8080}\n", encoding="utf-8")
    assert load_config(config_path, environ={}).port == 8080


def test_variable_aliases(config_path: Path) -> None:
    cfg = load_config(config_path, environ={"QBT_RULES_SERVER_PORT": "8080"})
    assert cfg.port == 8080
    assert cfg.sources["listen.port"] == "QBT_RULES_SERVER_PORT (alias of QBT_RULES_LISTEN_PORT)"
    # The image sets QBT_RULES_LISTEN_HOST=0.0.0.0; the same value under the alias is fine
    env = {"QBT_RULES_LISTEN_HOST": "0.0.0.0", "QBT_RULES_SERVER_HOST": "0.0.0.0"}  # noqa: S104
    assert load_config(config_path, environ=env).host == "0.0.0.0"  # noqa: S104
    # A variable beats the file, the alias included
    config_path.write_text("listen: {port: 9000}\n", encoding="utf-8")
    assert load_config(config_path, environ={"QBT_RULES_SERVER_PORT": "8080"}).port == 8080


def test_schedule_from_file(config_path: Path) -> None:
    config_path.write_text(
        "schedule:\n  - {cron: '*/30 * * * *', context: cron}\n"
        "  - {cron: '0 3 * * *', context: nightly}\n",
        encoding="utf-8",
    )
    assert load_config(config_path, environ={}).schedule == (
        ScheduleEntry("*/30 * * * *", "cron"),
        ScheduleEntry("0 3 * * *", "nightly"),
    )


def test_schedule_variables_replace_the_file(tmp_path: Path, config_path: Path) -> None:
    config_path.write_text("schedule:\n  - {cron: '0 0 * * *', context: file}\n", encoding="utf-8")
    cron = tmp_path / "cron"
    cron.write_text("*/15 * * * *\n", encoding="utf-8")
    env = {
        "QBT_RULES_SCHEDULE_0_CRON_FILE": str(cron),
        "QBT_RULES_SCHEDULE_0_CONTEXT": "first",
        "QBT_RULES_SCHEDULE_1_CRON": "0 3 * * *",
        "QBT_RULES_SCHEDULE_1_CONTEXT": "second",
        # Index 2 is missing, so index 3 is never read
        "QBT_RULES_SCHEDULE_3_CRON": "0 4 * * *",
        "QBT_RULES_SCHEDULE_3_CONTEXT": "unreached",
    }
    assert load_config(config_path, environ=env).schedule == (
        ScheduleEntry("*/15 * * * *", "first"),
        ScheduleEntry("0 3 * * *", "second"),
    )


def test_unreadable_schedule_file_variable(tmp_path: Path, config_path: Path) -> None:
    env = {"QBT_RULES_SCHEDULE_0_CRON_FILE": str(tmp_path / "nope")}
    with pytest.raises(ConfigError, match=r"cannot read QBT_RULES_SCHEDULE_0_CRON_FILE"):
        load_config(config_path, environ=env)


def test_no_api_key_is_a_problem_not_an_error(config_path: Path) -> None:
    # The image's smoke test starts it with no configuration at all
    cfg = load_config(config_path, environ={})
    assert len(cfg.problems) == 1
    assert cfg.problems[0].startswith("server.api_key is not set")
    assert load_config(config_path, environ={"QBT_RULES_SERVER_API_KEY": "k"}).problems == ()


def test_the_old_placeholder_key_counts_as_unset(config_path: Path) -> None:
    config_path.write_text(
        f"server: {{api_key: {PLACEHOLDER_API_KEY}}}\nclient: {{api_key: {PLACEHOLDER_API_KEY}}}\n",
        encoding="utf-8",
    )
    cfg = load_config(config_path, environ={})
    assert not cfg.api_key
    assert not cfg.client_api_key
    assert "placeholder" in cfg.problems[0]


def test_secrets_are_masked(config_path: Path) -> None:
    cfg = load_config(config_path, environ={"QBT_RULES_QBITTORRENT_PASSWORD": "hunter2"})
    assert cfg.qbt_password.reveal() == "hunter2"
    assert str(cfg.qbt_password) == "********"
    assert "hunter2" not in repr(cfg)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("604800", 604800),
        ("7d", 604800),
        ("2w", 1209600),
        ("12h", 43200),
        ("30 days", 2592000),
        ("3 hours", 10800),
        ("1 minute", 60),
        ("0", 0),
        ("soon", None),
        ("7 fortnights", None),
    ],
)
def test_duration_seconds(text: str, seconds: int | None) -> None:
    assert duration_seconds(text) == seconds


def test_level_is_the_declared_spelling(config_path: Path) -> None:
    assert "INFO" in LOG_LEVELS
    for given in ("info", "Info", "INFO"):
        config_path.write_text(f"logging: {{level: {given}}}\n", encoding="utf-8")
        assert load_config(config_path, environ={}).log_level == "INFO"


def test_a_secret_setting(tmp_path: Path) -> None:
    # The pattern for a secret=True setting: read it with secret() and reveal() it where it's used.
    token = Setting("example.token", "", "A token.", secret=True)
    settings = Settings(ENV_PREFIX, (*SETTINGS, token), default_path=DEFAULT_CONFIG_PATH)
    path = tmp_path / "token"
    path.write_text("s3cret\n", encoding="utf-8")
    resolved = settings.resolve(
        tmp_path / "missing.yaml", {"QBT_RULES_EXAMPLE_TOKEN_FILE": str(path)}
    )
    assert resolved.secret("example.token").reveal() == "s3cret"
    with pytest.raises(TypeError, match=r"secret setting, not str: use secret\(\) and reveal\(\)"):
        resolved.str("example.token")


def test_top_level_must_be_mapping(write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match="the top level must be a mapping"):
        load_config(write_config("- a\n- b\n"), environ={})


def test_empty_file_is_defaults(write_config: Callable[..., Path]) -> None:
    assert load_config(write_config(""), environ={}).log_level == "INFO"


def test_invalid_yaml(write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match="cannot parse"):
        load_config(write_config("logging: [unclosed\n"), environ={})


def test_bad_port(config_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"listen\.port: expected int"):
        load_config(config_path, environ={"QBT_RULES_LISTEN_PORT": "http"})
    with pytest.raises(ConfigError, match=r"listen\.port: 70000 is not a TCP port"):
        load_config(config_path, environ={"QBT_RULES_LISTEN_PORT": "70000"})


def test_the_example_file_is_every_default() -> None:
    # contrib/qbt-rules.example.yaml lists every setting, each with its default
    example = Path(__file__).resolve().parents[2] / "contrib" / "qbt-rules.example.yaml"
    cfg = load_config(example, environ={})
    defaults = load_config(example.with_name("missing.yaml"), environ={})
    for setting in SETTINGS:
        assert cfg.sources[setting.key] == "file" or cfg.sources[setting.key].startswith("default")
        assert cfg.values[setting.key] == defaults.values[setting.key], setting.key
