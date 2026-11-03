"""The HTTP API.

The wiki's HTTP-API-Reference endpoint table is generated from this app's OpenAPI
schema (scripts/gen-wiki.py): give every route a `summary`, and a docstring when
it needs more than a line.

TODO(4c): The template skeleton, not served yet: the legacy Flask app in web.py serves
the API and dashboard until the FastAPI port (4c, 4d) lands here.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse
from interpose.metrics import CONTENT_TYPE, Gauge, Label, Registry

from qbt_rules import __description__, __version__
from qbt_rules.config import Config


class Target(Protocol):
    """A background thread's body: runs until `stop` is set."""

    def __call__(self, stop: threading.Event) -> None: ...


class BackgroundThreads:
    """Threads that run beside the API (pollers, workers, schedulers).

    `add` registers one before the app starts; the lifespan starts them all, and on
    shutdown sets `stop` and joins each for up to `join_timeout` seconds. A target
    runs until `stop` is set: loop on `while not stop.wait(interval):`. A thread
    that returns or raises is dead, and /readyz names it.
    """

    def __init__(self, join_timeout: float = 5.0) -> None:
        self.join_timeout = join_timeout
        self.stop = threading.Event()
        self._targets: dict[str, Target] = {}
        self._threads: list[threading.Thread] = []

    def add(self, name: str, target: Target) -> None:
        if name in self._targets:
            raise ValueError(f"background thread {name!r} is registered twice")
        self._targets[name] = target

    def start(self) -> None:
        self.stop.clear()
        # Daemon threads: one that misses its join timeout doesn't hold up the exit.
        self._threads = [
            threading.Thread(target=target, args=(self.stop,), name=name, daemon=True)
            for name, target in self._targets.items()
        ]
        for thread in self._threads:
            thread.start()

    def shutdown(self) -> None:
        self.stop.set()
        for thread in self._threads:
            thread.join(self.join_timeout)

    def dead(self) -> list[str]:
        """The registered threads not running: never started, returned or raised."""
        alive = {t.name for t in self._threads if t.is_alive()}
        return [name for name in self._targets if name not in alive]


def create_app(config: Config) -> FastAPI:
    # Prometheus metrics, served at /metrics. Register the app's own on this registry
    # (metrics.register(Counter(...))), here or in the code create_app wires up.
    # interpose's metrics aren't locked: change them on the event loop, or from one
    # thread per series, and create every label set at startup.
    metrics = Registry()
    metrics.register(
        Gauge(
            "qbt_rules_build_info",
            "The running version: always 1",
            [Label("version", [__version__])],
        )
    ).set(1, __version__)
    threads = BackgroundThreads()
    # Register background threads here, never at import, so the app can be built
    # without them: threads.add("worker", worker.run)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        threads.start()
        try:
            yield
        finally:
            threads.shutdown()

    app = FastAPI(
        title="qbt-rules",
        version=__version__,
        description=__description__,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.threads = threads
    app.state.metrics = metrics

    @app.get("/api/health", summary="Liveness: the process is up", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/readyz",
        summary="Readiness: able to serve requests",
        tags=["health"],
        responses={503: {"description": "Not ready: a background thread or dependency is down"}},
    )
    def readyz() -> dict[str, str]:
        # Also check what the service depends on (database, upstream API) here, and
        # answer 503 when it can't serve. Liveness must stay dependency-free.
        if dead := threads.dead():
            raise HTTPException(503, f"background thread not running: {', '.join(dead)}")
        return {"status": "ready"}

    @app.get("/version", summary="The running version", tags=["meta"])
    def get_version() -> dict[str, str]:
        return {"version": __version__}

    @app.get(
        "/metrics",
        summary="Prometheus metrics (text exposition)",
        tags=["meta"],
        response_class=PlainTextResponse,
    )
    async def get_metrics() -> Response:
        # async: rendered on the event loop, as interpose's metrics expect.
        return Response(metrics.render(), media_type=CONTENT_TYPE)

    return app
