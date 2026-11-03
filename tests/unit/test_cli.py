from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qbt_rules import __version__
from qbt_rules.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_config_shows_sources(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("logging: {level: debug}\n"))])
    assert result.exit_code == 0
    assert "logging.level = DEBUG  (file)" in result.stdout
    assert "rules.file = " in result.stdout
    assert "server.api_key = ********  (default)" in result.stdout


def test_config_error_exits_2(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("logging: {level: loud}\n"))])
    assert result.exit_code == 2
    assert "logging.level" in result.stderr


def test_secrets_are_masked(
    monkeypatch: pytest.MonkeyPatch, write_config: Callable[..., Path]
) -> None:
    from interpose.settings import Setting

    from qbt_rules import cli
    from qbt_rules.config import SETTINGS

    secret = Setting(SETTINGS[0].key, SETTINGS[0].default, SETTINGS[0].help, secret=True)
    monkeypatch.setattr(cli, "SETTINGS", (secret, *SETTINGS[1:]))
    result = runner.invoke(app, ["config", "-c", str(write_config(""))])
    assert f"{SETTINGS[0].key} = ********" in result.stdout


def test_main_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from qbt_rules import cli

    called: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    cli.main()
    assert called == [True]


def test_serve_starts_uvicorn(
    monkeypatch: pytest.MonkeyPatch, write_config: Callable[..., Path]
) -> None:
    import uvicorn

    seen: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    result = runner.invoke(app, ["serve", "-c", str(write_config("listen:\n  port: 9100\n"))])
    assert result.exit_code == 0
    assert seen["port"] == 9100
