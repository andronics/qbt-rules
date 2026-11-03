import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from interpose.metrics import Counter

from qbt_rules import __version__
from qbt_rules.api import create_app
from qbt_rules.config import load_config


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(load_config(tmp_path / "missing.yaml", environ={}))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready(client: TestClient) -> None:
    assert client.get("/readyz").json() == {"status": "ready"}


def test_version(client: TestClient) -> None:
    assert client.get("/version").json() == {"version": __version__}


def test_lifespan_starts_and_stops_threads(app: FastAPI) -> None:
    started = threading.Event()
    stopped = threading.Event()

    def worker(stop: threading.Event) -> None:
        started.set()
        stop.wait()
        stopped.set()

    app.state.threads.add("worker", worker)
    with TestClient(app) as client:
        assert started.wait(5)
        assert client.get("/readyz").status_code == 200
    assert stopped.is_set()


def test_ready_fails_when_a_thread_dies(app: FastAPI) -> None:
    def exits(stop: threading.Event) -> None:
        return  # as a thread that returned early, or raised

    app.state.threads.add("exits", exits)
    with TestClient(app) as client:
        deadline = time.monotonic() + 5
        while not app.state.threads.dead() and time.monotonic() < deadline:
            time.sleep(0.01)
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"detail": "background thread not running: exits"}
        # Liveness stays dependency-free.
        assert client.get("/api/health").status_code == 200


def test_thread_names_are_unique(app: FastAPI) -> None:
    app.state.threads.add("worker", lambda stop: None)
    with pytest.raises(ValueError, match="registered twice"):
        app.state.threads.add("worker", lambda stop: None)


def test_metrics(app: FastAPI, client: TestClient) -> None:
    app.state.metrics.register(Counter("qbt_rules_jobs_total", "Jobs run")).inc()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    lines = response.text.splitlines()
    assert f'qbt_rules_build_info{{version="{__version__}"}} 1' in lines
    assert "qbt_rules_jobs_total 1" in lines
