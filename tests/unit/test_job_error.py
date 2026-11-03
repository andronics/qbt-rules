"""A failed job's ``error``: one line, the traceback only in the server log (#41)."""

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from qbt_rules import errors
from qbt_rules.queue_manager import JobStatus
from qbt_rules.worker import MAX_ERROR_LENGTH, Worker, job_error


def chained_connection_error() -> errors.ConnectionError:
    """The chain an unreachable qBittorrent raises: a library error wrapped in ours."""
    try:
        try:
            raise OSError("[Errno 111] Connection refused")
        except OSError as inner:
            raise errors.ConnectionError("http://127.0.0.1:1", str(inner)) from inner
    except errors.ConnectionError as outer:
        return outer


def test_a_plain_exception() -> None:
    assert job_error(ValueError("bad input")) == "ValueError: bad input"


def test_no_message() -> None:
    assert job_error(KeyError()) == "KeyError"


def test_a_multi_line_message_becomes_one_line() -> None:
    assert job_error(RuntimeError("first\n\n  second  \n")) == "RuntimeError: first; second"


def test_a_qbittorrent_error_keeps_its_details_and_fix() -> None:
    assert job_error(chained_connection_error()) == (
        "ConnectionError: Cannot reach qBittorrent server (Host: http://127.0.0.1:1; "
        "Error: [Errno 111] Connection refused; Fix: Check that qBittorrent is running and "
        "the host/port are correct)"
    )


def test_a_qbittorrent_error_without_details() -> None:
    error = errors.QBittorrentError("X-1", "Something failed")
    assert job_error(error) == "QBittorrentError: Something failed"


def test_long_messages_are_cut() -> None:
    line = job_error(ValueError("x" * 5000))
    assert len(line) == MAX_ERROR_LENGTH
    assert line.endswith("…")


def run_failing_job(exc: Exception) -> tuple[dict[str, Any], MagicMock]:
    queue = MagicMock()
    worker = Worker(queue=queue, api=MagicMock(), config=MagicMock(), poll_interval=0.01)

    def fail(context: str | None, hash_filter: str | None, job_dry_run: bool = False) -> Any:
        raise exc

    worker._execute_job = fail  # type: ignore[method-assign]
    worker._process_job({"job_id": "job-1", "context": None, "hash": None})
    return queue.update_status.call_args.kwargs, queue


def test_the_job_stores_one_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="qbt_rules.worker"):
        stored, _ = run_failing_job(chained_connection_error())
    assert stored["status"] == JobStatus.FAILED
    assert "\n" not in stored["error"]
    assert "Traceback" not in stored["error"]
    assert stored["error"].startswith("ConnectionError: Cannot reach qBittorrent server")


def test_the_traceback_goes_to_the_server_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="qbt_rules.worker"):
        run_failing_job(chained_connection_error())
    record = next(r for r in caplog.records if "Job job-1 failed" in r.getMessage())
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert "Connection refused" in caplog.text
    assert "Traceback" in caplog.text
    assert "The above exception was the direct cause" in caplog.text
