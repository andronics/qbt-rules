"""The project's settings and its own rules.

The engine (lookup order, coercion, ``_FILE``, YAML errors) is interpose's and tested there;
these tests pin what is the project's: the keys and variables, the defaults and the checks.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from interpose.settings import Setting, Settings

from qbt_rules.config import (
    CONFIG_ENV,
    DEFAULT_CONFIG_PATH,
    ENV_PREFIX,
    LOG_LEVELS,
    SETTINGS,
    ConfigError,
    load_config,
)


def test_keys_and_variables() -> None:
    # Renaming one breaks every deployment that sets it: this list changes only on purpose.
    assert [(s.key, s.env) for s in SETTINGS] == [
        ("log_level", "QBT_RULES_LOG_LEVEL"),
        ("listen.host", "QBT_RULES_LISTEN_HOST"),
        ("listen.port", "QBT_RULES_LISTEN_PORT"),
        ("state_dir", "QBT_RULES_STATE_DIR"),
    ]
    assert CONFIG_ENV == "QBT_RULES_CONFIG"
    assert Path("/etc/qbt-rules/config.yaml") == DEFAULT_CONFIG_PATH


def test_defaults_when_no_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.yaml", environ={})
    assert cfg.log_level == "INFO"
    assert (cfg.host, cfg.port) == ("0.0.0.0", 5000)  # noqa: S104
    assert cfg.state_dir == Path("/var/lib/qbt-rules")
    assert set(cfg.sources.values()) == {"default"}


def test_file_overrides_default(write_config: Callable[..., Path]) -> None:
    cfg = load_config(write_config("log_level: debug\n"), environ={})
    assert cfg.log_level == "DEBUG"
    assert cfg.sources["log_level"] == "file"


def test_env_overrides_file(write_config: Callable[..., Path]) -> None:
    path = write_config("log_level: debug\n")
    cfg = load_config(path, environ={"QBT_RULES_LOG_LEVEL": "warning"})
    assert cfg.log_level == "WARNING"
    assert cfg.sources["log_level"] == "QBT_RULES_LOG_LEVEL"


def test_file_variable_overrides_env(tmp_path: Path) -> None:
    level = tmp_path / "level"
    level.write_text("error\n", encoding="utf-8")
    env = {"QBT_RULES_LOG_LEVEL": "warning", "QBT_RULES_LOG_LEVEL_FILE": str(level)}
    cfg = load_config(tmp_path / "missing.yaml", environ=env)
    assert cfg.log_level == "ERROR"
    assert cfg.sources["log_level"] == "QBT_RULES_LOG_LEVEL_FILE"


def test_config_path_from_environment(write_config: Callable[..., Path]) -> None:
    path = write_config("log_level: error\n")
    cfg = load_config(environ={"QBT_RULES_CONFIG": str(path)})
    assert cfg.log_level == "ERROR"
    assert cfg.sources["log_level"] == "file"


def test_unreadable_file_variable(tmp_path: Path) -> None:
    env = {"QBT_RULES_LOG_LEVEL_FILE": str(tmp_path / "nope")}
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.yaml", environ=env)


def test_invalid_log_level(tmp_path: Path) -> None:
    match = r"log_level: expected one of DEBUG, INFO, WARNING, ERROR, got 'loud'"
    with pytest.raises(ConfigError, match=match):
        load_config(tmp_path / "missing.yaml", environ={"QBT_RULES_LOG_LEVEL": "loud"})


def test_level_is_the_declared_spelling(write_config: Callable[..., Path]) -> None:
    # one_of() resolves any case to the spelling LOG_LEVELS declares: the names logging wants.
    assert "INFO" in LOG_LEVELS
    for given in ("info", "Info", "INFO"):
        assert load_config(write_config(f"log_level: {given}\n"), environ={}).log_level == "INFO"
    cfg = load_config(write_config(""), environ={"QBT_RULES_LOG_LEVEL": "debug"})
    assert cfg.log_level == "DEBUG"


def test_a_secret_setting(tmp_path: Path) -> None:
    # The pattern for a secret=True setting: read it with secret() and reveal() it where it's used.
    token = Setting("example.token", "", "A token.", secret=True)
    settings = Settings(ENV_PREFIX, (*SETTINGS, token), default_path=DEFAULT_CONFIG_PATH)
    path = tmp_path / "token"
    path.write_text("s3cret\n", encoding="utf-8")
    env = {"QBT_RULES_EXAMPLE_TOKEN_FILE": str(path)}
    resolved = settings.resolve(tmp_path / "missing.yaml", env)
    secret = resolved.secret("example.token")
    assert secret.reveal() == "s3cret"
    assert str(secret) == f"{secret}" == "********"
    assert "s3cret" not in repr(secret)
    # str() on a secret setting is refused at load, not sent as ********.
    with pytest.raises(TypeError, match=r"secret setting, not str: use secret\(\) and reveal\(\)"):
        resolved.str("example.token")


def test_top_level_must_be_mapping(write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match="the top level must be a mapping"):
        load_config(write_config("- a\n- b\n"), environ={})


def test_empty_file_is_defaults(write_config: Callable[..., Path]) -> None:
    assert load_config(write_config(""), environ={}).log_level == "INFO"


def test_invalid_yaml(write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match="cannot parse"):
        load_config(write_config("log_level: [unclosed\n"), environ={})


def test_nested_keys_from_file_and_env(write_config: Callable[..., Path]) -> None:
    cfg = load_config(write_config("listen:\n  port: 9000\n"), environ={})
    assert cfg.port == 9000
    assert cfg.sources["listen.port"] == "file"
    cfg = load_config(write_config(""), environ={"QBT_RULES_LISTEN_PORT": "9001"})
    assert cfg.port == 9001
    assert cfg.sources["listen.port"] == "QBT_RULES_LISTEN_PORT"


def test_bad_port(write_config: Callable[..., Path]) -> None:
    with pytest.raises(ConfigError, match=r"listen\.port: expected int"):
        load_config(write_config(""), environ={"QBT_RULES_LISTEN_PORT": "http"})
    with pytest.raises(ConfigError, match=r"listen\.port: 70000 is not a TCP port"):
        load_config(write_config(""), environ={"QBT_RULES_LISTEN_PORT": "70000"})
