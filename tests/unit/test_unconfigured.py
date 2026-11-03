"""The server with no configuration at all: how the image's smoke test starts it.

It starts, /api/health answers 200 and lists what's missing, authenticated requests get a 503
that says what to set, the dashboard's login page says it too, and the rules editor can create
rules.yml on its first save.
"""

import dataclasses
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import httpx2
import pytest
from fastapi.testclient import TestClient
from interpose.secret import Secret

from qbt_rules import api
from qbt_rules.config_loader import Config, load_config
from qbt_rules.queue_manager import QueueManager


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """No config.yaml, no rules.yml, no variables: every default"""
    (tmp_path / "etc").mkdir()
    environ = {"QBT_RULES_STATE_DIR": str(tmp_path / "state")}
    return load_config(tmp_path / "etc" / "config.yaml", environ)


def _client(config: Config, api_key: str = "") -> TestClient:
    queue = MagicMock()
    queue.health_check.return_value = True
    queue.count_jobs.return_value = 0
    queue.get_queue_depth.return_value = 0
    worker = MagicMock()
    worker.is_alive.return_value = True
    worker.get_status.return_value = {"running": True, "last_job_completed": None}
    if api_key:
        config.settings = dataclasses.replace(config.settings, api_key=Secret(api_key))
    services = api.Services(
        queue=cast(QueueManager, queue), worker=cast(api.WorkerLike, worker), rules=config
    )
    return TestClient(api.create_app(config.settings, services), follow_redirects=False)


def _json(response: httpx2.Response) -> dict[str, Any]:
    data = response.json()
    assert isinstance(data, dict)
    return data


def test_health_is_200_and_lists_the_problem(config: Config) -> None:
    response = _client(config).get("/api/health")
    assert response.status_code == 200
    data = _json(response)
    assert data["status"] == "healthy"
    assert len(data["config_problems"]) == 1
    assert data["config_problems"][0].startswith("server.api_key is not set")


def test_health_has_no_problems_key_when_configured(tmp_path: Path) -> None:
    environ = {"QBT_RULES_SERVER_API_KEY": "k3y", "QBT_RULES_STATE_DIR": str(tmp_path)}
    config = load_config(tmp_path / "config.yaml", environ)
    assert "config_problems" not in _json(_client(config, "k3y").get("/api/health"))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/jobs"),
        ("GET", "/api/stats"),
        ("POST", "/api/execute"),
        ("GET", "/api/rules/source"),
        ("GET", "/api/config/source"),
    ],
)
def test_authenticated_requests_are_503(config: Config, method: str, path: str) -> None:
    # Any key, even an empty one, must not match an unset API key
    response = _client(config).request(method, path, headers={"X-API-Key": ""})
    assert response.status_code == 503
    assert "No API key is configured" in _json(response)["message"]


def test_dashboard_and_login_say_why(config: Config) -> None:
    client = _client(config)
    assert client.get("/").status_code == 302
    page = client.get("/login").text
    assert "No API key is configured on the server" in page
    # And no key logs in
    assert client.post("/login", data={"key": "anything", "next": "/"}).status_code == 302
    assert client.get("/").status_code == 302


def test_config_source_without_a_config_file(config: Config) -> None:
    data = _json(_client(config, "k").get("/api/config/source", headers={"X-API-Key": "k"}))
    assert data["content"] == ""
    assert data["path"] == str(config.config_file)
    assert "does not exist" in data["issues"][0]["message"]


def test_the_editor_creates_rules_yml(config: Config) -> None:
    client = _client(config, "k")
    key = {"X-API-Key": "k"}
    source = _json(client.get("/api/rules/source", headers=key))
    assert (source["content"], source["modified_at"], source["editable"]) == ("", None, True)

    rules = "rules:\n  - {id: first, conditions: [], actions: [{type: stop}]}\n"
    response = client.put(
        "/api/rules/source", json={"content": rules}, headers={**key, "If-Match": source["etag"]}
    )

    assert response.status_code == 200
    assert _json(response)["saved"] is True
    assert config.rules_file.read_text() == rules
    assert [r["id"] for r in config.get_rules()] == ["first"]
