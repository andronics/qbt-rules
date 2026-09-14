"""
Comprehensive tests for metrics.py - Prometheus metrics support

Test coverage for:
- is_available()/is_enabled() before and after init()
- init() enabled/disabled behavior, including the missing-dependency error
- record_*() no-ops when disabled, real recording when enabled
- The on-demand state collector (queue/worker/scheduler gauges)
- generate_metrics_output()'s full exposition format
- Multiprocess-mode correctness (metrics aggregate across process files)
"""

import os
from pathlib import Path

import pytest

from qbt_rules import metrics


# The metrics module's enabled/disabled state is reset before and after
# every test in the whole suite by tests/conftest.py's autouse
# reset_metrics_module_state fixture (needed there rather than only here
# since test_server.py's /metrics tests also call metrics.init()).

# PROMETHEUS_MULTIPROC_DIR is set once, session-wide, at the very top of
# tests/conftest.py -- prometheus_client resolves its multiprocess-vs-
# single-process value storage exactly once, at its own first import
# anywhere in the process, so a per-test fixture trying to change the env
# var later would have no effect (and was silently producing empty
# metrics output when this test file first tried that approach). Every
# test below shares that one session-wide directory; tests use distinct
# label values per test to avoid cross-test accumulation ambiguity on the
# real multiprocess-mode Counter/Histogram objects (unaffected: the
# on-demand gauges in TestStateCollector are computed fresh from plain
# function arguments on every call, not persisted via prometheus_client's
# multiprocess value files at all).


class TestAvailability:
    """is_available() reflects whether prometheus_client is importable -- always True in this test env."""

    def test_is_available_true_when_installed(self):
        assert metrics.is_available() is True

    def test_is_enabled_false_before_init(self):
        assert metrics.is_enabled() is False


class TestInit:
    """init() enable/disable behavior."""

    def test_init_disabled_is_a_noop(self):
        metrics.init(enabled=False)
        assert metrics.is_enabled() is False

    def test_init_disabled_does_not_require_multiproc_dir(self, monkeypatch):
        """Disabled metrics must not care whether PROMETHEUS_MULTIPROC_DIR is set at all."""
        monkeypatch.delenv('PROMETHEUS_MULTIPROC_DIR', raising=False)
        metrics.init(enabled=False)
        assert metrics.is_enabled() is False

    def test_init_enabled_sets_is_enabled_true(self):
        metrics.init(enabled=True)
        assert metrics.is_enabled() is True

    def test_init_enabled_twice_does_not_raise(self):
        """Re-callable without a duplicate-timeseries error -- matters for
        test isolation, and is generally more robust regardless."""
        metrics.init(enabled=True)
        metrics.init(enabled=True)
        assert metrics.is_enabled() is True

    def test_init_enabled_but_not_installed_raises_value_error(self, monkeypatch):
        """Fail-fast, actionable error -- mirrors queue_manager.py's
        create_queue() ValueError for a missing 'redis' package."""
        monkeypatch.setattr(metrics, 'is_available', lambda: False)

        with pytest.raises(ValueError, match=r"pip install qbt-rules\[metrics\]"):
            metrics.init(enabled=True)

        assert metrics.is_enabled() is False


class TestRecordFunctionsDisabled:
    """record_*() must be silent no-ops when metrics aren't enabled -- this
    is what lets engine.py/worker.py/scheduler.py call them unconditionally."""

    def test_record_action_executed_noop(self):
        metrics.record_action_executed('stop', True)  # must not raise

    def test_record_job_duration_noop(self):
        metrics.record_job_duration(1.23)  # must not raise

    def test_record_scheduler_fire_noop(self):
        metrics.record_scheduler_fire(False)  # must not raise

    def test_record_http_request_noop(self):
        metrics.record_http_request('GET', 'health', 200, 0.01)  # must not raise


