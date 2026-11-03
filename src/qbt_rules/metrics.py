"""Prometheus metrics on interpose's Registry (template-python decision 0007).

``api.create_app`` builds the app's ``interpose.metrics.Registry`` (``app.state.metrics``) with
``qbt_rules_build_info``, and a ``Metrics`` on the same registry with qbt-rules' own metrics:

- state gauges, set from the queue, the worker and the schedule on every scrape (``scrape``):
  ``qbt_rules_queue_depth``, ``qbt_rules_jobs_total``, ``qbt_rules_worker_running``,
  ``qbt_rules_worker_last_job_completed_timestamp_seconds`` and ``qbt_rules_scheduler_entries``;
- event counters and histograms: ``qbt_rules_actions_executed_total`` (engine.py, in the worker
  thread), ``qbt_rules_job_duration_seconds`` (worker.py), ``qbt_rules_scheduler_fires_total``
  (scheduler.py, in the scheduler thread), and ``qbt_rules_http_requests_total`` with
  ``qbt_rules_http_request_duration_seconds`` (api.HttpMetrics, on the event loop).

The names and label sets are prometheus_client's from 0.10.x, so dashboards and alerts keep working.
Labels are in prometheus_client's multiprocess order (sorted by name), so even the sample lines
read the same. interpose takes label values from sets declared up front: the action types
(schema.ACTION_TYPES), the HTTP methods and status codes, and the app's route names (declared by
create_app). An event with a value outside its set (an unknown action type, an unusual HTTP
method) isn't counted; an undeclared route name counts as ``unknown``.

**Threads.** interpose's metrics aren't locked, and three threads change these: the worker, the
scheduler and the event loop, while a scrape renders in the threadpool. Every change and every
render here holds ``LOCK``, so a scrape never iterates a dict another thread is growing; each
holds it for microseconds, never across I/O.

**Recording.** engine.py, worker.py and scheduler.py call the module-level ``record_*`` functions,
which go to the ``Metrics`` the last ``create_app`` activated (``activate``): one app per process in
production. They are no-ops while metrics are off.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from datetime import datetime

from interpose.metrics import CONTENT_TYPE, Counter, Gauge, Histogram, Label, Registry

__all__ = [
    "CONTENT_TYPE",
    "LOCK",
    "Metrics",
    "activate",
    "active",
    "build_registry",
    "record_action_executed",
    "record_job_duration",
    "record_scheduler_fire",
]

LOCK = threading.Lock()

# prometheus_client's default buckets, which both histograms used in 0.10.x
DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)
RESULTS = ("success", "failure")
JOB_STATUSES = ("pending", "processing", "completed", "failed", "cancelled")
HTTP_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT")
HTTP_STATUSES = tuple(str(code) for code in range(100, 600))
# Route names that aren't a route function's own (api.endpoint_name)
EXTRA_ENDPOINTS = ("static", "unknown", "login")

_active: Metrics | None = None


def build_registry(version: str) -> Registry:
    """The app's registry, with the template's ``qbt_rules_build_info{version} 1``."""
    registry = Registry()
    registry.register(
        Gauge(
            "qbt_rules_build_info", "The running version: always 1", [Label("version", [version])]
        )
    ).set(1, version)
    return registry


class Metrics:
    """qbt-rules' metrics, registered on ``registry`` (decision 0007's hook)."""

    def __init__(self, registry: Registry) -> None:
        # Here, not at the top: schema.py imports engine.py, which imports this module
        from qbt_rules.schema import ACTION_TYPES

        self.registry = registry
        self._action_type = Label("action_type", ACTION_TYPES)
        self._backend = Label("backend")
        self._endpoint = Label("endpoint", EXTRA_ENDPOINTS)
        method = Label("method", HTTP_METHODS)
        result = Label("result", RESULTS)

        # State gauges: set by scrape()
        self.queue_depth = registry.register(
            Gauge("qbt_rules_queue_depth", "Current pending queue depth", [self._backend])
        )
        self.jobs = registry.register(
            Gauge("qbt_rules_jobs_total", "Total jobs by status", [Label("status", JOB_STATUSES)])
        )
        self.worker_running = registry.register(
            Gauge("qbt_rules_worker_running", "Worker thread running (1) or not (0)")
        )
        self.last_job_completed = registry.register(
            Gauge(
                "qbt_rules_worker_last_job_completed_timestamp_seconds",
                "Unix timestamp of the last job the worker completed",
            )
        )
        self.scheduler_entries = registry.register(
            Gauge("qbt_rules_scheduler_entries", "Number of configured schedule entries")
        )

        # Events
        self.actions_executed = registry.register(
            Counter(
                "qbt_rules_actions_executed_total",
                "Total actions executed by the rules engine (excludes dry-run and idempotent "
                "skips)",
                [self._action_type, result],
            )
        )
        self.job_duration = registry.register(
            Histogram(
                "qbt_rules_job_duration_seconds",
                "Job execution duration in seconds",
                DEFAULT_BUCKETS,
            )
        )
        self.scheduler_fires = registry.register(
            Counter(
                "qbt_rules_scheduler_fires_total", "Total internal cron scheduler fires", [result]
            )
        )
        self.http_requests = registry.register(
            Counter(
                "qbt_rules_http_requests_total",
                "Total HTTP requests",
                [self._endpoint, method, Label("status", HTTP_STATUSES)],
            )
        )
        self.http_duration = registry.register(
            Histogram(
                "qbt_rules_http_request_duration_seconds",
                "HTTP request duration in seconds",
                DEFAULT_BUCKETS,
                [self._endpoint, method],
            )
        )

    # -- declared before the app serves (create_app), so never while a scrape runs ---------------

    def declare_endpoints(self, names: Iterable[str]) -> None:
        self._endpoint.declare(*names)

    def declare_backend(self, name: str) -> None:
        self._backend.declare(name)

    # -- events --------------------------------------------------------------------------------

    def action_executed(self, action_type: str, success: bool) -> None:
        if action_type in self._action_type:
            with LOCK:
                self.actions_executed.inc(action_type, _result(success))

    def job_finished(self, seconds: float) -> None:
        with LOCK:
            self.job_duration.observe(seconds)

    def scheduler_fired(self, success: bool) -> None:
        with LOCK:
            self.scheduler_fires.inc(_result(success))

    def http_request(self, method: str, endpoint: str, status: int, seconds: float) -> None:
        if method not in HTTP_METHODS:
            return
        if endpoint not in self._endpoint:
            endpoint = "unknown"
        code = str(status) if 100 <= status < 600 else "500"
        with LOCK:
            self.http_requests.inc(endpoint, method, code)
            self.http_duration.observe(seconds, endpoint, method)

    # -- the scrape ----------------------------------------------------------------------------

    def scrape(
        self,
        queue_backend: str,
        queue_depth: int,
        job_counts: Mapping[str, int],
        worker_running: bool,
        worker_last_job_completed: str | None,
        schedule_entry_count: int,
    ) -> str:
        """Set the state gauges from values read just before (outside the lock), then render
        the whole registry in Prometheus text exposition format."""
        last_completed = _iso_to_unix_timestamp(worker_last_job_completed)
        with LOCK:
            if queue_backend in self._backend:
                self.queue_depth.set(queue_depth, queue_backend)
            for status in JOB_STATUSES:
                self.jobs.set(job_counts.get(status, 0), status)
            self.worker_running.set(1 if worker_running else 0)
            if last_completed is None:
                self.last_job_completed.values.pop((), None)
            else:
                self.last_job_completed.set(last_completed)
            self.scheduler_entries.set(schedule_entry_count)
            return self.registry.render()


def _result(success: bool) -> str:
    return "success" if success else "failure"


def _iso_to_unix_timestamp(iso_string: str | None) -> float | None:
    """Parse an ISO 8601 timestamp (Worker.get_status()'s) to Unix seconds."""
    if not iso_string:
        return None
    try:
        return datetime.fromisoformat(iso_string).timestamp()
    except ValueError:
        return None


# -- the module-level recorders engine.py, worker.py and scheduler.py call ----------------------


def activate(metrics: Metrics | None) -> None:
    """Send the ``record_*`` calls to ``metrics`` (None: metrics are off, they're no-ops)."""
    global _active
    _active = metrics


def active() -> Metrics | None:
    return _active


def record_action_executed(action_type: str, success: bool) -> None:
    """One action the engine ran (not a dry run or an idempotent skip)."""
    if _active is not None:
        _active.action_executed(action_type, success)


def record_job_duration(seconds: float) -> None:
    """One finished job's run time, completed or failed."""
    if _active is not None:
        _active.job_finished(seconds)


def record_scheduler_fire(success: bool) -> None:
    """One scheduler fire: the job was queued, or queueing it failed."""
    if _active is not None:
        _active.scheduler_fired(success)
