"""The `qbt-rules` command (cli.py): every command, its output and its exit code.

The client commands run against the real FastAPI app with a real SQLite queue: requests
to SERVER are answered by a TestClient (requests-mock), so the CLI and the API are tested
together, not against a hand-written imitation of the API.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
import requests_mock
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from qbt_rules import __version__, api, api_client, cli
from qbt_rules.cli import app
from qbt_rules.config import load_config
from qbt_rules.queue_backends.sqlite_queue import SQLiteQueue

runner = CliRunner()

SERVER = "http://qbtr.test"
API_KEY = "cli-test-key"
HASH = "0123456789ABCDEF0123456789abcdef01234567"

VALID_RULES = """\
rules:
  - id: tag-hd
    context: torrent-imported
    meta:
      description: Tag HD torrents
    conditions:
      all:
        - field: info.name
          operator: contains
          value: 1080p
    actions:
      - type: add_tag
        params:
          tags: [hd]
  - id: pause-stalled
    enabled: false
    stop_on_match: true
    context: [hourly, manual]
    conditions:
      all:
        - field: info.state
          operator: ==
          value: stalledDL
    actions:
      - type: stop
"""


# -- version and config ------------------------------------------------------------------------


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_config_shows_sources(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("logging: {level: debug}\n"))])
    assert result.exit_code == 0
    assert "logging.level = DEBUG  (file)" in result.stdout
    assert "rules.file = " in result.stdout
    assert "server.api_key = (unset)  (default)" in result.stdout


def test_config_says_the_placeholder_key_is_unset(write_config: Callable[..., Path]) -> None:
    from qbt_rules.config import PLACEHOLDER_API_KEY

    path = write_config(f"server: {{api_key: {PLACEHOLDER_API_KEY}}}\n")
    result = runner.invoke(app, ["config", "-c", str(path)])
    assert "server.api_key = (unset)  (file" in result.stdout
    assert PLACEHOLDER_API_KEY not in result.stdout


def test_config_error_exits_2(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config("logging: {level: loud}\n"))])
    assert result.exit_code == 2
    assert "logging.level" in result.stderr


def test_secrets_are_masked(
    monkeypatch: pytest.MonkeyPatch, write_config: Callable[..., Path]
) -> None:
    from interpose.settings import Setting

    from qbt_rules.config import SETTINGS

    secret = Setting(SETTINGS[0].key, SETTINGS[0].default, SETTINGS[0].help, secret=True)
    monkeypatch.setattr(cli, "SETTINGS", (secret, *SETTINGS[1:]))
    result = runner.invoke(app, ["config", "-c", str(write_config(""))])
    assert f"{SETTINGS[0].key} = ******** (set)" in result.stdout


def test_config_masks_a_set_key_and_lists_the_schedule(write_config: Callable[..., Path]) -> None:
    path = write_config(
        "server: {api_key: hunter2-hunter2}\nschedule:\n  - {cron: '0 * * * *', context: hourly}\n"
    )
    result = runner.invoke(app, ["config", "-c", str(path)])
    assert result.exit_code == 0
    assert "hunter2" not in result.output
    assert "server.api_key = ******** (set)  (file)" in result.stdout
    assert "schedule[0] = 0 * * * * -> hourly" in result.stdout
    assert "warning:" not in result.stderr


def test_config_warns_about_a_missing_api_key(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["config", "-c", str(write_config(""))])
    assert result.exit_code == 0
    assert "warning: server.api_key is not set" in result.stderr


def test_main_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    monkeypatch.setattr(cli, "app", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["qbt-rules", "version"])
    cli.main()
    assert called == [True]


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "execute" in result.output and "serve" in result.output


def test_unknown_command_exits_2() -> None:
    assert runner.invoke(app, ["frobnicate"]).exit_code == 2


# -- serve -------------------------------------------------------------------------------------


@pytest.fixture
def logging_configs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """log_setup.setup_logging, recorded instead of run (it would replace caplog's handler)"""
    from qbt_rules import log_setup

    configs: list[dict[str, Any]] = []
    monkeypatch.setattr(log_setup, "setup_logging", configs.append)
    return configs


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch, logging_configs: list[dict[str, Any]]) -> list[Any]:
    """server.serve, recorded instead of run"""
    from qbt_rules import server

    calls: list[Any] = []
    monkeypatch.setattr(server, "serve", calls.append)
    return calls


