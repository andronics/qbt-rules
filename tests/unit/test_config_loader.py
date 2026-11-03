"""config_loader: rules.yml beside the settings, with hot reload.

The settings themselves are config.py's (tests/unit/test_config.py).
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from qbt_rules.config_loader import Config, load_config, load_yaml_file
from qbt_rules.errors import ConfigurationError

RULE = "rules:\n  - {id: %s, conditions: {all: []}, actions: [{type: stop}]}\n"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A config directory with an empty config.yaml (rules.yml is each test's)."""
    directory = tmp_path / "etc"
    directory.mkdir()
    (directory / "config.yaml").write_text("", encoding="utf-8")
    return directory


@pytest.fixture
def load(config_dir: Path) -> Callable[..., Config]:
    """Write rules.yml (unless None) and load the configuration from config_dir."""

    def run(rules: str | None) -> Config:
        if rules is not None:
            (config_dir / "rules.yml").write_text(rules, encoding="utf-8")
        return load_config(config_dir / "config.yaml", environ={})

    return run


# -- load_yaml_file -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("key: value\nnumber: 42\n", {"key": "value", "number": 42}),
        ("outer:\n  list: [a, b]\n", {"outer": {"list": ["a", "b"]}}),
        ("", {}),
        ("# only a comment\n", {}),
    ],
)
def test_load_yaml_file(tmp_path: Path, text: str, expected: dict[str, object]) -> None:
    path = tmp_path / "file.yml"
    path.write_text(text, encoding="utf-8")
    assert load_yaml_file(path) == expected


def test_load_yaml_file_missing_is_empty(tmp_path: Path) -> None:
    assert load_yaml_file(tmp_path / "missing.yml") == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("key: value\n  bad: [indent\n", "Invalid YAML syntax"),
        ("- a\n- b\n", "The top level must be a mapping"),
    ],
)
def test_load_yaml_file_errors(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "file.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_yaml_file(path)


def test_load_yaml_file_permission_denied(tmp_path: Path) -> None:
    path = tmp_path / "file.yml"
    path.write_text("key: value\n", encoding="utf-8")
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):  # pragma: no cover - running as root
            pytest.skip("root reads any file")
        with pytest.raises(ConfigurationError, match="Permission denied"):
            load_yaml_file(path)
    finally:
        path.chmod(0o644)


# -- Config: where the files are ------------------------------------------------------------------


def test_paths_come_from_the_settings(config_dir: Path, load: Callable[..., Config]) -> None:
    config = load(RULE % "a")
    assert config.config_file == config_dir / "config.yaml"
    assert config.rules_file == config_dir / "rules.yml"
    assert config.history_dir == Path("/var/lib/qbt-rules/.history")
    assert config.settings.rules_file == config.rules_file


def test_rules_file_setting(tmp_path: Path, config_dir: Path) -> None:
    elsewhere = tmp_path / "elsewhere.yml"
    elsewhere.write_text(RULE % "from-elsewhere", encoding="utf-8")
    env = {"QBT_RULES_RULES_FILE": str(elsewhere)}
    config = load_config(config_dir / "config.yaml", environ=env)
    assert config.rules_file == elsewhere
    assert config.get_rules()[0]["id"] == "from-elsewhere"


# -- Config: loading rules.yml --------------------------------------------------------------------


def test_loads_rules(load: Callable[..., Config]) -> None:
    config = load(RULE % "test-rule")
    assert [r["id"] for r in config.get_rules()] == ["test-rule"]
    assert config.rules_version == 1


def test_rules_version_is_read(load: Callable[..., Config]) -> None:
    assert load("version: 2\nrules: []\n").rules_version == 2


