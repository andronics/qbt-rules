"""The app itself: probes, the lifespan's background threads, the JSON encoding."""

import dataclasses
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qbt_rules import api, metrics
from qbt_rules.config import Config, load_config
from qbt_rules.queue_manager import QueueManager
from qbt_rules.worker import Worker


@pytest.fixture
def settings(tmp_path: Path) -> Config:
    return load_config(tmp_path / "missing.yaml", environ={"QBT_RULES_STATE_DIR": str(tmp_path)})


class StubWorker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(self, stop: threading.Event) -> None:
        self.started.set()
        stop.wait()
        self.stopped.set()

    def is_alive(self) -> bool:
        return self.started.is_set() and not self.stopped.is_set()

    def get_status(self) -> dict[str, Any]:
        return {"running": self.is_alive(), "last_job_completed": None}


def _services(worker: api.WorkerLike) -> api.Services:
    queue = MagicMock()
    queue.health_check.return_value = True
    queue.count_jobs.return_value = 0
    queue.get_queue_depth.return_value = 0
    return api.Services(queue=cast(QueueManager, queue), worker=worker, rules=None)


def test_healthz_is_dependency_free(settings: Config) -> None:
    # No services: the lifespan hasn't built them, and liveness doesn't care
    response = TestClient(api.create_app(settings)).get("/healthz")
    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}\n'