def test_serve_runs_the_server_with_the_settings(
    served: list[Any],
    logging_configs: list[dict[str, Any]],
    write_config: Callable[..., Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = write_config(
        "listen: {port: 9100}\nserver: {api_key: abc}\n"
        "logging: {level: debug, file: q.log, trace_mode: true, max_bytes: 9, backup_count: 2}\n"
    )
    result = runner.invoke(app, ["serve", "-c", str(path)])
    assert result.exit_code == 0, result.output
    assert [cfg.port for cfg in served] == [9100]
    assert logging_configs == [
        {
            "level": "DEBUG",
            "file": served[0].state_dir / "q.log",
            "trace_mode": True,
            "max_bytes": 9,
            "backup_count": 2,
        }
    ]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_serve_starts_without_an_api_key_and_says_so(
    served: list[Any], write_config: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    result = runner.invoke(app, ["serve", "-c", str(write_config(""))])
    assert result.exit_code == 0
    assert len(served) == 1
    assert any("server.api_key is not set" in r.getMessage() for r in caplog.records)


def test_serve_warns_about_the_port_alias(
    served: list[Any],
    write_config: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("QBT_RULES_SERVER_PORT", "9200")
    result = runner.invoke(app, ["serve", "-c", str(write_config(""))])
    assert result.exit_code == 0
    assert served[0].port == 9200
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("set QBT_RULES_LISTEN_PORT instead" in w for w in warnings)


def test_serve_warns_about_the_aliased_file_keys(
    served: list[Any], write_config: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_config("server:\n  host: 127.0.0.1\n  port: 9201\n")
    result = runner.invoke(app, ["serve", "-c", str(path)])
    assert result.exit_code == 0
    assert (served[0].host, served[0].port) == ("127.0.0.1", 9201)
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "server.host is deprecated" in w and "Rename it to listen.host" in w for w in warnings
    )
    assert any(
        "server.port is deprecated" in w and "Rename it to listen.port" in w for w in warnings
    )


def test_config_and_validate_show_the_alias_warnings(
    write_config: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QBT_RULES_STATE_DIR", str(tmp_path))
    path = write_config("server: {port: 9202}\n")
    result = runner.invoke(app, ["config", "-c", str(path)])
    assert "warning: " in result.stderr and "server.port is deprecated" in result.stderr
    result = runner.invoke(app, ["validate", "-c", str(path)])
    assert "warning: " in result.stdout and "server.port is deprecated" in result.stdout


def test_serve_lists_every_refused_setting(
    served: list[Any], write_config: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONFIG_DIR", "/config")
    path = write_config("engine: {dry_run: true}\nlogging: {file: /config/qbt-rules.log}\n")
    result = runner.invoke(app, ["serve", "-c", str(path)])
    assert result.exit_code == 2
    assert not served
    assert "the configuration has 3 problems" in result.stderr
    for part in ("CONFIG_DIR is no longer read", "engine.dry_run is now dry_run", "logging.file"):
        assert part in result.stderr


def test_serve_with_metrics_on_starts(served: list[Any], write_config: Callable[..., Path]) -> None:
    """metrics.enabled needs nothing installed beyond the image's dependencies (interpose)."""
    result = runner.invoke(app, ["serve", "-c", str(write_config("metrics: {enabled: true}\n"))])
    assert result.exit_code == 0
    assert served[0].metrics_enabled is True


def test_serve_refuses_the_removed_multiprocess_directory(
    served: list[Any], write_config: Callable[..., Path]
) -> None:
    path = write_config("metrics: {enabled: true, multiproc_dir: /tmp/m}\n")
    result = runner.invoke(app, ["serve", "-c", str(path)])
    assert result.exit_code == 2
    assert "metrics.multiproc_dir is no longer read" in result.stderr
    assert served == []


def test_serve_refusal_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    logging_configs: list[dict[str, Any]],
    write_config: Callable[..., Path],
) -> None:
    from qbt_rules import server
    from qbt_rules.config import ConfigError

    def refuse(cfg: Any) -> None:
        raise ConfigError("server.workers is 4: drop the setting")

    monkeypatch.setattr(server, "serve", refuse)
    result = runner.invoke(app, ["serve", "-c", str(write_config(""))])
    assert result.exit_code == 2
    assert "error: server.workers is 4" in result.stderr


# -- validate ----------------------------------------------------------------------------------


@pytest.fixture
def rules_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The config and the state directory in one: config.yaml with a qBittorrent password, and
    rules.yml (which lives in the state directory)"""
    monkeypatch.setenv("QBT_RULES_STATE_DIR", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "qbittorrent: {password: secret}\nserver: {api_key: abc}\n", encoding="utf-8"
    )
    return tmp_path


def _validate(directory: Path, rules: str | None, *extra: str) -> Any:
    if rules is not None:
        (directory / "rules.yml").write_text(rules, encoding="utf-8")
    return runner.invoke(app, ["validate", "-c", str(directory / "config.yaml"), *extra])


def test_validate_passes_a_good_file(rules_dir: Path) -> None:
    result = _validate(rules_dir, VALID_RULES)
    assert result.exit_code == 0, result.output
    assert f"Rules: {rules_dir / 'rules.yml'}: 2 rule(s), 0 error(s)" in result.stdout
    assert result.stdout.rstrip().endswith("Valid.")


def test_validate_reports_line_and_column_and_exits_1(rules_dir: Path) -> None:
    rules = VALID_RULES.replace("type: stop", "type: explode")
    result = _validate(rules_dir, rules)
    assert result.exit_code == 1
    line = 1 + rules.splitlines().index("      - type: explode")
    assert (
        f"{rules_dir / 'rules.yml'}:{line}:15: error: Unknown action type 'explode'"
        in result.stdout
    )
    assert "(rules[1].actions[0].type)" in result.stdout
    assert "error: validation failed: 1 error(s)" in result.stderr


def test_validate_reports_yaml_syntax_errors_with_their_line(rules_dir: Path) -> None:
    result = _validate(rules_dir, "rules:\n  - id: a\n    conditions: [\n")
    assert result.exit_code == 1
    assert f"{rules_dir / 'rules.yml'}:4:1: error: YAML syntax error" in result.stdout


def test_validate_checks_actions_supplied_by_a_ref(rules_dir: Path) -> None:
    rules = (
        "refs:\n  actions:\n    shared:\n      - type: explode\n"
        "rules:\n  - id: r\n    conditions: []\n    actions:\n      - $ref: actions.shared\n"
    )
    result = _validate(rules_dir, rules)
    assert result.exit_code == 1
    assert (
        ":4:15: error: Unknown action type 'explode' (refs.actions.shared[0].type)" in result.stdout
    )


def test_validate_warnings_alone_pass(rules_dir: Path) -> None:
    rules = VALID_RULES.replace("operator: contains", "operator: contains\n          extra: 1")
    result = _validate(rules_dir, rules)
    assert result.exit_code == 0, result.output
    assert ": warning: " in result.stdout


@pytest.mark.parametrize(
    "config_extra, expected",
    [("", 1), ("notifications: {webhook_url: 'https://example.invalid/hook'}\n", 0)],
)
def test_validate_checks_notify_against_the_configured_webhook(
    rules_dir: Path, config_extra: str, expected: int
) -> None:
    with (rules_dir / "config.yaml").open("a", encoding="utf-8") as f:
        f.write(config_extra)
    rules = VALID_RULES.replace(
        "      - type: stop", "      - type: notify\n        params: {message: hi}"
    )
    result = _validate(rules_dir, rules)
    assert result.exit_code == expected, result.output
    if expected:
        assert "notify needs params.url or notifications.webhook_url" in result.stdout


def test_validate_a_missing_rules_file_is_a_warning(rules_dir: Path) -> None:
    result = _validate(rules_dir, None)
    assert result.exit_code == 0
    assert "does not exist: no rules" in result.stdout


def test_validate_an_empty_rules_file_is_a_warning(rules_dir: Path) -> None:
    result = _validate(rules_dir, "\n")
    assert result.exit_code == 0
    assert "is empty: no rules" in result.stdout


def test_validate_an_unreadable_rules_file_exits_1(rules_dir: Path) -> None:
    (rules_dir / "rules.yml").mkdir()
    result = _validate(rules_dir, None)
    assert result.exit_code == 1
    assert "error: cannot read" in result.stdout


def test_validate_takes_another_rules_file(rules_dir: Path, tmp_path: Path) -> None:
    other = tmp_path / "candidate.yml"
    other.write_text(VALID_RULES.replace("type: stop", "type: explode"), encoding="utf-8")
    (rules_dir / "rules.yml").write_text(VALID_RULES, encoding="utf-8")
    result = runner.invoke(app, ["validate", str(other), "-c", str(rules_dir / "config.yaml")])
    assert result.exit_code == 1
    assert f"{other}:" in result.stdout


def test_validate_flags_settings(write_config: Callable[..., Path]) -> None:
    path = write_config("qbittorrent: {host: ''}\n")
    result = runner.invoke(app, ["validate", "-c", str(path)])
    assert result.exit_code == 1
    assert "error: qbittorrent.host is not set" in result.stdout
    assert "warning: qbittorrent.password is not set" in result.stdout
    assert "warning: server.api_key is not set" in result.stdout
    assert "(absent)" not in result.stdout


def test_validate_says_when_the_config_file_is_absent(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "-c", str(tmp_path / "config.yaml")])
    assert result.exit_code == 0
    assert f"Settings: {tmp_path / 'config.yaml'} (absent)" in result.stdout


def test_validate_with_a_bad_setting_exits_2(write_config: Callable[..., Path]) -> None:
    result = runner.invoke(app, ["validate", "-c", str(write_config("queue: {backend: mongo}\n"))])
    assert result.exit_code == 2
    assert "queue.backend" in result.stderr


# -- rules list --------------------------------------------------------------------------------


def test_rules_list_table(rules_dir: Path) -> None:
    (rules_dir / "rules.yml").write_text(VALID_RULES, encoding="utf-8")
    result = runner.invoke(app, ["rules", "list", "-c", str(rules_dir / "config.yaml")])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "Rules (2 total, execute in file order):" in lines
    first = next(line for line in lines if line.startswith("1 "))
    second = next(line for line in lines if line.startswith("2 "))
    assert first.split()[:5] == ["1", "✓", "-", "torrent-imported", "tag-hd"]
    assert "Tag HD torrents" in first
    assert second.split()[:5] == ["2", "✗", "✓", "hourly,manual", "pause-stalled"]


def test_rules_list_json(rules_dir: Path) -> None:
    (rules_dir / "rules.yml").write_text(VALID_RULES, encoding="utf-8")
    result = runner.invoke(app, ["rules", "list", "--json", "-c", str(rules_dir / "config.yaml")])
    assert result.exit_code == 0
    assert [r["id"] for r in json.loads(result.stdout)] == ["tag-hd", "pause-stalled"]


def test_rules_list_without_rules(rules_dir: Path) -> None:
    result = runner.invoke(app, ["rules", "list", "-c", str(rules_dir / "config.yaml")])
    assert result.exit_code == 0
    assert "No rules defined in" in result.stdout


def test_rules_list_with_broken_rules_exits_1(rules_dir: Path) -> None:
    (rules_dir / "rules.yml").write_text("rules: {not: a list}\n", encoding="utf-8")
    result = runner.invoke(app, ["rules", "list", "-c", str(rules_dir / "config.yaml")])
    assert result.exit_code == 1
    assert "Run `qbt-rules validate`" in result.stderr


# -- the client commands, against the real API -------------------------------------------------


class StubWorker:
    def run(self, stop: Any) -> None:
        stop.wait()

    def is_alive(self) -> bool:
        return True

    def get_status(self) -> dict[str, Any]:
        return {"running": True, "last_job_completed": None}


@pytest.fixture
def queue(tmp_path: Path) -> Iterator[SQLiteQueue]:
    q = SQLiteQueue(str(tmp_path / "queue.db"))
    yield q
    q.close()


@pytest.fixture
def server(
    queue: SQLiteQueue, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[requests_mock.Mocker]:
    """The API at SERVER, and the CLI's settings pointing at it with the right key"""
    settings = load_config(
        tmp_path / "server.yaml",
        environ={"QBT_RULES_SERVER_API_KEY": API_KEY, "QBT_RULES_STATE_DIR": str(tmp_path)},
    )
    client = TestClient(
        api.create_app(settings, api.Services(queue=queue, worker=StubWorker(), rules=None))
    )

    def forward(request: Any, context: Any) -> Any:
        response = client.request(
            request.method,
            request.url.removeprefix(SERVER),
            headers=dict(request.headers),
            content=request.body,
        )
        context.status_code = response.status_code
        context.headers = dict(response.headers)
        return response.content

    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    monkeypatch.setenv("QBT_RULES_CLIENT_SERVER_URL", SERVER + "/")
    monkeypatch.setenv("QBT_RULES_SERVER_API_KEY", API_KEY)
    with client, requests_mock.Mocker() as mock:
        mock.register_uri(requests_mock.ANY, requests_mock.ANY, content=forward)
        yield mock


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr("qbt_rules.api_client.time.sleep", slept.append)
    return slept


def test_execute_queues_a_job(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    result = runner.invoke(app, ["execute", "--context", "torrent-imported", "--hash", HASH])
    assert result.exit_code == 0, result.output
    [job] = queue.list_jobs()
    assert (job["context"], job["hash"], job["dry_run"]) == (
        "torrent-imported",
        HASH.lower(),
        False,
    )
    assert f"✓ Job queued: {job['job_id']}" in result.stdout
    assert f"  Hash: {HASH.lower()}" in result.stdout
    assert "Dry run" not in result.stdout
    # The key goes in a header, never the URL (access logs)
    request = server.request_history[0]
    assert request.headers["X-API-Key"] == API_KEY
    assert "key=" not in request.url


def test_execute_without_context_or_hash(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    result = runner.invoke(app, ["execute"])
    assert result.exit_code == 0
    [job] = queue.list_jobs()
    assert (job["context"], job["hash"]) == (None, None)
    assert "  Context: none" in result.stdout and "  Hash: all torrents" in result.stdout


def test_execute_dry_run(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    result = runner.invoke(app, ["execute", "--context", "manual", "--dry-run"])
    assert result.exit_code == 0
    assert queue.list_jobs()[0]["dry_run"] is True
    assert "  Dry run: yes" in result.stdout


def test_execute_json(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    result = runner.invoke(app, ["execute", "--context", "manual", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["job_id"] == queue.list_jobs()[0]["job_id"]


@pytest.mark.parametrize("value", ["abc", "z" * 40])
def test_execute_refuses_a_bad_hash_with_exit_2(server: requests_mock.Mocker, value: str) -> None:
    result = runner.invoke(app, ["execute", "--hash", value])
    assert result.exit_code == 2
    # Click's usage error, which rich colours under CI (FORCE_COLOR)
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "Invalid torrent hash" in plain
    assert server.call_count == 0


def _finish(queue: SQLiteQueue, status: str, **fields: Any) -> Callable[[float], None]:
    """A time.sleep that finishes the only job, as the worker would"""

    def sleep(seconds: float) -> None:
        job_id = queue.list_jobs()[0]["job_id"]
        queue.update_status(job_id, status, **fields)

    return sleep


def test_execute_wait_reports_the_result(
    server: requests_mock.Mocker, queue: SQLiteQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_fields = {"torrents_processed": 7, "rules_matched": 2, "actions_executed": 3}
    monkeypatch.setattr(
        "qbt_rules.api_client.time.sleep", _finish(queue, "completed", result=result_fields)
    )
    result = runner.invoke(app, ["execute", "--context", "manual", "--wait"])
    assert result.exit_code == 0, result.output
    assert "  Status: pending (waiting...)" in result.stdout
    assert "✓ Job completed successfully" in result.stdout
    assert "  Torrents processed: 7" in result.stdout
    assert "  Actions executed: 3" in result.stdout


def test_execute_wait_json_prints_only_the_finished_job(
    server: requests_mock.Mocker, queue: SQLiteQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("qbt_rules.api_client.time.sleep", _finish(queue, "completed", result={}))
    result = runner.invoke(app, ["execute", "--wait", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "completed"


@pytest.mark.parametrize(
    "status, fields, message",
    [
        ("failed", {"error": "qBittorrent is down"}, "  Error: qBittorrent is down"),
        ("cancelled", {}, "Job was cancelled"),
    ],
)
def test_execute_wait_exits_1_unless_the_job_completes(
    server: requests_mock.Mocker,
    queue: SQLiteQueue,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    fields: dict[str, Any],
    message: str,
) -> None:
    monkeypatch.setattr("qbt_rules.api_client.time.sleep", _finish(queue, status, **fields))
    result = runner.invoke(app, ["execute", "--wait"])
    assert result.exit_code == 1
    assert message in result.stderr


def test_execute_wait_gives_up(
    server: requests_mock.Mocker, no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_client, "MAX_WAIT", 4)
    result = runner.invoke(app, ["execute", "--wait"])
    assert result.exit_code == 1
    assert no_sleep == [2, 2]
    assert "did not finish within 4s" in result.stderr


def test_execute_cancels_a_job_an_old_server_would_run_for_real(
    requests_mock: requests_mock.Mocker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    monkeypatch.setenv("QBT_RULES_CLIENT_SERVER_URL", SERVER)
    monkeypatch.setenv("QBT_RULES_CLIENT_API_KEY", API_KEY)
    requests_mock.post(f"{SERVER}/api/execute", status_code=202, json={"job_id": "j1"})
    cancel = requests_mock.delete(f"{SERVER}/api/jobs/j1", json={"job_id": "j1"})
    result = runner.invoke(app, ["execute", "--dry-run"])
    assert result.exit_code == 1
    assert cancel.called
    assert "Cancelled job j1 before it ran." in result.stderr


def test_execute_says_when_the_unconfirmed_job_could_not_be_cancelled(
    requests_mock: requests_mock.Mocker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    monkeypatch.setenv("QBT_RULES_CLIENT_SERVER_URL", SERVER)
    monkeypatch.setenv("QBT_RULES_CLIENT_API_KEY", API_KEY)
    requests_mock.post(f"{SERVER}/api/execute", status_code=202, json={"job_id": "j1"})
    requests_mock.delete(f"{SERVER}/api/jobs/j1", status_code=400, json={"message": "started"})
    result = runner.invoke(app, ["execute", "--dry-run"])
    assert result.exit_code == 1
    assert "qbt-rules jobs status j1" in result.stderr


def test_client_without_any_api_key_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 1
    assert "no API key to send" in result.stderr


def test_client_key_wins_over_the_server_key(
    server: requests_mock.Mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QBT_RULES_CLIENT_API_KEY", "wrong")
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 1
    assert "Authentication failed" in result.stderr


def test_client_cannot_connect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    monkeypatch.setenv("QBT_RULES_CLIENT_SERVER_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("QBT_RULES_SERVER_API_KEY", API_KEY)
    result = runner.invoke(app, ["execute", "--context", "manual"])
    assert result.exit_code == 1
    assert "Cannot connect to the server at http://127.0.0.1:1" in result.stderr
    assert "qbt-rules serve" in result.stderr


@pytest.mark.parametrize(
    "mock_kwargs, message",
    [
        ({"exc": requests.exceptions.Timeout}, "timed out"),
        ({"exc": requests.exceptions.InvalidURL("bad")}, "failed: bad"),
        ({"status_code": 500, "json": {"error": "x", "message": "boom"}}, "Server error 500: boom"),
        ({"status_code": 502, "text": "<html>bad gateway</html>"}, "Server error 502: <html>"),
        ({"status_code": 503, "text": ""}, "Server error 503:"),
        ({"status_code": 500, "json": ["no", "message"]}, 'Server error 500: ["no"'),
    ],
)
def test_client_errors_exit_1(
    requests_mock: requests_mock.Mocker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mock_kwargs: dict[str, Any],
    message: str,
) -> None:
    monkeypatch.setenv("QBT_RULES_CONFIG", str(tmp_path / "cli.yaml"))
    monkeypatch.setenv("QBT_RULES_CLIENT_SERVER_URL", SERVER)
    monkeypatch.setenv("QBT_RULES_SERVER_API_KEY", API_KEY)
    requests_mock.get(f"{SERVER}/api/stats", **mock_kwargs)
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 1
    assert message in result.stderr


def test_jobs_list_table(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    first = queue.enqueue(context="hourly")
    queue.enqueue()
    result = runner.invoke(app, ["jobs", "list"])
    assert result.exit_code == 0
    assert "Jobs (showing 2 of 2 total):" in result.stdout
    row = next(line for line in result.stdout.splitlines() if line.startswith(first))
    assert row.split()[1:3] == ["pending", "hourly"]
    assert any(line.split()[2:3] == ["none"] for line in result.stdout.splitlines()[3:])


def test_jobs_list_filters(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    done = queue.enqueue(context="hourly")
    queue.update_status(done, "completed")
    queue.enqueue(context="hourly")
    queue.enqueue(context="manual")
    result = runner.invoke(
        app, ["jobs", "list", "--status", "pending", "--context", "hourly", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["total"] == 1
    assert data["limit"] == 20
    assert [(j["status"], j["context"]) for j in data["jobs"]] == [("pending", "hourly")]


def test_jobs_list_limit(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    for _ in range(3):
        queue.enqueue()
    result = runner.invoke(app, ["jobs", "list", "--limit", "2"])
    assert "Jobs (showing 2 of 3 total):" in result.stdout


def test_jobs_list_empty(server: requests_mock.Mocker) -> None:
    result = runner.invoke(app, ["jobs", "list"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "No jobs found"


@pytest.mark.parametrize("args", [["--status", "stuck"], ["--limit", "0"]])
def test_jobs_list_bad_values_exit_2(server: requests_mock.Mocker, args: list[str]) -> None:
    assert runner.invoke(app, ["jobs", "list", *args]).exit_code == 2


def test_jobs_status(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    job_id = queue.enqueue(context="manual", hash_filter=HASH.lower(), dry_run=True)
    queue.update_status(job_id, "failed", result={"rules_matched": 1}, error="it broke")
    result = runner.invoke(app, ["jobs", "status", job_id])
    assert result.exit_code == 0
    out = result.stdout
    assert f"Job ID:    {job_id}" in out
    assert "Status:    failed" in out
    assert f"Hash:      {HASH.lower()}" in out
    assert "Dry run:   yes" in out
    assert "Started:   not started" in out
    assert "rules_matched: 1" in out
    assert "  Error:\n    it broke" in out


def test_jobs_status_json(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    job_id = queue.enqueue()
    result = runner.invoke(app, ["jobs", "status", job_id, "--json"])
    assert json.loads(result.stdout)["job_id"] == job_id


def test_jobs_status_not_found_exits_1(server: requests_mock.Mocker) -> None:
    result = runner.invoke(app, ["jobs", "status", "nope"])
    assert result.exit_code == 1
    assert "error: Job not found: nope" in result.stderr


def test_jobs_cancel(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    job_id = queue.enqueue()
    result = runner.invoke(app, ["jobs", "cancel", job_id])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"✓ Job cancelled: {job_id}"
    assert queue.get_job(job_id)["status"] == "cancelled"  # type: ignore[index]


def test_jobs_cancel_json(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    job_id = queue.enqueue()
    result = runner.invoke(app, ["jobs", "cancel", job_id, "--json"])
    assert json.loads(result.stdout)["status"] == "cancelled"


def test_jobs_cancel_a_started_job_exits_1(
    server: requests_mock.Mocker, queue: SQLiteQueue
) -> None:
    job_id = queue.enqueue()
    queue.update_status(job_id, "completed")
    result = runner.invoke(app, ["jobs", "cancel", job_id])
    assert result.exit_code == 1
    assert result.stderr.strip() == "error: Cannot cancel job in status: completed"


def test_jobs_cancel_not_found_exits_1(server: requests_mock.Mocker) -> None:
    result = runner.invoke(app, ["jobs", "cancel", "nope"])
    assert result.exit_code == 1
    assert "Job not found: nope" in result.stderr


def test_stats(server: requests_mock.Mocker, queue: SQLiteQueue) -> None:
    queue.enqueue()
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Server Statistics:" in out
    assert "    Total:      1" in out
    assert "    Pending:    1" in out
    assert "    Cancelled:  0" in out
    assert "Average execution time: N/A" in out
    assert "Backend: SQLiteQueue" in out
    assert "Last job completed: never" in out


def test_stats_json(server: requests_mock.Mocker) -> None:
    result = runner.invoke(app, ["stats", "--json"])
    assert json.loads(result.stdout)["jobs"]["total"] == 0


# -- the 0.10.x flags-only form ----------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, command",
    [
        (
            ["--context", "torrent-imported", "--hash", "%I"],
            "qbt-rules execute --context torrent-imported --hash %I",
        ),
        (
            ["--context=manual", "--dry-run", "--wait", "--config", "/x/config.yaml"],
            "qbt-rules execute --context manual --wait --dry-run --config /x/config.yaml",
        ),
        (["--serve"], "qbt-rules serve"),
        (["--serve", "--server-port", "8080"], "qbt-rules serve"),
        (
            ["--list-jobs", "--status-filter", "pending", "--limit", "5", "--output", "json"],
            "qbt-rules jobs list --status pending --limit 5 --json",
        ),
        (["--job-status", "abc"], "qbt-rules jobs status abc"),
        (["--cancel-job", "abc", "--output=json"], "qbt-rules jobs cancel abc --json"),
        (["--stats"], "qbt-rules stats"),
        (["--validate", "-c", "my config.yaml"], "qbt-rules validate --config 'my config.yaml'"),
        (["--list-rules", "--output", "json"], "qbt-rules rules list --json"),
        (["--version"], "qbt-rules version"),
        (["--trace", "--context", "a b"], "qbt-rules execute --context 'a b'"),
        (["--hash"], "qbt-rules execute --hash ''"),
    ],
)
def test_old_style_invocations_name_the_new_command(argv: list[str], command: str) -> None:
    hint = cli.old_style_hint(argv)
    assert hint is not None
    assert f"  run:        {command}\n" in hint


def test_old_style_hint_explains_removed_settings_flags() -> None:
    hint = cli.old_style_hint(
        ["--serve", "--server-port", "8080", "--server-workers", "2", "--trace"]
    )
    assert hint is not None
    assert "--server-port is gone: set QBT_RULES_LISTEN_PORT" in hint
    assert "--server-workers is gone: the server is one process" in hint
    assert "--trace is gone: set QBT_RULES_LOGGING_TRACE_MODE=true" in hint
    assert "Run external program" not in hint


def test_old_style_hook_names_the_new_hook_line() -> None:
    hint = cli.old_style_hint(["--context", "torrent-imported", "--hash", "%I"])
    assert hint is not None
    assert 'qbt-rules execute --context torrent-imported --hash "%I"' in hint


@pytest.mark.parametrize(
    "argv", [[], ["serve"], ["--help"], ["execute", "--context", "x"], ["-c", "x", "config"]]
)
def test_new_style_invocations_get_no_hint(argv: list[str]) -> None:
    assert cli.old_style_hint(argv) is None


def test_main_refuses_the_old_form_with_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["qbt-rules", "--context", "torrent-imported"])
    monkeypatch.setattr(cli, "app", lambda: pytest.fail("the app ran"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "the 0.10.x flags-only form is gone" in err
    assert "qbt-rules execute --context torrent-imported" in err