@pytest.mark.parametrize("text", [None, "", "# nothing yet\n", "rules: []\n"])
def test_no_rules_is_not_an_error(
    load: Callable[..., Config], text: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    # The first start: no rules.yml yet (the editor creates it), or an empty one
    with caplog.at_level(logging.WARNING):
        config = load(text)
    assert config.get_rules() == []
    assert ("does not exist" in caplog.text) == (text is None)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("rules: not_a_list\n", "must be a list"),
        ("rules:\n  - {name: no-id, conditions: {all: []}, actions: []}\n", "'id'"),
        ('rules:\n  - {id: "", conditions: {all: []}, actions: []}\n', "invalid 'id'"),
        ("rules:\n  - {id: 42, conditions: {all: []}, actions: []}\n", "invalid 'id'"),
        (
            "rules:\n  - {id: dupe, conditions: {all: []}, actions: []}\n"
            "  - {id: dupe, conditions: {all: []}, actions: []}\n",
            "Duplicate rule id: 'dupe'",
        ),
    ],
)
def test_invalid_rules_refused(load: Callable[..., Config], text: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load(text)


def test_empty_refs_block_loads(load: Callable[..., Config]) -> None:
    # refs: with everything under it commented out parses as None
    config = load("refs:\n  vars:\nrules:\n  - {id: a, conditions: [], actions: []}\n")
    assert config.get_rules()[0]["id"] == "a"


def test_schedule_and_dry_run_come_from_the_settings(config_dir: Path) -> None:
    (config_dir / "config.yaml").write_text(
        "dry_run: true\nschedule:\n  - {cron: '*/30 * * * *', context: cron}\n",
        encoding="utf-8",
    )
    config = load_config(config_dir / "config.yaml", environ={})
    assert config.is_dry_run() is True
    assert config.schedule == [{"cron": "*/30 * * * *", "context": "cron"}]


# -- Config: hot reload ---------------------------------------------------------------------------


def test_reloads_when_the_file_changes(config_dir: Path, load: Callable[..., Config]) -> None:
    config = load(RULE % "initial")
    assert [r["id"] for r in config.get_rules()] == ["initial"]
    time.sleep(0.01)
    (config_dir / "rules.yml").write_text(RULE % "updated", encoding="utf-8")
    assert [r["id"] for r in config.get_rules()] == ["updated"]


def test_creating_the_file_reloads(config_dir: Path, load: Callable[..., Config]) -> None:
    config = load(None)
    assert config.get_rules() == []
    (config_dir / "rules.yml").write_text(RULE % "created", encoding="utf-8")
    assert [r["id"] for r in config.get_rules()] == ["created"]


def test_no_reload_when_unchanged(load: Callable[..., Config], mocker: MockerFixture) -> None:
    config = load(RULE % "a")
    spy = mocker.spy(config, "_load_rules")
    config.get_rules()
    config.get_rules()
    assert spy.call_count == 1


def test_reloads_a_file_with_an_older_mtime(config_dir: Path, load: Callable[..., Config]) -> None:
    # A restored backup (cp -p, git checkout) can carry an older mtime than the file it replaces
    config = load(RULE % "current")
    assert config.get_rules()[0]["id"] == "current"
    rules_file = config_dir / "rules.yml"
    old = rules_file.stat().st_mtime - 3600
    rules_file.write_text(RULE % "restored-backup", encoding="utf-8")
    os.utime(rules_file, (old, old))
    assert config.get_rules()[0]["id"] == "restored-backup"


def test_failed_reload_keeps_the_old_rules(
    config_dir: Path, load: Callable[..., Config], caplog: pytest.LogCaptureFixture
) -> None:
    config = load(RULE % "good")
    config.get_rules()
    rules_file = config_dir / "rules.yml"
    rules_file.write_text(
        "rules:\n  - {id: dup, conditions: [], actions: []}\n"
        "  - {id: dup, conditions: [], actions: []}\n",
        encoding="utf-8",
    )
    os.utime(rules_file, (rules_file.stat().st_mtime + 5,) * 2)
    with caplog.at_level(logging.WARNING):
        assert [r["id"] for r in config.get_rules()] == ["good"]
    assert [r["id"] for r in config.get_rules(resolved=False)] == ["good"]
    assert "Failed to reload rules" in caplog.text


def test_reload_rules_force(load: Callable[..., Config]) -> None:
    config = load("rules: []\n")
    assert config.reload_rules() is True  # first call after init
    assert config.reload_rules() is False  # unchanged
    assert config.reload_rules(force=True) is True


def test_resolved_rules_expand_refs(load: Callable[..., Config]) -> None:
    config = load(
        "refs:\n  actions:\n    halt: {type: stop}\n"
        "rules:\n  - {id: a, conditions: {all: []}, actions: [{$ref: actions.halt}]}\n"
    )
    assert config.get_rules()[0]["actions"] == [{"type": "stop"}]
    assert config.get_rules(resolved=False)[0]["actions"] == [{"$ref": "actions.halt"}]
