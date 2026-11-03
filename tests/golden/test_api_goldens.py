"""
Golden responses for the JSON API -- the safety net for the Flask -> FastAPI port

Every JSON route in web.py (plus /metrics and the 404/405/413/500
handlers) is driven through the Flask test client against a real queue --
SQLite and fakeredis -- and its status, Content-Type, selected headers
(SELECTED_HEADERS) and exact body are compared with a stored golden file:

    tests/golden/responses/<backend>/<case>.json

Comparison is exact: the body is stored as the literal response text and
must match byte for byte. A missing golden file is a failure.

Regenerating
------------
After an intended change to an API response, rewrite the golden files and
review the diff like any other code change:

    QBT_RULES_UPDATE_GOLDENS=1 pytest tests/golden

With the switch set every case writes its file and passes; without it,
nothing is written.

Determinism
-----------
- Time is frozen: every ``datetime.now()`` in web.py, queue_manager.py,
  both queue backends and config_store.py reads a settable Clock (seeded
  jobs get distinct, whole-second timestamps; requests run at FROZEN_AT).
  rules.yml's mtime -- the editor's ``modified_at`` -- is pinned to the
  clock too, including after a save.
- Job IDs come from a counter (00000000-0000-4000-8000-00000000000N).
- ``__version__`` is patched to FIXED_VERSION, so a release bump doesn't
  rewrite every golden.
- The worker is a stub with a fixed status; the qBittorrent API is never
  reached by these routes.

Masked -- the only values not captured as-is (each listed in the golden's
"masked" field):
- ``python_version`` in /api/version: the interpreter running the tests.
- The temporary config directory in ``path`` fields (and anywhere else it
  appears) is replaced with ``<config_dir>``.
- /metrics: only the on-demand state gauges (STATE_METRICS) are kept. The
  multiprocess event counters/histograms aggregate every request made in
  the whole pytest session, so their values depend on test order.

- The ``Allow`` header's methods are sorted: Werkzeug builds it from a
  set, so its order changes from run to run.

Session cookies (Set-Cookie) are not captured: itsdangerous signs them
with the real wall clock.

Timestamps: SQLite vs Redis (READ THIS BEFORE THE PORT)
-------------------------------------------------------
The goldens hold today's real output, which differs between backends:
SQLite returns job timestamps as datetime objects, which Flask's jsonify
renders as RFC 822 dates ("Tue, 03 Nov 2026 12:00:00 GMT" -- second
precision, zone dropped), while Redis returns the stored ISO 8601 strings
("2026-11-03T12:00:00+00:00"). The FastAPI port will emit ISO 8601 for
both backends. Every field that is a timestamp is named in
TIMESTAMP_FIELDS, and each golden lists the concrete JSON paths under
"timestamp_paths". ``normalise_timestamps()`` rewrites RFC 822 values at
those fields to ISO 8601 -- it is the one place the port's comparison
should change (compare against ``normalise_timestamps(json.loads(body))``
for the SQLite goldens). Seeded times are whole seconds, so that
conversion is lossless. test_backends_agree_after_timestamp_normalisation
proves that, once normalised, the two backends' goldens are identical
apart from the backend class name.

JSON encoding (the port must match)
-----------------------------------
create_app() sets ``JSON_SORT_KEYS = False``, but Flask 3 ignores that
config key (it moved to ``app.json.sort_keys``), so every JSON body today
has its keys sorted, is compact (no spaces after ``,``/``:``) and ends
with a newline. The goldens capture exactly that; FastAPI's default
JSONResponse does neither sorting nor the trailing newline.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

from qbt_rules import config_store, metrics, queue_manager, web
from qbt_rules.queue_backends import sqlite_queue
from qbt_rules.queue_manager import JobStatus, QueueManager

GOLDEN_DIR = Path(__file__).parent / "responses"  # not data/: .gitignore excludes it
UPDATE_GOLDENS = os.environ.get("QBT_RULES_UPDATE_GOLDENS") == "1"

API_KEY = "golden-api-key"
KEY = {"X-API-Key": API_KEY}
FIXED_VERSION = "0.0.0+golden"
FROZEN_AT = datetime(2026, 11, 3, 12, 30, 0, tzinfo=timezone.utc)
BACKENDS = ["sqlite", "redis"]

# Every response field that holds a timestamp. SQLite job timestamps are
# RFC 822 today, everything else is ISO 8601 -- see the module docstring.
TIMESTAMP_FIELDS = frozenset(
    {
        "created_at",
        "started_at",
        "completed_at",
        "timestamp",
        "last_job_completed",
        "modified_at",
        "saved_at",
    }
)

SELECTED_HEADERS = ("ETag", "Cache-Control", "Allow", "Location")

STATE_METRICS = (
    "qbt_rules_queue_depth",
    "qbt_rules_jobs_total",
    "qbt_rules_worker_running",
    "qbt_rules_worker_last_job_completed_timestamp_seconds",
    "qbt_rules_scheduler_entries",
)

RULES = (
    "version: 1\n"
    "rules:\n"
    "  - id: pause-stalled  # keep this comment\n"
    "    conditions:\n"
    "      all:\n"
    "        - field: info.state\n"
    "          operator: ==\n"
    "          value: stalledDL\n"
    "    actions:\n"
    "      - type: stop\n"
)

CONFIG = (
    "server:\n"
    "  api_key: hunter2\n"
    "qbittorrent:\n"
    "  host: http://localhost:8080\n"
    "  username: admin\n"
    "  password: s3cret\n"
    "schedule:\n"
    "  - {cron: '0 * * * *', context: hourly}\n"
    "  - {cron: '0 3 * * 0', context: weekly-cleanup}\n"
)

INVALID_RULES = (
    "version: 1\n"
    "rules:\n"
    "  - id: remove-finished\n"
    "    conditions: []\n"
    "    actions:\n"
    "      - type: delete_torrent\n"
    '        params: {delete_files: "false"}\n'
)


# ---------------------------------------------------------------------------
# Timestamp normalisation -- the one place the port changes the comparison
# ---------------------------------------------------------------------------

_RFC822 = re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")


def normalise_timestamps(value: Any) -> Any:
    """Return a copy of a parsed JSON body with every RFC 822 date under a
    TIMESTAMP_FIELDS key rewritten as ISO 8601 (UTC, "+00:00")"""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in TIMESTAMP_FIELDS and isinstance(v, str) and _RFC822.match(v):
                out[k] = parsedate_to_datetime(v).astimezone(timezone.utc).isoformat()
            else:
                out[k] = normalise_timestamps(v)
        return out
    if isinstance(value, list):
        return [normalise_timestamps(v) for v in value]
    return value


def timestamp_paths(value: Any, prefix: str = "") -> List[str]:
    """JSON paths (e.g. "jobs[0].created_at") of every non-null timestamp"""
    paths: List[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else k
            if k in TIMESTAMP_FIELDS and isinstance(v, str):
                paths.append(path)
            else:
                paths.extend(timestamp_paths(v, path))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            paths.extend(timestamp_paths(v, f"{prefix}[{i}]"))
    return paths


# ---------------------------------------------------------------------------
# Deterministic environment
# ---------------------------------------------------------------------------


class Clock:
    def __init__(self, value: datetime):
        self.value = value

    def set(self, value: datetime):
        self.value = value


def _frozen_datetime(clock: Clock):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.value
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    return FrozenDatetime


class StubWorker:
    def __init__(self):
        self.running = True
        self.alive = True

    def is_alive(self):
        return self.alive

    def get_status(self):
        return {
            "running": self.running,
            "thread_alive": self.alive,
            "last_job_completed": "2026-11-03T12:01:02+00:00",
            "queue_depth": 0,
        }


def _make_queue(backend: str, tmp_path: Path) -> QueueManager:
    if backend == "sqlite":
        return sqlite_queue.SQLiteQueue(db_path=str(tmp_path / "queue.db"))
    fakeredis = pytest.importorskip("fakeredis")
    from qbt_rules.queue_backends.redis_queue import RedisQueue

    queue = RedisQueue.__new__(RedisQueue)
    queue.redis_url = "redis://golden/0"
    queue.redis = fakeredis.FakeRedis(decode_responses=True)
    queue.pool = None
    return queue


class Env:
    """One app + queue + config directory, all deterministic"""

    def __init__(self, backend: str, tmp_path: Path, monkeypatch):
        self.backend = backend
        self.clock = Clock(FROZEN_AT)
        self.monkeypatch = monkeypatch

        frozen = _frozen_datetime(self.clock)
        for module in (web, queue_manager, config_store, sqlite_queue):
            monkeypatch.setattr(module, "datetime", frozen)
        if backend == "redis":
            from qbt_rules.queue_backends import redis_queue

            monkeypatch.setattr(redis_queue, "datetime", frozen)

        ids = iter(range(1, 10_000))
        monkeypatch.setattr(
            QueueManager,
            "generate_job_id",
            staticmethod(lambda: f"00000000-0000-4000-8000-{next(ids):012d}"),
        )
        monkeypatch.setattr(web, "__version__", FIXED_VERSION)

        # config.yml redaction and Config() both read QBT_RULES_* overrides
        for name in list(os.environ):
            if name.startswith("QBT_RULES_") or name == "CONFIG_DIR":
                monkeypatch.delenv(name)

        # Pin rules.yml's mtime to the clock after every editor save, so
        # modified_at is as frozen as everything else
        real_replace = config_store.EditableFile._replace
        clock = self.clock

        def _replace(self_, data):
            real_replace(self_, data)
            ts = clock.value.timestamp()
            os.utime(self_.path, (ts, ts))

        monkeypatch.setattr(config_store.EditableFile, "_replace", _replace)

        self.config_dir = tmp_path / "config"
        self.config_dir.mkdir()
        (self.config_dir / "config.yml").write_text(CONFIG)
        self.write_rules(RULES)

        self.queue = _make_queue(backend, tmp_path)
        self.worker = StubWorker()

    def write_rules(self, text: str):
        path = self.config_dir / "rules.yml"
        path.write_text(text)
        ts = self.clock.value.timestamp()
        os.utime(path, (ts, ts))

    def client(self, with_config: bool = True, metrics_on: bool = False, **kwargs):
        from qbt_rules.config_loader import Config

        config = Config(self.config_dir) if with_config else None
        metrics_config = None
        if metrics_on:
            metrics.init(enabled=True)
            metrics_config = {
                "enabled": True,
                "multiproc_dir": os.environ["PROMETHEUS_MULTIPROC_DIR"],
            }
        app = web.create_app(
            self.queue,
            self.worker,
            API_KEY,
            config=config,
            metrics_config=metrics_config,
            **kwargs,
        )
        # TESTING stays off: with it on, Flask re-raises unhandled errors
        # instead of running the 500 handler a real deployment would
        return app.test_client()

    def seed_jobs(self):
        """Completed, failed and pending jobs a minute apart, moved through the
        queue the way the worker moves them (dequeue, then update_status)"""
        t0 = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        q = self.queue

        self.clock.set(t0)
        completed = q.enqueue(context="weekly-cleanup")
        q.dequeue()  # as the worker does: pending -> processing
        q.update_status(
            completed,
            JobStatus.COMPLETED,
            started_at=t0 + timedelta(seconds=1),
            completed_at=t0 + timedelta(seconds=4),
            result={"actions_executed": 2, "rules_matched": 1, "torrents_processed": 12},
        )

        self.clock.set(t0 + timedelta(minutes=1))
        failed = q.enqueue(context="torrent-imported", hash_filter="abc123def456")
        q.dequeue()
        q.update_status(
            failed,
            JobStatus.FAILED,
            started_at=t0 + timedelta(minutes=1, seconds=1),
            completed_at=t0 + timedelta(minutes=1, seconds=2),
            error=(
                "Traceback (most recent call last):\n"
                '  File "worker.py", line 170, in _process_job\n'
                "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent\n"
            ),
        )

        self.clock.set(t0 + timedelta(minutes=2))
        pending = q.enqueue(dry_run=True)

        self.clock.set(FROZEN_AT)
        return {"completed": completed, "failed": failed, "pending": pending}

    def login(self, client):
        client.post("/login", data={"key": API_KEY, "next": "/rules/edit"})

    def etag(self, client) -> str:
        return client.get("/api/rules/source", headers=KEY).get_json()["etag"]


# ---------------------------------------------------------------------------
# Cases -- each returns (request description, response)
# ---------------------------------------------------------------------------

CASES: Dict[str, Callable[[Env], Any]] = {}


def case(name: str):
    def register(fn):
        CASES[name] = fn
        return fn

    return register


def _call(client, method: str, url: str, **kwargs):
    return f"{method} {url}", client.open(url, method=method, **kwargs)


# -- /api/execute -----------------------------------------------------------


@case("execute_202")
def _(env):
    return _call(
        env.client(), "POST", "/api/execute?context=weekly-cleanup&hash=abc123", headers=KEY
    )


@case("execute_202_dry_run")
def _(env):
    return _call(env.client(), "POST", "/api/execute?dry_run=true", headers=KEY)


@case("execute_400_bad_dry_run")
def _(env):
    return _call(env.client(), "POST", "/api/execute?dry_run=maybe", headers=KEY)


@case("execute_401")
def _(env):
    return _call(env.client(), "POST", "/api/execute")


@case("execute_401_wrong_key")
def _(env):
    return _call(env.client(), "POST", "/api/execute", headers={"X-API-Key": "nope"})


@case("execute_403_session_without_csrf")
def _(env):
    client = env.client()
    env.login(client)
    return _call(client, "POST", "/api/execute")


@case("execute_500_queue_error")
def _(env):
    def boom(**kwargs):
        raise RuntimeError("queue backend unavailable")

    env.monkeypatch.setattr(env.queue, "enqueue", boom)
    return _call(env.client(), "POST", "/api/execute", headers=KEY)


# -- /api/jobs --------------------------------------------------------------


@case("jobs_list_200")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/jobs", headers=KEY)


@case("jobs_list_200_empty")
def _(env):
    return _call(env.client(), "GET", "/api/jobs", headers=KEY)


@case("jobs_list_200_status_filter")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/jobs?status=completed", headers=KEY)


@case("jobs_list_200_context_filter")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/jobs?context=torrent-imported", headers=KEY)


@case("jobs_list_200_paginated")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/jobs?limit=1&offset=1", headers=KEY)


@case("jobs_list_200_limit_over_max")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/jobs?limit=500", headers=KEY)


@case("jobs_list_400_bad_status")
def _(env):
    return _call(env.client(), "GET", "/api/jobs?status=bogus", headers=KEY)


@case("jobs_list_401")
def _(env):
    return _call(env.client(), "GET", "/api/jobs")


@case("jobs_list_500_non_integer_limit")
def _(env):
    # int('abc') is unhandled -> the generic 500 handler, not a 400
    return _call(env.client(), "GET", "/api/jobs?limit=abc", headers=KEY)


@case("job_get_200_completed")
def _(env):
    ids = env.seed_jobs()
    return _call(env.client(), "GET", f"/api/jobs/{ids['completed']}", headers=KEY)


@case("job_get_200_failed")
def _(env):
    ids = env.seed_jobs()
    return _call(env.client(), "GET", f"/api/jobs/{ids['failed']}", headers=KEY)


@case("job_get_200_pending")
def _(env):
    ids = env.seed_jobs()
    return _call(env.client(), "GET", f"/api/jobs/{ids['pending']}", headers=KEY)


@case("job_get_404")
def _(env):
    return _call(env.client(), "GET", "/api/jobs/no-such-job", headers=KEY)


@case("job_get_401")
def _(env):
    return _call(env.client(), "GET", "/api/jobs/no-such-job")


@case("job_cancel_200")
def _(env):
    ids = env.seed_jobs()
    return _call(env.client(), "DELETE", f"/api/jobs/{ids['pending']}", headers=KEY)


@case("job_cancel_400_not_pending")
def _(env):
    ids = env.seed_jobs()
    return _call(env.client(), "DELETE", f"/api/jobs/{ids['completed']}", headers=KEY)


@case("job_cancel_404")
def _(env):
    return _call(env.client(), "DELETE", "/api/jobs/no-such-job", headers=KEY)


@case("job_cancel_401")
def _(env):
    return _call(env.client(), "DELETE", "/api/jobs/no-such-job")


# -- health / stats / version ---------------------------------------------------


@case("health_200")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/health")


@case("health_503_worker_dead")
def _(env):
    env.worker.alive = False
    return _call(env.client(), "GET", "/api/health")


@case("stats_200")
def _(env):
    env.seed_jobs()
    return _call(env.client(), "GET", "/api/stats", headers=KEY)


@case("stats_200_empty")
def _(env):
    return _call(env.client(), "GET", "/api/stats", headers=KEY)


@case("stats_401")
def _(env):
    return _call(env.client(), "GET", "/api/stats")


@case("version_200")
def _(env):
    return _call(env.client(), "GET", "/api/version")


# -- rules editor -------------------------------------------------------------


@case("rules_source_200")
def _(env):
    return _call(env.client(), "GET", "/api/rules/source", headers=KEY)


@case("rules_source_200_editor_disabled")
def _(env):
    return _call(env.client(editor=False), "GET", "/api/rules/source", headers=KEY)


@case("rules_source_200_session")
def _(env):
    client = env.client()
    env.login(client)
    return _call(client, "GET", "/api/rules/source")


@case("rules_source_401")
def _(env):
    return _call(env.client(), "GET", "/api/rules/source")


@case("rules_source_503_no_config")
def _(env):
    return _call(env.client(with_config=False), "GET", "/api/rules/source", headers=KEY)


@case("rules_validate_200_valid")
def _(env):
    return _call(env.client(), "POST", "/api/rules/validate", headers=KEY, json={"content": RULES})


@case("rules_validate_200_invalid")
def _(env):
    return _call(
        env.client(),
        "POST",
        "/api/rules/validate",
        headers=KEY,
        json={"content": INVALID_RULES},
    )


@case("rules_validate_200_yaml_syntax_error")
def _(env):
    return _call(
        env.client(),
        "POST",
        "/api/rules/validate",
        headers=KEY,
        json={"content": "rules:\n  - id: [unclosed\n"},
    )


@case("rules_validate_400_no_content")
def _(env):
    return _call(env.client(), "POST", "/api/rules/validate", headers=KEY, json={})


@case("rules_validate_413_oversized")
def _(env):
    return _call(
        env.client(),
        "POST",
        "/api/rules/validate",
        headers=KEY,
        json={"content": "x" * (3 * 1024 * 1024)},
    )


@case("rules_save_200_saved")
def _(env):
    client = env.client()
    etag = env.etag(client)
    env.clock.set(FROZEN_AT + timedelta(minutes=5))
    new = RULES.replace("stalledDL", "stalledUP")
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": f'"{etag}"'},
        json={"content": new},
    )


@case("rules_save_200_unchanged")
def _(env):
    client = env.client()
    etag = env.etag(client)
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": f'W/"{etag}"'},
        json={"content": RULES},
    )


@case("rules_save_200_etag_in_body")
def _(env):
    client = env.client()
    etag = env.etag(client)
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers=KEY,
        json={"content": RULES + "\n", "etag": etag},
    )


@case("rules_save_400_no_content")
def _(env):
    return _call(
        env.client(),
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": '"x"'},
        json={"etag": "x"},
    )


@case("rules_save_401")
def _(env):
    return _call(env.client(), "PUT", "/api/rules/source", json={"content": RULES})


@case("rules_save_403_editor_disabled")
def _(env):
    client = env.client(editor=False)
    etag = env.etag(client)
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": f'"{etag}"'},
        json={"content": RULES + "\n"},
    )


@case("rules_save_403_session_without_csrf")
def _(env):
    client = env.client()
    env.login(client)
    etag = client.get("/api/rules/source").get_json()["etag"]
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={"If-Match": f'"{etag}"'},
        json={"content": RULES + "\n"},
    )


@case("rules_save_412_stale_etag")
def _(env):
    client = env.client()
    etag = env.etag(client)
    env.write_rules(RULES + "# edited elsewhere\n")
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": f'"{etag}"'},
        json={"content": RULES.replace("stalledDL", "stalledUP")},
    )


@case("rules_save_422_invalid")
def _(env):
    client = env.client()
    etag = env.etag(client)
    return _call(
        client,
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": f'"{etag}"'},
        json={"content": INVALID_RULES},
    )


@case("rules_save_428_no_if_match")
def _(env):
    return _call(env.client(), "PUT", "/api/rules/source", headers=KEY, json={"content": RULES})


@case("rules_save_503_no_config")
def _(env):
    return _call(
        env.client(with_config=False),
        "PUT",
        "/api/rules/source",
        headers={**KEY, "If-Match": '"x"'},
        json={"content": RULES},
    )


def _save_once(env, client):
    etag = env.etag(client)
    env.clock.set(FROZEN_AT + timedelta(minutes=5))
    client.put(
        "/api/rules/source",
        headers={**KEY, "If-Match": f'"{etag}"'},
        json={"content": RULES.replace("stalledDL", "stalledUP")},
    )
    env.clock.set(FROZEN_AT)


@case("rules_history_200")
def _(env):
    client = env.client()
    _save_once(env, client)
    return _call(client, "GET", "/api/rules/history", headers=KEY)


@case("rules_history_200_empty")
def _(env):
    return _call(env.client(), "GET", "/api/rules/history", headers=KEY)


@case("rules_history_401")
def _(env):
    return _call(env.client(), "GET", "/api/rules/history")


@case("rules_history_version_200")
def _(env):
    client = env.client()
    _save_once(env, client)
    version_id = client.get("/api/rules/history", headers=KEY).get_json()["versions"][0]["id"]
    return _call(client, "GET", f"/api/rules/history/{version_id}", headers=KEY)


@case("rules_history_version_404")
def _(env):
    return _call(env.client(), "GET", "/api/rules/history/20200101T000000000000Z", headers=KEY)


@case("rules_history_version_404_bad_id")
def _(env):
    return _call(env.client(), "GET", "/api/rules/history/..%2Frules.yml", headers=KEY)


@case("rules_catalog_200")
def _(env):
    return _call(env.client(), "GET", "/api/rules/catalog", headers=KEY)


@case("rules_catalog_200_no_config")
def _(env):
    return _call(env.client(with_config=False), "GET", "/api/rules/catalog", headers=KEY)


@case("config_source_200")
def _(env):
    return _call(env.client(), "GET", "/api/config/source", headers=KEY)


@case("config_source_401")
def _(env):
    return _call(env.client(), "GET", "/api/config/source")


@case("config_source_503_no_config")
def _(env):
    return _call(env.client(with_config=False), "GET", "/api/config/source", headers=KEY)


# -- /metrics -------------------------------------------------------------------


@case("metrics_200")
def _(env):
    env.seed_jobs()
    return _call(env.client(metrics_on=True), "GET", "/metrics", headers=KEY)


@case("metrics_401")
def _(env):
    return _call(env.client(metrics_on=True), "GET", "/metrics")


@case("metrics_404_disabled")
def _(env):
    return _call(env.client(), "GET", "/metrics", headers=KEY)


# -- error handlers -------------------------------------------------------------


@case("error_404_unknown_endpoint")
def _(env):
    return _call(env.client(), "GET", "/api/nope", headers=KEY)


@case("error_405_wrong_method")
def _(env):
    # No 405 handler is registered: Werkzeug's HTML page, not JSON
    return _call(env.client(), "POST", "/api/jobs", headers=KEY)


# ---------------------------------------------------------------------------
# Capture and compare
# ---------------------------------------------------------------------------


def _mask(env: Env, body: str, content_type: str) -> "tuple[str, List[str]]":
    masked: List[str] = []

    config_dir = str(env.config_dir)
    if config_dir in body:
        body = body.replace(config_dir, "<config_dir>")
        masked.append("config directory -> <config_dir>")

    python_version = f'"python_version":"{sys.version.split()[0]}"'
    if python_version in body:
        body = body.replace(python_version, '"python_version":"<python_version>"')
        masked.append("python_version")

    if content_type.startswith("text/plain") and "# TYPE qbt_rules_" in body:
        kept = []
        for line in body.splitlines(keepends=True):
            name = line.split()[2] if line.startswith("# ") else re.split(r"[{ ]", line)[0]
            if any(name == m or name.startswith(m + "{") for m in STATE_METRICS):
                kept.append(line)
        body = "".join(kept)
        masked.append("metrics: event counters/histograms dropped, state gauges kept")

    return body, masked


def _selected_headers(response) -> Dict[str, str]:
    headers = {h: response.headers[h] for h in SELECTED_HEADERS if h in response.headers}
    if "Allow" in headers:
        # Werkzeug builds Allow from a set, so its order varies run to run
        headers["Allow"] = ", ".join(sorted(m.strip() for m in headers["Allow"].split(",")))
    return headers


def _record(env: Env, name: str, request: str, response) -> Dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    body, masked = _mask(env, response.get_data(as_text=True), content_type)
    paths: List[str] = []
    if content_type.startswith("application/json"):
        paths = timestamp_paths(json.loads(body))
    return {
        "case": name,
        "backend": env.backend,
        "request": request,
        "status": response.status_code,
        "content_type": content_type,
        "headers": _selected_headers(response),
        "timestamp_paths": paths,
        "masked": masked,
        "body": body,
    }


def _golden_path(backend: str, name: str) -> Path:
    return GOLDEN_DIR / backend / f"{name}.json"


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text("utf-8"))


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("backend", BACKENDS)
def test_golden_response(backend, name, tmp_path, monkeypatch):
    env = Env(backend, tmp_path, monkeypatch)
    request, response = CASES[name](env)
    actual = _record(env, name, request, response)
    path = _golden_path(backend, name)

    if UPDATE_GOLDENS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n", "utf-8")
        return

    expected = _load(path)
    assert (
        expected is not None
    ), f"No golden file {path} -- run QBT_RULES_UPDATE_GOLDENS=1 pytest tests/golden"
    # Body first, as text, so a mismatch shows a readable diff
    assert actual["body"] == expected["body"]
    assert actual == expected


def test_every_golden_file_has_a_case():
    """A renamed or deleted case must not leave a stale golden behind"""
    expected = {f"{b}/{n}.json" for b in BACKENDS for n in CASES}
    found = {f"{p.parent.name}/{p.name}" for p in GOLDEN_DIR.glob("*/*.json")}
    assert found - expected == set()


@pytest.mark.parametrize("name", list(CASES))
def test_backends_agree_after_timestamp_normalisation(name):
    """
    Once normalise_timestamps() rewrites SQLite's RFC 822 dates as ISO
    8601, both backends answer every case identically apart from the
    backend class name -- i.e. the timestamp format is the only
    difference the port has to iron out
    """
    goldens = {b: _load(_golden_path(b, name)) for b in BACKENDS}
    if any(g is None for g in goldens.values()):
        pytest.skip("golden files not generated yet")

    def comparable(g):
        body = g["body"].replace("SQLiteQueue", "<backend>").replace("RedisQueue", "<backend>")
        if g["content_type"].startswith("application/json"):
            body = normalise_timestamps(json.loads(body))
        return {k: g[k] for k in ("status", "content_type", "headers", "timestamp_paths")}, body

    assert comparable(goldens["sqlite"]) == comparable(goldens["redis"])