class TestRecordFunctionsEnabled:
    """record_*() actually increment/observe once enabled -- verified via generate_metrics_output()'s output."""

    def test_record_action_executed_success_and_failure(self):
        metrics.init(enabled=True)
        metrics.record_action_executed('delete_torrent', True)
        metrics.record_action_executed('delete_torrent', False)
        metrics.record_action_executed('stop', True)

        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_actions_executed_total{action_type="delete_torrent",result="success"} 1.0' in output
        assert 'qbt_rules_actions_executed_total{action_type="delete_torrent",result="failure"} 1.0' in output
        assert 'qbt_rules_actions_executed_total{action_type="stop",result="success"} 1.0' in output

    def test_record_job_duration_observed(self):
        metrics.init(enabled=True)
        metrics.record_job_duration(2.5)

        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_job_duration_seconds_sum 2.5' in output
        assert 'qbt_rules_job_duration_seconds_count 1.0' in output

    def test_record_scheduler_fire_success_and_failure(self):
        metrics.init(enabled=True)
        metrics.record_scheduler_fire(True)
        metrics.record_scheduler_fire(True)
        metrics.record_scheduler_fire(False)

        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_scheduler_fires_total{result="success"} 2.0' in output
        assert 'qbt_rules_scheduler_fires_total{result="failure"} 1.0' in output

    def test_record_http_request_counted_and_timed(self):
        metrics.init(enabled=True)
        metrics.record_http_request('GET', 'execute', 202, 0.05)

        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_http_requests_total{endpoint="execute",method="GET",status="202"} 1.0' in output
        assert 'qbt_rules_http_request_duration_seconds_count{endpoint="execute",method="GET"} 1.0' in output


class TestStateCollector:
    """The on-demand gauges reflect exactly the values passed in, computed fresh per call."""

    def test_queue_depth_gauge(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('RedisQueue', 7, {}, True, None, 0).decode()

        assert 'qbt_rules_queue_depth{backend="RedisQueue"} 7.0' in output

    def test_jobs_total_gauge_by_status(self):
        metrics.init(enabled=True)
        job_counts = {'pending': 2, 'processing': 1, 'completed': 40, 'failed': 3, 'cancelled': 1}
        output = metrics.generate_metrics_output('SQLiteQueue', 0, job_counts, True, None, 0).decode()

        for status, count in job_counts.items():
            assert f'qbt_rules_jobs_total{{status="{status}"}} {count}.0' in output

    def test_jobs_total_gauge_missing_status_defaults_to_zero(self):
        """get_stats() might not include every status key -- should default to 0, not KeyError."""
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('SQLiteQueue', 0, {'completed': 5}, True, None, 0).decode()

        assert 'qbt_rules_jobs_total{status="completed"} 5.0' in output
        assert 'qbt_rules_jobs_total{status="failed"} 0.0' in output

    def test_worker_running_gauge_true(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_worker_running 1.0' in output

    def test_worker_running_gauge_false(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, False, None, 0).decode()

        assert 'qbt_rules_worker_running 0.0' in output

    def test_worker_last_job_completed_timestamp_present(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output(
            'SQLiteQueue', 0, {}, True, '2026-01-15T10:30:00.123456', 0
        ).decode()

        assert 'qbt_rules_worker_last_job_completed_timestamp_seconds' in output

    def test_worker_last_job_completed_absent_when_never_completed(self):
        """No job has ever completed -- the gauge should be omitted
        entirely, not emitted as 0 or some sentinel (0 would be a
        misleading real Unix timestamp, 1970-01-01)."""
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0).decode()

        assert 'qbt_rules_worker_last_job_completed_timestamp_seconds' not in output

    def test_worker_last_job_completed_malformed_timestamp_omitted(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output(
            'SQLiteQueue', 0, {}, True, 'not-a-timestamp', 0
        ).decode()

        assert 'qbt_rules_worker_last_job_completed_timestamp_seconds' not in output

    def test_scheduler_entries_gauge(self):
        metrics.init(enabled=True)
        output = metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 3).decode()

        assert 'qbt_rules_scheduler_entries 3.0' in output


class TestContentType:
    def test_content_type_when_enabled(self):
        metrics.init(enabled=True)
        assert metrics.content_type().startswith('text/plain')


class TestMultiprocessAggregation:
    """The whole point of multiprocess mode: metrics recorded under
    different PIDs (simulated here by re-importing prometheus_client's
    process-identity logic isn't practical in-process, so this instead
    verifies the .db file mechanism is actually being used -- the real
    cross-process aggregation itself gets verified by the live
    multi-worker smoke test, not a unit test)."""

    def test_multiproc_dir_receives_db_files_after_recording(self):
        metrics.init(enabled=True)
        metrics.record_action_executed('stop', True)
        metrics.generate_metrics_output('SQLiteQueue', 0, {}, True, None, 0)

        multiproc_dir = Path(os.environ['PROMETHEUS_MULTIPROC_DIR'])
        db_files = list(multiproc_dir.glob('*.db'))
        assert len(db_files) > 0, "expected prometheus_client to write per-process .db files into the multiproc dir"
