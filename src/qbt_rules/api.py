"""The HTTP API.

The wiki's HTTP-API-Reference endpoint table is generated from this app's OpenAPI
schema (scripts/gen-wiki.py): give every route a `summary`, and a docstring when
it needs more than a line.

The JSON is the Flask API's, byte for byte (sorted keys, compact, a final newline:
CompatJSONResponse), with timestamps in ISO 8601 for both queue backends, and every
error as ``{"error", "message"}`` (docs/design/0002-fastapi.md).

One process (template-python decision 0008): the worker and the scheduler are threads
the lifespan starts and stops (BackgroundThreads, decision 0006).

The dashboard pages, the login form, /static and /metrics are web.py's routes on the same
app (web.register). TODO(4e): /metrics is still prometheus_client; interpose's Registry
replaces it.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, APIKeyQuery
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qbt_rules import __description__, __version__, metrics, sessions
from qbt_rules import api_models as m
from qbt_rules.config import Config
from qbt_rules.config_loader import Config as RulesConfig
from qbt_rules.queue_manager import JobStatus, QueueManager
from qbt_rules.utils import parse_bool

logger = logging.getLogger(__name__)

# Largest request body accepted: far beyond any real rules.yml, small enough that a
# validate or save request can't be used to exhaust memory
MAX_REQUEST_BYTES = 2 * 1024 * 1024
# The most jobs one GET /api/jobs returns (both queue backends cap it too)
MAX_JOBS_LIMIT = 100
# Accepted spellings for boolean query parameters (parse_bool's true set plus opposites)
BOOL_VALUES = frozenset({"true", "false", "1", "0", "yes", "no", "on", "off"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# More jobs than this in "processing" at once makes /api/health unhealthy
STUCK_PROCESSING_JOBS = 5

NO_API_KEY_MESSAGE = (
    "No API key is configured on the server: set QBT_RULES_SERVER_API_KEY_FILE (or "
    "server.api_key) and restart"
)
NO_CONFIG_MESSAGE = "The server was started without a config directory"

# The status names the Flask API used (Werkzeug's, not Python 3.13's newer RFC 9110 ones)
STATUS_NAMES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    412: "Precondition Failed",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    428: "Precondition Required",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class CompatJSONResponse(JSONResponse):
    """JSON exactly as the Flask API wrote it, so no client sees the port.

    Sorted keys, compact separators, non-ASCII escaped and a trailing newline: Flask's
    `jsonify`, byte for byte. A datetime (the SQLite backend's job timestamps) is written
    in ISO 8601, as the Redis backend's strings already are.
    """

    def render(self, content: Any) -> bytes:
        text = json.dumps(
            content, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=_iso
        )
        return f"{text}\n".encode()


def _iso(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


class ApiError(Exception):
    """An error response: ``{"error": <status name>, "message": ..., **extra}``."""

    def __init__(
        self,
        status: int,
        message: str,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}
        self.headers = headers


def error_response(
    status: int,
    message: str,
    extra: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> CompatJSONResponse:
    error = STATUS_NAMES.get(status, "Error")
    return CompatJSONResponse(
        {"error": error, "message": message, **(extra or {})}, status, headers=headers
    )


# -- Background threads --------------------------------------------------------------------------


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
            if thread.is_alive():
                logger.warning(f"Background thread {thread.name} did not stop in time")
            else:
                logger.info(f"Background thread {thread.name} stopped")

    def dead(self) -> list[str]:
        """The registered threads not running: never started, returned or raised."""
        alive = {t.name for t in self._threads if t.is_alive()}
        return [name for name in self._targets if name not in alive]


# -- What the routes serve -------------------------------------------------------------------------


class WorkerLike(Protocol):
    """The worker as the API sees it (worker.Worker; a stub in tests)."""

    def run(self, stop: threading.Event) -> None: ...

    def is_alive(self) -> bool: ...

    def get_status(self) -> dict[str, Any]: ...


class SchedulerLike(Protocol):
    @property
    def has_entries(self) -> bool: ...

    def run(self, stop: threading.Event) -> None: ...


@dataclass
class Services:
    """The queue, the worker and the running config the API serves.

    ``rules`` is None for a server started without a config directory: the rules
    editor's routes then answer 503. ``close`` runs when the app shuts down.
    """

    queue: QueueManager
    worker: WorkerLike
    rules: RulesConfig | None
    scheduler: SchedulerLike | None = None
    close: Callable[[], None] | None = field(default=None, repr=False)


def build_services(config: Config) -> Services:
    """The production services: the configured queue, a qBittorrent client, the worker
    and the scheduler. Nothing connects to qBittorrent until the first job."""
    from qbt_rules.qbittorrent import QBittorrentAPI
    from qbt_rules.queue_manager import create_queue
    from qbt_rules.scheduler import Scheduler
    from qbt_rules.worker import Worker

    rules = RulesConfig(config)
    queue = create_queue(
        backend=config.queue_backend,
        db_path=str(config.sqlite_path),
        redis_url=config.redis_url.reveal(),
    )
    logger.info(f"Queue backend: {queue.__class__.__name__}")
    api = QBittorrentAPI(
        host=config.qbt_host,
        username=config.qbt_username,
        password=config.qbt_password.reveal(),
        connect_now=False,
    )
    logger.info(f"qBittorrent: {config.qbt_host} (will connect on first job)")
    worker = Worker(
        queue=queue,
        api=api,
        config=rules,
        notifications_config={
            "webhook_url": config.webhook_url.reveal() or None,  # type: ignore[dict-item]
            "service": config.notify_service,
        },
        integrations_config=_integrations(config),
        cleanup_after=config.cleanup_after,
    )
    scheduler = Scheduler(queue=queue, entries=rules.schedule)
    close: Callable[[], None] | None = getattr(queue, "close", None)
    return Services(queue=queue, worker=worker, rules=rules, scheduler=scheduler, close=close)


def _integrations(config: Config) -> dict[str, Any]:
    return {
        "sonarr": {
            "url": config.sonarr_url or None,
            "api_key": config.sonarr_api_key.reveal() or None,
        },
        "radarr": {
            "url": config.radarr_url or None,
            "api_key": config.radarr_api_key.reveal() or None,
        },
        "trackie": {
            "url": config.trackie_url or None,
            "max_age": config.trackie_max_age,
            "timeout": config.trackie_timeout,
        },
    }


# -- Auth ----------------------------------------------------------------------------------------

_query_key = APIKeyQuery(
    name="key", auto_error=False, description="The API key (or send X-API-Key instead)"
)
_header_key = APIKeyHeader(name="X-API-Key", auto_error=False, description="The API key")


def _api_key(request: Request) -> str:
    key: str = request.app.state.api_key
    return key


def _key_matches(request: Request, key: str | None) -> bool:
    import secrets

    configured = _api_key(request)
    return bool(key and configured and secrets.compare_digest(key, configured))


def require_api_key(
    request: Request,
    query_key: str | None = Security(_query_key),
    header_key: str | None = Security(_header_key),
) -> None:
    """The API key, as ``?key=`` or ``X-API-Key``: 401 without it, 503 with none configured."""
    if not _api_key(request):
        raise ApiError(503, NO_API_KEY_MESSAGE)
    if not _key_matches(request, query_key or header_key):
        raise ApiError(401, "Invalid or missing API key")


def require_api_key_or_session(
    request: Request,
    query_key: str | None = Security(_query_key),
    header_key: str | None = Security(_header_key),
) -> None:
    """The API key, or the dashboard's login session (sessions.py).

    A session is a cookie the browser attaches by itself, so a POST, PUT or DELETE riding
    on one must also carry the page's X-CSRF-Token header, which another site can neither
    read nor set: 403 without it. A wrong key is a 401 even with a session.
    """
    if not _api_key(request):
        raise ApiError(503, NO_API_KEY_MESSAGE)
    key = query_key or header_key
    if key:
        if _key_matches(request, key):
            return
    elif sessions.is_logged_in(request.session):
        if request.method in SAFE_METHODS:
            return
        if sessions.csrf_ok(request.session, request.headers.get("X-CSRF-Token")):
            return
        raise ApiError(
            403, "Missing or invalid X-CSRF-Token header -- reload the page and try again"
        )
    raise ApiError(401, "Invalid or missing API key")


KeyOnly = [Depends(require_api_key)]
KeyOrSession = [Depends(require_api_key_or_session)]


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {s: {"model": m.ErrorBody, "description": STATUS_NAMES[s]} for s in statuses}


AUTH_ERRORS = error_responses(401, 503)


def services(request: Request) -> Services:
    found: Services | None = request.app.state.services
    if found is None:
        raise ApiError(503, "qbt-rules is starting")
    return found


# -- Middleware ----------------------------------------------------------------------------------


class BodyLimit:
    """413 for a declared body over MAX_REQUEST_BYTES, before anything reads it.

    A body sent without Content-Length (chunked) is counted as it is read instead
    (read_json_body).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope["headers"]:
                if name == b"content-length":
                    try:
                        too_large = int(value) > MAX_REQUEST_BYTES
                    except ValueError:
                        too_large = False
                    if too_large:
                        await error_response(413, TOO_LARGE_MESSAGE)(scope, receive, send)
                        return
        await self.app(scope, receive, send)


TOO_LARGE_MESSAGE = f"Request body exceeds {MAX_REQUEST_BYTES // (1024 * 1024)} MB"


class CatchAll:
    """A 500 ``{"error", "message"}`` for any unhandled exception, with no detail.

    The exception and its traceback are logged; the body never carries its text.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # scope["path"] has no query string, so never the ?key=
            logger.exception(f"Unhandled error: {scope['method']} {scope['path']}")
            if started:
                raise
            await error_response(500, "An unexpected error occurred")(scope, receive, send)


# Metric labels kept from the Flask app, where GET and POST /login were one view
_ENDPOINT_ALIASES = {"login_submit": "login"}


def endpoint_name(scope: Scope) -> str | None:
    """A request's HTTP metrics label: its route function's name, ``static`` for a static
    file, ``unknown`` for no route, and None for /metrics (a scrape doesn't count itself)."""
    from starlette.staticfiles import StaticFiles

    endpoint = scope.get("endpoint")
    if isinstance(endpoint, StaticFiles):
        return "static"
    name = getattr(endpoint, "__name__", None) or "unknown"
    if name == "metrics_endpoint":
        return None
    return _ENDPOINT_ALIASES.get(name, name)


class HttpMetrics:
    """qbt_rules_http_requests_total and its duration histogram, for every route but /metrics.

    TODO(4e): interpose.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not metrics.is_enabled():
            await self.app(scope, receive, send)
            return
        status = 500
        start = time.time()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            name = endpoint_name(scope)
            if name is not None:
                metrics.record_http_request(scope["method"], name, status, time.time() - start)


# -- The app -------------------------------------------------------------------------------------


def create_app(config: Config, services: Services | None = None) -> FastAPI:
    """The app. Without `services`, the lifespan builds them from `config` (build_services),
    starts the worker and scheduler threads, and stops them on shutdown."""
    threads = BackgroundThreads()
    api_key = config.api_key.reveal()

    def attach(app: FastAPI, found: Services) -> None:
        app.state.services = found
        threads.add("worker", found.worker.run)
        if found.scheduler is not None and found.scheduler.has_entries:
            threads.add("scheduler", found.scheduler.run)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = app.state.services is None
        if owned:
            attach(app, build_services(config))
        threads.start()
        try:
            yield
        finally:
            threads.shutdown()
            if owned and app.state.services.close is not None:
                app.state.services.close()

    app = FastAPI(
        title="qbt-rules",
        version=__version__,
        description=__description__,
        lifespan=lifespan,
        default_response_class=CompatJSONResponse,
    )
    metrics_on = config.metrics_enabled and metrics.is_enabled()
    app.state.config = config
    app.state.threads = threads
    app.state.api_key = api_key
    app.state.services = None
    if services is not None:
        attach(app, services)

    # Last added runs first: the body limit, then the session, then the catch-all
    app.add_middleware(CatchAll)
    app.add_middleware(HttpMetrics)
    app.add_middleware(
        SessionMiddleware,
        secret_key=sessions.session_secret(api_key),
        session_cookie=sessions.SESSION_COOKIE,
        max_age=sessions.SESSION_MAX_AGE,
        same_site="lax",
    )
    app.add_middleware(BodyLimit)
    _register_error_handlers(app)

    @app.get(
        "/healthz",
        summary="Liveness: the process is up",
        tags=["health"],
        response_model=m.Probe,
    )
    def healthz() -> CompatJSONResponse:
        """Dependency-free: the image's HEALTHCHECK and a liveness probe poll it."""
        return CompatJSONResponse({"status": "ok"})

    @app.get(
        "/readyz",
        summary="Readiness: able to serve requests",
        tags=["health"],
        response_model=m.Probe,
        responses={503: {"model": m.ErrorBody, "description": "A background thread is down"}},
    )
    def readyz() -> CompatJSONResponse:
        """503 while starting, or when the worker or scheduler thread has died."""
        if app.state.services is None:
            raise ApiError(503, "qbt-rules is starting")
        if dead := threads.dead():
            raise ApiError(503, f"background thread not running: {', '.join(dead)}")
        return CompatJSONResponse({"status": "ready"})

    app.include_router(_jobs_router())
    from qbt_rules.api_rules import router as rules_router

    app.include_router(rules_router)

    from qbt_rules import web

    web.register(app, metrics_on)

    return app


def _register_error_handlers(app: FastAPI) -> None:
    async def api_error(request: Request, exc: Exception) -> CompatJSONResponse:
        assert isinstance(exc, ApiError)  # noqa: S101  registered for ApiError only
        return error_response(exc.status, exc.message, exc.extra, exc.headers)

    async def http_error(request: Request, exc: Exception) -> CompatJSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101  registered for it only
        if exc.status_code == 404:
            message = "Endpoint not found"
        elif exc.status_code == 405:
            message = f"{request.method} is not allowed for this endpoint"
        else:
            message = str(exc.detail)
        return error_response(exc.status_code, message, headers=exc.headers)

    async def validation_error(request: Request, exc: Exception) -> CompatJSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101  registered for it only
        parts = []
        for error in exc.errors():
            where = ".".join(str(p) for p in error.get("loc", ())[1:]) or "request"
            parts.append(f"{where}: {error.get('msg', 'invalid')}")
        return error_response(400, "; ".join(parts) or "Invalid request")

    handlers: dict[type[Exception], Callable[[Request, Exception], Awaitable[JSONResponse]]] = {
        ApiError: api_error,
        StarletteHTTPException: http_error,
        RequestValidationError: validation_error,
    }
    for exc_class, handler in handlers.items():
        app.add_exception_handler(exc_class, handler)


# -- Jobs, health, stats, version ----------------------------------------------------------------


def _worker_status(found: Services) -> dict[str, Any]:
    status = found.worker.get_status()
    return {
        "status": "running" if status["running"] else "stopped",
        "last_job_completed": status["last_job_completed"],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _jobs_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/execute",
        summary="Queue a job",
        tags=["jobs"],
        status_code=202,
        response_model=m.Job,
        dependencies=KeyOrSession,
        responses={**error_responses(400, 403), **AUTH_ERRORS},
    )
    def execute(
        request: Request,
        context: str | None = Query(None, description="Run the rules with this context"),
        hash: str | None = Query(None, description="Only this torrent (its info hash)"),
        dry_run: str | None = Query(
            None,
            description="true to log what the rules would do and change nothing. It only "
            "adds dry-run: a server configured for dry-run stays in it",
        ),
    ) -> CompatJSONResponse:
        """Queues a job and answers at once; poll GET /api/jobs/{job_id} for its result."""
        if dry_run is not None and dry_run.lower() not in BOOL_VALUES:
            # Refuse rather than guess: a typo here must not run deletes for real
            raise ApiError(400, f"dry_run must be one of {', '.join(sorted(BOOL_VALUES))}")
        dry = parse_bool(dry_run)
        queue = services(request).queue
        job_id = queue.enqueue(context=context, hash_filter=hash, dry_run=dry)
        job = queue.get_job(job_id)
        logger.info(
            f"Job queued: {job_id} (context={context}, hash={hash}"
            f"{', dry_run=True' if dry else ''})"
        )
        return CompatJSONResponse(job, 202)

    @router.get(
        "/api/jobs",
        summary="List jobs, newest first",
        tags=["jobs"],
        response_model=m.JobList,
        dependencies=KeyOnly,
        responses={**error_responses(400), **AUTH_ERRORS},
    )
    def list_jobs(
        request: Request,
        status: str | None = Query(
            None, description="pending, processing, completed, failed or cancelled"
        ),
        context: str | None = Query(None, description="Only jobs with this context"),
        limit: int = Query(50, ge=0, description=f"At most {MAX_JOBS_LIMIT}"),
        offset: int = Query(0, ge=0),
    ) -> CompatJSONResponse:
        if status and not QueueManager.validate_status(status):
            raise ApiError(400, f"Invalid status: {status}")
        queue = services(request).queue
        limit = min(limit, MAX_JOBS_LIMIT)
        jobs = queue.list_jobs(status=status, context=context, limit=limit, offset=offset)
        total = queue.count_jobs(status=status, context=context)
        return CompatJSONResponse({"total": total, "limit": limit, "offset": offset, "jobs": jobs})

    @router.get(
        "/api/jobs/{job_id}",
        summary="One job",
        tags=["jobs"],
        response_model=m.Job,
        dependencies=KeyOrSession,
        responses={**error_responses(404), **AUTH_ERRORS},
    )
    def get_job(request: Request, job_id: str) -> CompatJSONResponse:
        job = services(request).queue.get_job(job_id)
        if not job:
            raise ApiError(404, f"Job not found: {job_id}")
        return CompatJSONResponse(job)

    @router.delete(
        "/api/jobs/{job_id}",
        summary="Cancel a pending job",
        tags=["jobs"],
        response_model=m.CancelledJob,
        dependencies=KeyOnly,
        responses={**error_responses(400, 404, 500), **AUTH_ERRORS},
    )
    def cancel_job(request: Request, job_id: str) -> CompatJSONResponse:
        """Only a pending job: 400 once it has started."""
        queue = services(request).queue
        job = queue.get_job(job_id)
        if not job:
            raise ApiError(404, f"Job not found: {job_id}")
        if job["status"] != JobStatus.PENDING:
            raise ApiError(400, f"Cannot cancel job in status: {job['status']}")
        if not queue.cancel_job(job_id):
            raise ApiError(500, "Failed to cancel job")
        logger.info(f"Job cancelled: {job_id}")
        return CompatJSONResponse(
            {
                "job_id": job_id,
                "status": JobStatus.CANCELLED,
                "message": "Job cancelled successfully",
            }
        )

    @router.get(
        "/api/health",
        summary="Queue and worker health",
        tags=["health"],
        response_model=m.Health,
        responses={503: {"model": m.Unhealthy, "description": "The queue or worker is down"}},
    )
    def health(request: Request) -> CompatJSONResponse:
        """No authentication. 503 when the queue backend is unreachable, the worker thread has
        died, or more than 5 jobs are processing at once. A setting the server started without
        (no API key) is listed in `config_problems` but doesn't fail it. The container
        HEALTHCHECK polls /healthz instead, which depends on nothing."""
        found = services(request)
        queue = found.queue
        errors = []
        if not queue.health_check():
            errors.append("Queue backend not accessible")
        if not found.worker.is_alive():
            errors.append("Worker thread not running")
        processing = queue.count_jobs(JobStatus.PROCESSING)
        if processing > STUCK_PROCESSING_JOBS:
            errors.append(f"Too many processing jobs: {processing}")
        if errors:
            return CompatJSONResponse(
                {"status": "unhealthy", "errors": errors, "timestamp": _now()}, 503
            )

        problems = list(request.app.state.config.problems)
        extra: dict[str, Any] = {"config_problems": problems} if problems else {}
        return CompatJSONResponse(
            {
                **extra,
                "status": "healthy",
                "version": __version__,
                "queue": {
                    "backend": queue.__class__.__name__,
                    "pending_jobs": queue.get_queue_depth(),
                    "processing_jobs": queue.count_jobs(JobStatus.PROCESSING),
                },
                "worker": _worker_status(found),
                "timestamp": _now(),
            }
        )

    @router.get(
        "/api/stats",
        summary="Job counts and timings",
        tags=["jobs"],
        response_model=m.Stats,
        dependencies=KeyOnly,
        responses=AUTH_ERRORS,
    )
    def stats(request: Request) -> CompatJSONResponse:
        found = services(request)
        queue = found.queue
        s = queue.get_stats()
        average = s["average_execution_time"]
        return CompatJSONResponse(
            {
                "jobs": {
                    "total": s["total_jobs"],
                    "pending": s["pending"],
                    "processing": s["processing"],
                    "completed": s["completed"],
                    "failed": s["failed"],
                    "cancelled": s["cancelled"],
                },
                "performance": {"average_execution_time": f"{average}s" if average else None},
                "queue": {"backend": queue.__class__.__name__, "depth": queue.get_queue_depth()},
                "worker": _worker_status(found),
                "timestamp": _now(),
            }
        )

    @router.get(
        "/api/version",
        summary="The running version",
        tags=["meta"],
        response_model=m.Version,
    )
    def version() -> CompatJSONResponse:
        """No authentication."""
        return CompatJSONResponse(
            {
                "version": __version__,
                "api_version": "1.0",
                "python_version": sys.version.split()[0],
            }
        )

    return router