def test_routes_are_503_until_the_services_exist(settings: Config) -> None:
    client = TestClient(api.create_app(settings))
    for path in ("/readyz", "/api/health", "/"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert response.json() == {
            "error": "Service Unavailable",
            "message": "qbt-rules is starting",
        }


def test_lifespan_starts_and_stops_the_worker(settings: Config) -> None:
    worker = StubWorker()
    app = api.create_app(settings, _services(worker))
    with TestClient(app) as client:
        assert worker.started.wait(5)
        assert client.get("/readyz").json() == {"status": "ready"}
        assert client.get("/api/health").json()["worker"]["status"] == "running"
    assert worker.stopped.is_set()


def test_ready_fails_naming_a_dead_thread(settings: Config) -> None:
    class ExitingWorker(StubWorker):
        def run(self, stop: threading.Event) -> None:
            return  # as a thread that returned early, or raised

    app = api.create_app(settings, _services(ExitingWorker()))
    with TestClient(app) as client:
        deadline = time.monotonic() + 5
        while not app.state.threads.dead() and time.monotonic() < deadline:
            time.sleep(0.01)
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {
            "error": "Service Unavailable",
            "message": "background thread not running: worker",
        }
        # Liveness stays dependency-free
        assert client.get("/healthz").status_code == 200


def test_thread_names_are_unique() -> None:
    threads = api.BackgroundThreads()
    threads.add("worker", lambda stop: None)
    with pytest.raises(ValueError, match="registered twice"):
        threads.add("worker", lambda stop: None)


def test_a_thread_that_misses_its_join_timeout_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    release = threading.Event()
    threads = api.BackgroundThreads(join_timeout=0.05)

    def stuck(stop: threading.Event) -> None:
        release.wait(5)

    threads.add("stuck", stuck)
    threads.start()
    threads.shutdown()
    release.set()
    assert "Background thread stuck did not stop in time" in caplog.text


def test_scheduler_runs_only_with_entries(settings: Config) -> None:
    class StubScheduler:
        def __init__(self, entries: bool) -> None:
            self.has_entries = entries

        def run(self, stop: threading.Event) -> None:
            stop.wait()

    for entries, expected in ((False, ["worker"]), (True, ["worker", "scheduler"])):
        services = dataclasses.replace(_services(StubWorker()), scheduler=StubScheduler(entries))
        app = api.create_app(settings, services)
        assert app.state.threads.dead() == expected


def test_lifespan_builds_the_services_from_the_settings(settings: Config) -> None:
    """No services given: the real queue, worker and (empty) scheduler, closed on exit"""
    app = api.create_app(settings)
    with TestClient(app) as client:
        services: api.Services = app.state.services
        assert isinstance(services.worker, Worker)
        deadline = time.monotonic() + 5
        while not services.worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert client.get("/readyz").json() == {"status": "ready"}
        health = client.get("/api/health").json()
        assert health["queue"]["backend"] == "SQLiteQueue"
        assert health["config_problems"][0].startswith("server.api_key is not set")
        worker = services.worker
    assert not worker.is_alive()
    assert (settings.state_dir / "qbt-rules.db").exists()


def test_build_services_passes_the_settings_on(tmp_path: Path) -> None:
    environ = {
        "QBT_RULES_STATE_DIR": str(tmp_path),
        "QBT_RULES_NOTIFICATIONS_WEBHOOK_URL": "https://hooks.example/x",
        "QBT_RULES_INTEGRATIONS_SONARR_URL": "http://sonarr:8989",
        "QBT_RULES_INTEGRATIONS_SONARR_API_KEY": "s0narr",
        "QBT_RULES_QUEUE_CLEANUP_AFTER": "1d",
    }
    settings = load_config(tmp_path / "missing.yaml", environ=environ)
    services = api.build_services(settings)
    try:
        worker = services.worker
        assert isinstance(worker, Worker)
        assert worker.notifications_config == {
            "webhook_url": "https://hooks.example/x",
            "service": "generic",
        }
        assert worker.integrations_config == {
            "sonarr": {"url": "http://sonarr:8989", "api_key": "s0narr"},
            "radarr": {"url": None, "api_key": None},
            "trackie": {"url": None, "max_age": 3 * 3600, "timeout": 10.0},
        }
        assert worker.cleanup_after == 86400
        assert services.rules is not None
        assert services.rules.settings is settings
    finally:
        assert services.close is not None
        services.close()


class TestCompatJSONResponse:
    """Flask's jsonify, byte for byte, with ISO 8601 for datetimes"""

    def test_sorted_compact_with_a_newline(self) -> None:
        body = api.CompatJSONResponse({"b": 1, "a": [1, {"d": None, "c": True}]}).body
        assert body == b'{"a":[1,{"c":true,"d":null}],"b":1}\n'

    def test_non_ascii_is_escaped(self) -> None:
        assert api.CompatJSONResponse({"x": "café"}).body == b'{"x":"caf\\u00e9"}\n'

    def test_datetimes_are_iso_8601(self) -> None:
        at = datetime(2026, 11, 3, 12, 0, 0, 123456, tzinfo=UTC)
        body = api.CompatJSONResponse({"at": at, "day": at.date()}).body
        assert body == b'{"at":"2026-11-03T12:00:00.123456+00:00","day":"2026-11-03"}\n'

    def test_other_objects_are_refused(self) -> None:
        with pytest.raises(TypeError, match="object is not JSON serialisable"):
            api.CompatJSONResponse({"x": object()})


def test_openapi_documents_the_routes(settings: Config) -> None:
    app: FastAPI = api.create_app(settings)
    paths = app.openapi()["paths"]
    assert set(paths) == {
        "/healthz",
        "/readyz",
        "/api/execute",
        "/api/jobs",
        "/api/jobs/{job_id}",
        "/api/health",
        "/api/stats",
        "/api/version",
        "/api/rules/source",
        "/api/rules/validate",
        "/api/rules/history",
        "/api/rules/history/{version_id}",
        "/api/rules/catalog",
        "/api/config/source",
        "/metrics",
    }
    # Every operation has a summary (the wiki's table) and a documented success body
    for path, ops in paths.items():
        for op in ops.values():
            assert op["summary"]
            success = next(v for k, v in op["responses"].items() if k.startswith("2"))
            if path == "/metrics":  # Prometheus text, not JSON
                assert set(success["content"]) == {metrics.CONTENT_TYPE}
                continue
            assert success["content"]["application/json"]["schema"]
    put = paths["/api/rules/source"]["put"]
    assert "requestBody" in put
    assert {"412", "422", "428"} <= set(put["responses"])


# -- Error names: an explicit table, not Python 3.13's HTTPStatus phrases ------------------------

OLD_NAMES = {
    413: "Payload Too Large",
    414: "URI Too Long",
    416: "Requested Range Not Satisfiable",
    422: "Unprocessable Entity",
}


@pytest.mark.parametrize(("status", "name"), OLD_NAMES.items())
def test_error_names_keep_the_old_phrases(status: int, name: str) -> None:
    body = api.error_response(status, "m").body
    assert body == f'{{"error":"{name}","message":"m"}}\n'.encode()


def test_python_changed_these_phrases() -> None:
    """Why the table exists: HTTPStatus would answer 3.13's RFC 9110 names for three of them."""
    from http import HTTPStatus

    changed = {s for s, name in OLD_NAMES.items() if HTTPStatus(s).phrase != name}
    assert changed >= {413, 416, 422}


@pytest.mark.parametrize("status", [414, 416])
def test_an_http_exception_gets_the_table_name(settings: Config, status: int) -> None:
    from fastapi import HTTPException

    app = api.create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise HTTPException(status, "detail")

    response = TestClient(app).get("/boom")
    assert response.status_code == status
    assert response.json() == {"error": OLD_NAMES[status], "message": "detail"}


def test_the_goldens_agree() -> None:
    """The 413 and 422 goldens (the only two statuses 0.10.x answered in JSON) carry the table's
    names, so the goldens and the table can't drift apart."""
    import json

    goldens = Path(__file__).parents[1] / "golden" / "responses"
    for backend in ("sqlite", "redis"):
        for case, status in (
            ("rules_validate_413_oversized", 413),
            ("rules_save_422_invalid", 422),
        ):
            golden = json.loads((goldens / backend / f"{case}.json").read_text())
            assert golden["status"] == status
            assert json.loads(golden["body"])["error"] == api.STATUS_NAMES[status]
