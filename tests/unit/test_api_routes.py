"""The JSON API's routes (api.py, api_rules.py), ported from the Flask app's tests.

The goldens (tests/golden) pin every body byte for byte; these check the behaviour behind
them: what reaches the queue, each branch, auth by key and by session, and the errors.
"""

import dataclasses
import logging
import os
import re
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import httpx2
import pytest
from fastapi.testclient import TestClient
from interpose.secret import Secret

from qbt_rules import api, metrics
from qbt_rules.config import Config, load_config
from qbt_rules.config_loader import Config as RulesConfig
from qbt_rules.queue_manager import JobStatus, QueueManager

API_KEY = "test-api-key-12345"
KEY = {"X-API-Key": API_KEY}

JOB: dict[str, Any] = {
    "job_id": "job-1",
    "context": "test",
    "hash": None,
    "dry_run": False,
    "status": JobStatus.PENDING,
    "created_at": "2025-01-01T12:00:00+00:00",
    "started_at": None,
    "completed_at": None,
    "result": None,
    "error": None,
}


class StubWorker:
    def __init__(self) -> None:
        self.alive = True
        self.running = True

    def run(self, stop: Any) -> None:
        stop.wait()

    def is_alive(self) -> bool:
        return self.alive

    def get_status(self) -> dict[str, Any]:
        return {"running": self.running, "last_job_completed": "2025-01-01T12:00:00+00:00"}


@pytest.fixture
def queue() -> MagicMock:
    queue = MagicMock()
    queue.__class__.__name__ = "SQLiteQueue"
    queue.enqueue.return_value = "job-1"
    queue.get_job.return_value = dict(JOB)
    queue.list_jobs.return_value = []
    queue.count_jobs.return_value = 0
    queue.get_queue_depth.return_value = 0
    queue.health_check.return_value = True
    queue.cancel_job.return_value = True
    queue.get_stats.return_value = {
        "total_jobs": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "average_execution_time": None,
    }
    return queue


@pytest.fixture
def worker() -> StubWorker:
    return StubWorker()


@pytest.fixture
def settings(tmp_path: Path) -> Config:
    environ = {"QBT_RULES_SERVER_API_KEY": API_KEY, "QBT_RULES_STATE_DIR": str(tmp_path)}
    return load_config(tmp_path / "missing.yaml", environ=environ)


def _client(settings: Config, queue: MagicMock, worker: StubWorker, **kwargs: Any) -> TestClient:
    services = api.Services(
        queue=cast(QueueManager, queue), worker=worker, rules=kwargs.pop("rules", None)
    )
    if kwargs:
        settings = dataclasses.replace(settings, **kwargs)
    return TestClient(api.create_app(settings, services), follow_redirects=False)


@pytest.fixture
def client(settings: Config, queue: MagicMock, worker: StubWorker) -> TestClient:
    return _client(settings, queue, worker)


def _json(response: httpx2.Response) -> dict[str, Any]:
    data = response.json()
    assert isinstance(data, dict)
    return data


# -- auth ------------------------------------------------------------------------------------------


