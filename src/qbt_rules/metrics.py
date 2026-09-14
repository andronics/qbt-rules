"""
Prometheus metrics support (optional -- requires `pip install qbt-rules[metrics]`)

Importing this module is always safe, even when prometheus_client isn't
installed and even before PROMETHEUS_MULTIPROC_DIR is set -- prometheus_client
itself is only ever imported lazily, inside init() and generate_metrics_output(),
never at this module's top level. Every other module (engine.py, worker.py,
scheduler.py, server.py) can therefore do `from qbt_rules import metrics` at
its own top level unconditionally and call the record_*() functions, which
silently no-op until init(enabled=True) has actually run.

Fork-safety: prometheus_client's default in-process registry breaks under
Gunicorn's preload_app + fork model, the same way a naively-written thread
would -- each forked worker gets its own independent, unsynchronized copy of
every counter. The fix is prometheus_client's own "multiprocess mode": set
the PROMETHEUS_MULTIPROC_DIR environment variable (this exact name is
mandated by the library) to a shared writable directory *before*
prometheus_client is first imported anywhere in the process; every process
(master and every forked child) then writes its own per-PID metric file into
that directory, and /metrics is served by aggregating across every file via
multiprocess.MultiProcessCollector. Because init() defers the actual import
until it's explicitly called (from cli.py's run_server_mode(), immediately
after setting the env var), this ordering constraint is satisfied without
requiring every module that records a metric to know or care about it.
"""

from datetime import datetime
from typing import Any, Dict, Optional

_enabled = False
_actions_executed: Optional[Any] = None
_job_duration: Optional[Any] = None
_scheduler_fires: Optional[Any] = None
_http_requests: Optional[Any] = None
_http_duration: Optional[Any] = None


def is_available() -> bool:
    """Check whether the prometheus_client package is installed, without importing it at module scope."""
    try:
        import prometheus_client  # noqa: F401
        return True
    except ImportError:
        return False


def is_enabled() -> bool:
    """Whether init(enabled=True) has run successfully -- record_*() calls are no-ops until then."""
    return _enabled


def init(enabled: bool) -> None:
    """
    Initialize the metrics module

    Must be called after PROMETHEUS_MULTIPROC_DIR is set in os.environ (when
    using multiprocess mode, which qbt-rules always does when metrics are
    enabled) and before any job/action/scheduler-fire/HTTP-request event
    that should be recorded. This is the only place prometheus_client is
    actually imported.

    Args:
        enabled: Value of metrics.enabled from config. If False, this is a
            no-op (record_*() calls remain silent no-ops) -- prometheus_client
            is never imported at all in that case, so it's fine for it to
            not even be installed.

    Raises:
        ValueError: If enabled is True but prometheus_client isn't installed
            -- fails fast at server startup with an actionable message,
            mirroring queue_manager.py's create_queue() ValueError for a
            missing 'redis' package.
    """
    global _enabled, _actions_executed, _job_duration, _scheduler_fires, _http_requests, _http_duration

    if not enabled:
        _enabled = False
        return

    if not is_available():
        raise ValueError(
            "metrics.enabled is true but the 'prometheus_client' package isn't installed. "
            "Install with: pip install qbt-rules[metrics]"
        )

    from prometheus_client import Counter, Histogram

    # registry=None deliberately skips auto-registration with
    # prometheus_client's default global REGISTRY -- it's never used for
    # multiprocess mode anyway (generate_metrics_output() always builds a
    # fresh CollectorRegistry() + MultiProcessCollector, which aggregates
    # from the per-process files these objects write to, independent of
    # any registry they're nominally attached to). This also makes init()
    # safely callable more than once in the same process, which the
    # default registry's duplicate-timeseries check would otherwise forbid.
    _actions_executed = Counter(
        'qbt_rules_actions_executed_total',
        'Total actions executed by the rules engine (excludes dry-run and idempotent skips)',
        ['action_type', 'result'],
        registry=None,
    )
    _job_duration = Histogram(
        'qbt_rules_job_duration_seconds',
        'Job execution duration in seconds',
        registry=None,
    )
    _scheduler_fires = Counter(
        'qbt_rules_scheduler_fires_total',
        'Total internal cron scheduler fires',
        ['result'],
        registry=None,
    )
    _http_requests = Counter(
        'qbt_rules_http_requests_total',
        'Total HTTP requests',
        ['method', 'endpoint', 'status'],
        registry=None,
    )
    _http_duration = Histogram(
        'qbt_rules_http_request_duration_seconds',
        'HTTP request duration in seconds',
        ['method', 'endpoint'],
        registry=None,
    )

    _enabled = True


