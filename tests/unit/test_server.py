"""Running the server: uvicorn, the access log filter, one process, and SIGTERM."""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from qbt_rules import server
from qbt_rules.config import ConfigError, load_config

ACCESS = '%s - "%s %s HTTP/%s" %d'


def _record(target: str, msg: str = ACCESS) -> logging.LogRecord:
    args: Any = ("127.0.0.1:5555", "GET", target, "1.1", 200) if msg == ACCESS else (target,)
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


class TestRedactKey:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("/api/jobs?key=s3cret", "/api/jobs?key=[REDACTED]"),
            (
                "/api/jobs?status=pending&key=s3cret&limit=5",
                "/api/jobs?status=pending&key=[REDACTED]&limit=5",
            ),
            ("/?KEY=s3cret#top", "/?KEY=[REDACTED]#top"),
            ("/api/jobs?monkey=banana", "/api/jobs?monkey=banana"),
            ("/api/jobs?key=", "/api/jobs?key=[REDACTED]"),
            ("/api/jobs", "/api/jobs"),
        ],
    )
    def test_redacts_only_the_key(self, url: str, expected: str) -> None:
        assert server.redact_key(url) == expected


class TestAccessLogFilter:
    def test_redacts_the_key(self) -> None:
        record = _record("/api/jobs?key=s3cret&status=pending")
        assert server.AccessLogFilter(quiet=True).filter(record)
        assert record.getMessage() == (
            '127.0.0.1:5555 - "GET /api/jobs?key=[REDACTED]&status=pending HTTP/1.1" 200'
        )

    @pytest.mark.parametrize(
        "target",
        ["/healthz", "/readyz", "/api/health", "/metrics?key=s3cret", "/static/editor.js"],
    )
    def test_quiet_drops_polling(self, target: str) -> None:
        assert not server.AccessLogFilter(quiet=True).filter(_record(target))
        assert server.AccessLogFilter(quiet=False).filter(_record(target))

    def test_quiet_keeps_everything_else(self) -> None:
        for target in ("/api/jobs", "/", "/rules/edit", "/api/healthz"):
            assert server.AccessLogFilter(quiet=True).filter(_record(target))

    def test_any_other_record_is_redacted_whole(self) -> None:
        record = _record("/x?key=s3cret", msg="odd line %s")
        assert server.AccessLogFilter(quiet=True).filter(record)
        assert record.getMessage() == "odd line /x?key=[REDACTED]"
        untouched = _record("/x", msg="odd line %s")
        assert server.AccessLogFilter(quiet=True).filter(untouched)
        assert untouched.args == ("/x",)

    def test_installed_once_on_uvicorns_access_logger(self) -> None:
        access = logging.getLogger("uvicorn.access")
        try:
            server.install_access_log_filter(quiet=True)
            installed = server.install_access_log_filter(quiet=False)
            filters = [f for f in access.filters if isinstance(f, server.AccessLogFilter)]
            assert filters == [installed]
            assert installed.quiet is False
        finally:
            for f in list(access.filters):
                access.removeFilter(f)


def test_more_than_one_worker_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"server\.workers.*must be 1, got 4"):
        load_config(tmp_path / "missing.yaml", environ={"QBT_RULES_SERVER_WORKERS": "4"})
    settings = load_config(tmp_path / "missing.yaml", environ={"QBT_RULES_SERVER_WORKERS": "1"})
    server.check_one_process(settings)


def test_serve_runs_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    environ = {"QBT_RULES_LISTEN_PORT": "5099", "QBT_RULES_LOGGING_LEVEL": "WARNING"}
    settings = load_config(tmp_path / "missing.yaml", environ=environ)
    try:
        server.serve(settings)
    finally:
        access = logging.getLogger("uvicorn.access")
        for f in list(access.filters):
            access.removeFilter(f)
    [(app, kw)] = calls
    assert app.title == "qbt-rules"
    assert kw["port"] == 5099
    assert kw["log_config"] is None
    assert kw["log_level"] == "warning"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_sigterm_stops_the_server_and_joins_the_worker(tmp_path: Path) -> None:
    """The legacy Gunicorn `serve` ignored SIGTERM (docker stop waited for SIGKILL)"""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QBT_RULES_", "PROMETHEUS_"))}
    env.update(
        QBT_RULES_CONFIG=str(tmp_path / "config.yaml"),
        QBT_RULES_STATE_DIR=str(tmp_path / "state"),
        QBT_RULES_LISTEN_HOST="127.0.0.1",
        QBT_RULES_LISTEN_PORT=str(port),
        QBT_RULES_SERVER_API_KEY="k",
    )
    log = tmp_path / "serve.log"
    with log.open("wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "qbt_rules", "serve"], env=env, stdout=out, stderr=out
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as r:
                        if r.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError):
                    pass
                assert proc.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(0.1)

            started = time.monotonic()
            proc.send_signal(signal.SIGTERM)
            code = proc.wait(timeout=10)
            elapsed = time.monotonic() - started
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    output = log.read_text()
    assert elapsed < 5, output
    # uvicorn re-raises the signal once the lifespan has finished: killed by SIGTERM
    assert code in (0, -signal.SIGTERM), output
    assert "Worker loop exited" in output
    assert "Background thread worker stopped" in output