class TestAuth:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/execute"),
            ("GET", "/api/jobs"),
            ("GET", "/api/jobs/job-1"),
            ("DELETE", "/api/jobs/job-1"),
            ("GET", "/api/stats"),
            ("GET", "/api/rules/source"),
            ("GET", "/api/rules/catalog"),
        ],
    )
    def test_no_key_is_401(self, client: TestClient, method: str, path: str) -> None:
        response = client.request(method, path)
        assert response.status_code == 401
        assert _json(response) == {
            "error": "Unauthorized",
            "message": "Invalid or missing API key",
        }

    def test_key_as_header_or_query(self, client: TestClient) -> None:
        assert client.get("/api/jobs", headers=KEY).status_code == 200
        assert client.get(f"/api/jobs?key={API_KEY}").status_code == 200

    def test_wrong_key_is_401(self, client: TestClient) -> None:
        assert client.get("/api/jobs?key=wrong").status_code == 401
        assert client.get("/api/jobs", headers={"X-API-Key": "wrong"}).status_code == 401

    def test_query_key_wins_over_the_header(self, client: TestClient) -> None:
        assert client.get("/api/jobs?key=wrong", headers=KEY).status_code == 401

    def test_compared_in_constant_time(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []
        real = secrets.compare_digest

        def spy(a: str, b: str) -> bool:
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(secrets, "compare_digest", spy)
        client.get("/api/jobs?key=guess")
        assert calls == [("guess", API_KEY)]

    def test_no_configured_key_is_503(
        self, tmp_path: Path, queue: MagicMock, worker: StubWorker
    ) -> None:
        settings = load_config(tmp_path / "missing.yaml", environ={})
        client = _client(settings, queue, worker)
        response = client.get("/api/jobs", headers={"X-API-Key": ""})
        assert response.status_code == 503
        assert "No API key is configured" in _json(response)["message"]

    def test_unauthenticated_routes(self, client: TestClient) -> None:
        for path in ("/healthz", "/api/health", "/api/version"):
            assert client.get(path).status_code == 200, path


# -- /api/execute --------------------------------------------------------------------------------


class TestExecute:
    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "TRUE"])
    def test_dry_run_true(self, client: TestClient, queue: MagicMock, value: str) -> None:
        response = client.post(f"/api/execute?context=manual&dry_run={value}", headers=KEY)
        assert response.status_code == 202
        queue.enqueue.assert_called_once_with(context="manual", hash_filter=None, dry_run=True)

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_dry_run_false(self, client: TestClient, queue: MagicMock, value: str) -> None:
        assert client.post(f"/api/execute?dry_run={value}", headers=KEY).status_code == 202
        queue.enqueue.assert_called_once_with(context=None, hash_filter=None, dry_run=False)

    @pytest.mark.parametrize("value", ["maybe", "", "2"])
    def test_unrecognised_dry_run_is_400(
        self, client: TestClient, queue: MagicMock, value: str
    ) -> None:
        response = client.post(f"/api/execute?dry_run={value}", headers=KEY)
        assert response.status_code == 400
        assert _json(response)["message"].startswith("dry_run must be one of")
        queue.enqueue.assert_not_called()

    def test_queues_with_context_and_hash(self, client: TestClient, queue: MagicMock) -> None:
        response = client.post("/api/execute?context=nightly&hash=abc123", headers=KEY)
        assert response.status_code == 202
        queue.enqueue.assert_called_once_with(
            context="nightly", hash_filter="abc123", dry_run=False
        )
        queue.get_job.assert_called_once_with("job-1")
        assert _json(response) == JOB

    def test_a_queue_error_is_a_generic_500(
        self, client: TestClient, queue: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """#28 item 6: the exception is logged, never sent"""
        queue.enqueue.side_effect = RuntimeError("database is locked at /secret/path")
        response = client.post(f"/api/execute?key={API_KEY}")
        assert response.status_code == 500
        assert _json(response) == {
            "error": "Internal Server Error",
            "message": "An unexpected error occurred",
        }
        assert "database is locked" in caplog.text
        assert "Unhandled error: POST /api/execute" in caplog.text
        assert API_KEY not in caplog.text


# -- /api/jobs --------------------------------------------------------------------------------


class TestJobs:
    def test_list_passes_the_filters_on(self, client: TestClient, queue: MagicMock) -> None:
        queue.list_jobs.return_value = [JOB]
        queue.count_jobs.return_value = 7
        response = client.get(
            "/api/jobs?status=pending&context=nightly&limit=10&offset=5", headers=KEY
        )
        assert _json(response) == {"total": 7, "limit": 10, "offset": 5, "jobs": [JOB]}
        queue.list_jobs.assert_called_once_with(
            status="pending", context="nightly", limit=10, offset=5
        )
        queue.count_jobs.assert_called_once_with(status="pending", context="nightly")

    def test_list_defaults(self, client: TestClient, queue: MagicMock) -> None:
        client.get("/api/jobs", headers=KEY)
        queue.list_jobs.assert_called_once_with(status=None, context=None, limit=50, offset=0)

    def test_limit_is_capped_and_echoed(self, client: TestClient, queue: MagicMock) -> None:
        """#28 item 3: the limit applied, not the one asked for"""
        assert _json(client.get("/api/jobs?limit=500", headers=KEY))["limit"] == 100
        assert queue.list_jobs.call_args.kwargs["limit"] == 100

    @pytest.mark.parametrize("query", ["limit=abc", "offset=x", "limit=-1", "offset=-5"])
    def test_bad_numbers_are_400(self, client: TestClient, query: str) -> None:
        """#28 item 1: was an unhandled 500"""
        response = client.get(f"/api/jobs?{query}", headers=KEY)
        assert response.status_code == 400
        body = _json(response)
        assert body["error"] == "Bad Request"
        assert body["message"].startswith(query.split("=")[0] + ": ")

    def test_invalid_status_is_400(self, client: TestClient) -> None:
        response = client.get("/api/jobs?status=bogus", headers=KEY)
        assert response.status_code == 400
        assert _json(response)["message"] == "Invalid status: bogus"

    def test_get(self, client: TestClient, queue: MagicMock) -> None:
        assert _json(client.get("/api/jobs/job-1", headers=KEY)) == JOB
        queue.get_job.assert_called_once_with("job-1")

    def test_get_missing_is_404(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_job.return_value = None
        response = client.get("/api/jobs/nope", headers=KEY)
        assert response.status_code == 404
        assert _json(response)["message"] == "Job not found: nope"

    def test_cancel_pending(self, client: TestClient, queue: MagicMock) -> None:
        response = client.delete("/api/jobs/job-1", headers=KEY)
        assert _json(response) == {
            "job_id": "job-1",
            "status": "cancelled",
            "message": "Job cancelled successfully",
        }
        queue.cancel_job.assert_called_once_with("job-1")

    @pytest.mark.parametrize("status", ["processing", "completed", "failed", "cancelled"])
    def test_cancel_after_pending_is_400(
        self, client: TestClient, queue: MagicMock, status: str
    ) -> None:
        queue.get_job.return_value = {**JOB, "status": status}
        response = client.delete("/api/jobs/job-1", headers=KEY)
        assert response.status_code == 400
        assert _json(response)["message"] == f"Cannot cancel job in status: {status}"
        queue.cancel_job.assert_not_called()

    def test_cancel_missing_is_404(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_job.return_value = None
        assert client.delete("/api/jobs/job-1", headers=KEY).status_code == 404

    def test_cancel_that_fails_is_500(self, client: TestClient, queue: MagicMock) -> None:
        queue.cancel_job.return_value = False
        response = client.delete("/api/jobs/job-1", headers=KEY)
        assert response.status_code == 500
        assert _json(response)["message"] == "Failed to cancel job"


# -- health, stats, version ---------------------------------------------------------------------


class TestHealth:
    def test_healthy(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_queue_depth.return_value = 2
        body = _json(client.get("/api/health"))
        assert body["status"] == "healthy"
        assert body["queue"] == {"backend": "SQLiteQueue", "pending_jobs": 2, "processing_jobs": 0}
        assert body["worker"] == {
            "status": "running",
            "last_job_completed": "2025-01-01T12:00:00+00:00",
        }
        assert "config_problems" not in body
        assert body["timestamp"].endswith("+00:00")

    @pytest.mark.parametrize(
        ("broken", "error"),
        [
            ("queue", "Queue backend not accessible"),
            ("worker", "Worker thread not running"),
            ("stuck", "Too many processing jobs: 6"),
        ],
    )
    def test_unhealthy_is_503(
        self, client: TestClient, queue: MagicMock, worker: StubWorker, broken: str, error: str
    ) -> None:
        if broken == "queue":
            queue.health_check.return_value = False
        elif broken == "worker":
            worker.alive = False
        else:
            queue.count_jobs.return_value = 6
        response = client.get("/api/health")
        assert response.status_code == 503
        body = _json(response)
        assert (body["status"], body["errors"]) == ("unhealthy", [error])

    def test_every_problem_is_listed(
        self, client: TestClient, queue: MagicMock, worker: StubWorker
    ) -> None:
        queue.health_check.return_value = False
        worker.alive = False
        assert len(_json(client.get("/api/health"))["errors"]) == 2

    def test_stats(self, client: TestClient, queue: MagicMock, worker: StubWorker) -> None:
        queue.get_stats.return_value = {
            "total_jobs": 10,
            "pending": 1,
            "processing": 2,
            "completed": 5,
            "failed": 1,
            "cancelled": 1,
            "average_execution_time": 1.24,
        }
        queue.get_queue_depth.return_value = 1
        worker.running = False
        body = _json(client.get("/api/stats", headers=KEY))
        assert body["jobs"] == {
            "total": 10,
            "pending": 1,
            "processing": 2,
            "completed": 5,
            "failed": 1,
            "cancelled": 1,
        }
        assert body["performance"] == {"average_execution_time": "1.24s"}
        assert body["queue"] == {"backend": "SQLiteQueue", "depth": 1}
        assert body["worker"]["status"] == "stopped"

    def test_stats_without_timings(self, client: TestClient) -> None:
        body = _json(client.get("/api/stats", headers=KEY))
        assert body["performance"] == {"average_execution_time": None}

    def test_version(self, client: TestClient) -> None:
        body = _json(client.get("/api/version"))
        assert set(body) == {"version", "api_version", "python_version"}
        assert body["api_version"] == "1.0"


# -- errors --------------------------------------------------------------------------------------


class TestErrors:
    def test_unknown_path_is_a_json_404(self, client: TestClient) -> None:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.content == b'{"error":"Not Found","message":"Endpoint not found"}\n'

    def test_wrong_method_is_a_json_405(self, client: TestClient) -> None:
        """#28 item 5: was Werkzeug's HTML page"""
        response = client.put("/api/jobs", headers=KEY)
        assert response.status_code == 405
        assert response.headers["Allow"] == "GET"
        assert _json(response) == {
            "error": "Method Not Allowed",
            "message": "PUT is not allowed for this endpoint",
        }

    def test_a_declared_body_over_2_mb_is_413(self, client: TestClient) -> None:
        response = client.post(
            "/api/rules/validate", headers={**KEY, "Content-Length": str(3 * 1024 * 1024)}
        )
        assert response.status_code == 413
        assert _json(response)["message"] == "Request body exceeds 2 MB"

    def test_a_streamed_body_over_2_mb_is_413(self, client: TestClient) -> None:
        def chunks() -> Iterator[bytes]:
            for _ in range(3):
                yield b"x" * (1024 * 1024)

        response = client.post(
            "/api/rules/validate",
            headers={**KEY, "Content-Type": "application/json"},
            content=chunks(),
        )
        assert response.status_code == 413

    def test_a_malformed_content_length_is_ignored(self, client: TestClient) -> None:
        response = client.post(
            "/api/rules/validate", headers={**KEY, "Content-Length": "abc"}, content=b""
        )
        assert response.status_code == 400

    def test_unhandled_errors_are_generic(
        self, client: TestClient, queue: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        queue.get_stats.side_effect = KeyError("internal detail")
        response = client.get("/api/stats", headers=KEY)
        assert response.status_code == 500
        assert "internal detail" not in response.text
        assert "internal detail" in caplog.text


# -- HTTP metrics ---------------------------------------------------------------------------------


def test_json_routes_are_counted_by_name(
    settings: Config, queue: MagicMock, worker: StubWorker, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        metrics.Metrics,
        "http_request",
        lambda self, method, endpoint, status, seconds: recorded.append((method, endpoint, status)),
    )
    on = _client(settings, queue, worker, metrics_enabled=True)
    on.get("/api/jobs", headers=KEY)
    on.get("/api/nope")
    on.get("/login")
    on.get("/static/editor.js")
    on.get("/metrics", headers=KEY)  # a scrape doesn't count itself
    assert recorded == [
        ("GET", "list_jobs", 200),
        ("GET", "unknown", 404),
        ("GET", "login", 200),
        ("GET", "static", 200),
    ]


def test_nothing_is_counted_while_metrics_are_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(
        metrics.Metrics, "http_request", lambda self, *args: recorded.append("counted")
    )
    client.get("/api/jobs", headers=KEY)
    assert recorded == []


def test_endpoint_names() -> None:
    def metrics_endpoint() -> None: ...

    def login_submit() -> None: ...

    assert api.endpoint_name({"endpoint": metrics_endpoint}) is None
    assert api.endpoint_name({"endpoint": login_submit}) == "login"
    assert api.endpoint_name({}) == "unknown"


# -- the rules editor, and the dashboard's session ---------------------------------------------


class TestEditor:
    RULES = (
        "rules:\n  - id: a  # keep this comment\n    conditions: []\n    actions: [{type: stop}]\n"
    )

    @pytest.fixture
    def config_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "config.yaml").write_text(
            "server:\n  api_key: hunter2\nqbittorrent:\n  host: http://localhost:8080\n"
            "schedule:\n  - {cron: '0 * * * *', context: hourly}\n"
        )
        (tmp_path / "rules.yml").write_text(self.RULES)
        return tmp_path

    @pytest.fixture
    def rules(self, config_dir: Path) -> RulesConfig:
        environ = {"QBT_RULES_STATE_DIR": str(config_dir / "state")}
        settings = load_config(config_dir / "config.yaml", environ)
        return RulesConfig(dataclasses.replace(settings, api_key=Secret(API_KEY)))

    @pytest.fixture
    def client(self, rules: RulesConfig, queue: MagicMock, worker: StubWorker) -> TestClient:
        return _client(rules.settings, queue, worker, rules=rules)

    def post_login(self, client: TestClient, key: str = API_KEY) -> httpx2.Response:
        """Post the dashboard's login form, with the CSRF token it carries"""
        form = client.get("/login").text
        match = re.search(r'name="csrf_token" value="([^"]+)"', form)
        assert match is not None
        data = {"key": key, "next": "/rules/edit", "csrf_token": match.group(1)}
        return client.post("/login", data=data)

    def login(self, client: TestClient) -> str:
        """Log in through the dashboard's form and return the editor page's CSRF token"""
        response = self.post_login(client)
        assert response.status_code == 302
        page = client.get("/rules/edit").text
        match = re.search(r'csrfToken: "([^"]+)"', page)
        assert match is not None
        return match.group(1)

    def put(self, client: TestClient, content: str, etag: str, **headers: str) -> httpx2.Response:
        return client.put(
            "/api/rules/source",
            json={"content": content},
            headers={**headers, "If-Match": f'"{etag}"'},
        )

    def etag(self, client: TestClient) -> str:
        etag: str = _json(client.get("/api/rules/source", headers=KEY))["etag"]
        return etag

    def test_source(self, client: TestClient, config_dir: Path) -> None:
        response = client.get("/api/rules/source", headers=KEY)
        data = _json(response)
        assert data["content"] == self.RULES
        assert response.headers["ETag"] == f'"{data["etag"]}"'
        assert response.headers["Cache-Control"] == "no-store"
        assert data["editable"] is True
        assert data["path"] == str(config_dir / "rules.yml")

    def test_validate(self, client: TestClient) -> None:
        response = client.post(
            "/api/rules/validate",
            headers=KEY,
            json={"content": "rules:\n  - id: a\n    actions: []\n"},
        )
        data = _json(response)
        assert data["valid"] is False
        assert "missing required field: 'conditions'" in data["issues"][0]["message"]

    @pytest.mark.parametrize(
        "body",
        [
            {"json": {}},
            {"json": {"content": 3}},
            {"json": ["content"]},
            {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
            {"content": b'{"content": "x"}', "headers": {"Content-Type": "text/plain"}},
        ],
    )
    def test_validate_needs_a_content_string(self, client: TestClient, body: Any) -> None:
        headers = {**KEY, **body.pop("headers", {})}
        response = client.post("/api/rules/validate", headers=headers, **body)
        assert response.status_code == 400
        assert _json(response)["message"] == "Body must be JSON with a 'content' string"

    def test_a_json_suffix_type_is_json(self, client: TestClient) -> None:
        response = client.post(
            "/api/rules/validate",
            headers={**KEY, "Content-Type": "application/merge-patch+json"},
            content=b'{"content": "rules: []\\n"}',
        )
        assert response.status_code == 200

    def test_catalog_includes_schedule_contexts(self, client: TestClient) -> None:
        data = _json(client.get("/api/rules/catalog", headers=KEY))
        assert "delete_torrent" in data["actions"]
        assert data["schedule_contexts"] == ["hourly"]

    def test_config_source_is_redacted(self, client: TestClient) -> None:
        response = client.get("/api/config/source", headers=KEY)
        data = _json(response)
        assert "hunter2" not in data["content"]
        assert data["redacted"] == ["server.api_key"]
        assert response.headers["Cache-Control"] == "no-store"

    def test_save_writes_reloads_and_keeps_history(
        self, client: TestClient, config_dir: Path, rules: RulesConfig
    ) -> None:
        new = self.RULES.replace("id: a", "id: renamed")
        response = self.put(client, new, self.etag(client), **KEY)
        data = _json(response)
        assert data["saved"] is True
        assert response.headers["ETag"] == f'"{data["etag"]}"'
        assert (config_dir / "rules.yml").read_text() == new
        assert rules.get_rules()[0]["id"] == "renamed"

        versions = _json(client.get("/api/rules/history", headers=KEY))["versions"]
        assert len(versions) == 1
        old = _json(client.get(f"/api/rules/history/{versions[0]['id']}", headers=KEY))
        assert old["content"] == self.RULES

    def test_a_failed_reload_still_saves(
        self,
        client: TestClient,
        rules: RulesConfig,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def boom(force: bool = False) -> None:
            raise RuntimeError("resolver exploded")

        monkeypatch.setattr(rules, "reload_rules", boom)
        response = self.put(client, self.RULES + "\n", self.etag(client), **KEY)
        assert _json(response)["saved"] is True
        assert "reloading it failed: resolver exploded" in caplog.text

    def test_unchanged_content_is_not_saved(self, client: TestClient) -> None:
        response = self.put(client, self.RULES, self.etag(client), **KEY)
        assert _json(response)["saved"] is False

    def test_no_if_match_is_428(self, client: TestClient) -> None:
        response = client.put("/api/rules/source", json={"content": self.RULES}, headers=KEY)
        assert response.status_code == 428

    def test_etag_in_the_body(self, client: TestClient) -> None:
        response = client.put(
            "/api/rules/source",
            json={"content": self.RULES + "\n", "etag": self.etag(client)},
            headers=KEY,
        )
        assert response.status_code == 200

    def test_stale_etag_is_412_with_the_current_file(
        self, client: TestClient, config_dir: Path
    ) -> None:
        etag = self.etag(client)
        (config_dir / "rules.yml").write_text(self.RULES + "# edited elsewhere\n")
        response = self.put(client, self.RULES.replace("id: a", "id: b"), etag, **KEY)
        assert response.status_code == 412
        assert _json(response)["current"]["content"].endswith("# edited elsewhere\n")

    def test_invalid_is_422_and_not_written(self, client: TestClient, config_dir: Path) -> None:
        bad = (
            "rules:\n  - id: a\n    conditions: []\n    actions:\n      - type: delete_torrent\n"
            '        params: {delete_files: "false"}\n'
        )
        response = self.put(client, bad, self.etag(client), **KEY)
        assert response.status_code == 422
        assert _json(response)["validation"]["counts"]["error"] == 1
        assert (config_dir / "rules.yml").read_text() == self.RULES

    def test_editor_disabled_is_read_only(
        self, rules: RulesConfig, queue: MagicMock, worker: StubWorker, config_dir: Path
    ) -> None:
        client = _client(rules.settings, queue, worker, rules=rules, editor_enabled=False)
        source = _json(client.get("/api/rules/source", headers=KEY))
        assert source["editable"] is False
        assert "editor_enabled" in source["readonly_reason"]
        assert self.put(client, self.RULES + "\n", source["etag"], **KEY).status_code == 403
        assert (config_dir / "rules.yml").read_text() == self.RULES

    def test_read_only_file_is_403(self, client: TestClient, config_dir: Path) -> None:
        if os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        (config_dir / "rules.yml").chmod(0o444)
        source = _json(client.get("/api/rules/source", headers=KEY))
        assert source["editable"] is False
        assert self.put(client, self.RULES + "\n", source["etag"], **KEY).status_code == 403

    def test_a_file_that_turns_read_only_is_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from qbt_rules.config_store import EditableFile, FileNotWritableError

        def refuse(self: EditableFile, content: str, etag: str) -> None:
            raise FileNotWritableError("rules.yml is read-only")

        monkeypatch.setattr(EditableFile, "write", refuse)
        response = self.put(client, self.RULES + "\n", self.etag(client), **KEY)
        assert response.status_code == 403
        assert _json(response)["message"] == "rules.yml is read-only"

    def test_history_version_not_found(self, client: TestClient) -> None:
        assert (
            client.get("/api/rules/history/20200101T000000000000Z", headers=KEY).status_code == 404
        )
        assert client.get("/api/rules/history/..%2Frules.yml", headers=KEY).status_code == 404

    def test_no_config_is_503(self, settings: Config, queue: MagicMock) -> None:
        bare = _client(settings, queue, StubWorker())
        for method, path in (
            ("GET", "/api/rules/source"),
            ("PUT", "/api/rules/source"),
            ("GET", "/api/rules/history"),
            ("GET", "/api/rules/history/x"),
            ("GET", "/api/config/source"),
        ):
            response = bare.request(method, path, headers=KEY, json={"content": ""})
            assert response.status_code == 503, path
        # The catalog works without one: no schedule contexts
        assert _json(bare.get("/api/rules/catalog", headers=KEY))["schedule_contexts"] == []

    # -- the session from the dashboard's login form ---------------------------------------------

    def test_session_reads_without_csrf(self, client: TestClient) -> None:
        self.login(client)
        assert client.get("/api/rules/source").status_code == 200
        assert client.get("/api/jobs/job-1").status_code == 200

    def test_session_only_routes_still_need_the_key(self, client: TestClient) -> None:
        self.login(client)
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/stats").status_code == 401

    def test_session_write_needs_the_csrf_token(self, client: TestClient, config_dir: Path) -> None:
        self.login(client)
        etag = self.etag(client)
        for headers in ({}, {"X-CSRF-Token": "wrong"}):
            response = self.put(client, self.RULES + "\n", etag, **headers)
            assert response.status_code == 403
            assert "CSRF" in _json(response)["message"]
        assert (config_dir / "rules.yml").read_text() == self.RULES

    def test_session_write_with_the_csrf_token(self, client: TestClient, config_dir: Path) -> None:
        token = self.login(client)
        response = self.put(client, self.RULES + "\n", self.etag(client), **{"X-CSRF-Token": token})
        assert response.status_code == 200
        assert (config_dir / "rules.yml").read_text() == self.RULES + "\n"

    def test_execute_with_the_session(self, client: TestClient, queue: MagicMock) -> None:
        token = self.login(client)
        assert client.post("/api/execute?dry_run=true").status_code == 403
        response = client.post("/api/execute?dry_run=true", headers={"X-CSRF-Token": token})
        assert response.status_code == 202
        queue.enqueue.assert_called_once_with(context=None, hash_filter=None, dry_run=True)

    def test_a_wrong_key_beats_the_session(self, client: TestClient) -> None:
        self.login(client)
        assert client.get("/api/rules/source?key=wrong").status_code == 401

    def test_the_session_cookie(self, client: TestClient) -> None:
        response = self.post_login(client)
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith("qbt_rules_session=")
        assert "samesite=lax" in cookie.lower()
        assert "httponly" in cookie.lower()
        assert "Max-Age=2678400" in cookie

    def test_a_wrong_login_is_no_session(self, client: TestClient) -> None:
        response = self.post_login(client, key="wrong")
        assert response.status_code == 302
        assert "error=1" in response.headers["Location"]
        assert "Set-Cookie" not in response.headers
        assert client.get("/api/rules/source").status_code == 401

    def test_a_key_in_a_dashboard_url_logs_in(self, client: TestClient) -> None:
        response = client.get(f"/rules?key={API_KEY}")
        assert response.status_code == 302
        assert response.headers["Location"] == "./rules"
        assert client.get("/api/rules/source").status_code == 200

    def test_a_flask_0_10_session_cookie_is_ignored(self, client: TestClient) -> None:
        """The one-time logout: the old cookie's name and format are both unknown"""
        client.cookies.set("session", "eyJhdXRoZW50aWNhdGVkIjp0cnVlfQ.Zz.abc")
        assert client.get("/api/rules/source").status_code == 401

    # -- the dashboard's pages (tests/unit/test_web.py has the rest) ------------------------------

    def test_editor_page_requires_login(self, client: TestClient) -> None:
        response = client.get("/rules/edit")
        assert response.status_code == 302
        assert response.headers["Location"] == "../login?next=%2Frules%2Fedit"

    def test_pages_render(self, client: TestClient) -> None:
        self.login(client)
        assert "vendor/ace/ace.js" in client.get("/rules/edit").text
        assert "./rules/edit#rule=a" in client.get("/rules").text
        assert client.get("/jobs").status_code == 200
        assert client.get("/").status_code == 200

    def test_static_assets_are_served(self, client: TestClient) -> None:
        for path in ("/static/editor.js", "/static/vendor/ace/ace.js"):
            assert client.get(path).status_code == 200

    def test_dashboard_405_is_json(self, client: TestClient) -> None:
        response = client.put("/login")
        assert response.status_code == 405
        assert _json(response)["error"] == "Method Not Allowed"


def test_error_logs_never_carry_the_key(
    client: TestClient, queue: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    queue.list_jobs.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.ERROR):
        client.get(f"/api/jobs?key={API_KEY}")
    assert caplog.records
    assert API_KEY not in caplog.text