def record_action_executed(action_type: str, success: bool) -> None:
    """Record one action execution. No-op unless init(enabled=True) has run."""
    if not _enabled:
        return
    _actions_executed.labels(action_type=action_type, result='success' if success else 'failure').inc()


def record_job_duration(seconds: float) -> None:
    """Record one completed job's execution time. No-op unless init(enabled=True) has run."""
    if not _enabled:
        return
    _job_duration.observe(seconds)


def record_scheduler_fire(success: bool) -> None:
    """Record one scheduler fire attempt. No-op unless init(enabled=True) has run."""
    if not _enabled:
        return
    _scheduler_fires.labels(result='success' if success else 'failure').inc()


def record_http_request(method: str, endpoint: str, status: int, duration: float) -> None:
    """Record one completed HTTP request. No-op unless init(enabled=True) has run."""
    if not _enabled:
        return
    _http_requests.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    _http_duration.labels(method=method, endpoint=endpoint).observe(duration)


def _iso_to_unix_timestamp(iso_string: Optional[str]) -> Optional[float]:
    """Parse an ISO-8601 timestamp string (as produced by Worker.get_status()) to Unix seconds."""
    if not iso_string:
        return None
    try:
        return datetime.fromisoformat(iso_string).timestamp()
    except ValueError:
        return None


def _build_state_collector(
    queue_backend: str,
    queue_depth: int,
    job_counts: Dict[str, int],
    worker_running: bool,
    worker_last_job_completed: Optional[str],
    schedule_entry_count: int,
):
    """
    Build a one-shot Collector exposing current-state gauges, computed from
    data already passed in (sourced from queue.get_stats()/get_queue_depth()
    and worker.get_status() at the call site) rather than pushed
    incrementally -- there's no shared chokepoint between the SQLite and
    Redis queue backends to instrument at write time, but both already
    durably track everything these gauges need, so it's cheaper and simpler
    to just read it fresh on every scrape.
    """
    from prometheus_client.core import GaugeMetricFamily
    from prometheus_client.registry import Collector

    class _StateCollector(Collector):
        def collect(self):
            depth = GaugeMetricFamily(
                'qbt_rules_queue_depth', 'Current pending queue depth', labels=['backend']
            )
            depth.add_metric([queue_backend], queue_depth)
            yield depth

            jobs = GaugeMetricFamily(
                'qbt_rules_jobs_total', 'Total jobs by status', labels=['status']
            )
            for status in ('pending', 'processing', 'completed', 'failed', 'cancelled'):
                jobs.add_metric([status], job_counts.get(status, 0))
            yield jobs

            running = GaugeMetricFamily(
                'qbt_rules_worker_running', 'Worker thread running (1) or not (0)'
            )
            running.add_metric([], 1 if worker_running else 0)
            yield running

            last_completed = _iso_to_unix_timestamp(worker_last_job_completed)
            if last_completed is not None:
                last_completed_family = GaugeMetricFamily(
                    'qbt_rules_worker_last_job_completed_timestamp_seconds',
                    'Unix timestamp of the last job the worker completed',
                )
                last_completed_family.add_metric([], last_completed)
                yield last_completed_family

            entries = GaugeMetricFamily(
                'qbt_rules_scheduler_entries', 'Number of configured schedule entries'
            )
            entries.add_metric([], schedule_entry_count)
            yield entries

    return _StateCollector()


def generate_metrics_output(
    queue_backend: str,
    queue_depth: int,
    job_counts: Dict[str, int],
    worker_running: bool,
    worker_last_job_completed: Optional[str],
    schedule_entry_count: int,
) -> bytes:
    """
    Render the full /metrics response: multiprocess-aggregated event
    counters/histograms plus the on-demand state gauges, in Prometheus
    text exposition format.

    Only called from server.py's /metrics route handler, and only reached
    when metrics are enabled (init(enabled=True) already succeeded), so
    prometheus_client is guaranteed importable here.
    """
    from prometheus_client import CollectorRegistry, generate_latest, multiprocess

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    registry.register(_build_state_collector(
        queue_backend, queue_depth, job_counts, worker_running,
        worker_last_job_completed, schedule_entry_count,
    ))
    return generate_latest(registry)


def content_type() -> str:
    """Prometheus exposition format Content-Type header value."""
    from prometheus_client import CONTENT_TYPE_LATEST
    return CONTENT_TYPE_LATEST
