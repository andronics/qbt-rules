"""
Comprehensive tests for scheduler.py - Internal cron scheduler

Test coverage for:
- Scheduler initialization and cron parsing
- Thread lifecycle (start, stop, is_alive)
- Firing due entries and enqueuing jobs
- Status reporting
- Error handling and recovery
- Graceful shutdown
"""

import time
import threading
import logging

import pytest

from qbt_rules.scheduler import Scheduler


@pytest.fixture
def mock_queue(mocker):
    """Create mock queue manager"""
    queue = mocker.MagicMock()
    queue.enqueue.return_value = "job-123"
    return queue


@pytest.fixture
def entries():
    """A couple of representative schedule entries"""
    return [
        {'cron': '*/30 * * * *', 'context': 'cron'},
        {'cron': '0 3 * * *', 'context': 'nightly'},
    ]


@pytest.fixture
def scheduler(mock_queue, entries):
    """Create scheduler instance (not started), short poll interval for testing"""
    return Scheduler(queue=mock_queue, entries=entries, poll_interval=0.01)


class TestSchedulerInitialization:
    """Test Scheduler initialization"""

    def test_init_stores_queue(self, mock_queue, entries):
        """Should store queue reference"""
        s = Scheduler(mock_queue, entries)
        assert s.queue is mock_queue

    def test_init_parses_all_entries(self, mock_queue, entries):
        """Should parse every entry into an internal cron iterator"""
        s = Scheduler(mock_queue, entries)
        assert len(s._entries) == 2
        assert s._entries[0]['context'] == 'cron'
        assert s._entries[1]['context'] == 'nightly'

    def test_init_computes_next_fire_for_each_entry(self, mock_queue, entries):
        """Should compute a next_fire timestamp in the future for each entry"""
        now = time.time()
        s = Scheduler(mock_queue, entries)
        for entry in s._entries:
            assert entry['next_fire'] > now

    def test_init_default_poll_interval(self, mock_queue, entries):
        """Should use default poll interval of 30.0"""
        s = Scheduler(mock_queue, entries)
        assert s.poll_interval == 30.0

    def test_init_custom_poll_interval(self, mock_queue, entries):
        """Should set custom poll interval"""
        s = Scheduler(mock_queue, entries, poll_interval=5.0)
        assert s.poll_interval == 5.0

    def test_init_not_running(self, scheduler):
        """Should not be running after init"""
        assert scheduler.running is False

    def test_init_no_thread(self, scheduler):
        """Should have no thread after init"""
        assert scheduler.thread is None

    def test_init_no_last_fire(self, scheduler):
        """Should have no last_fire after init"""
        assert scheduler.last_fire is None

    def test_init_empty_entries(self, mock_queue):
        """Should handle an empty entries list"""
        s = Scheduler(mock_queue, [])
        assert s._entries == []


class TestSchedulerStart:
    """Test scheduler.start() method"""

    def test_start_sets_running_flag(self, scheduler):
        """Should set running flag to True"""
        scheduler.start()
        assert scheduler.running is True
        scheduler.stop()

    def test_start_creates_thread(self, scheduler):
        """Should create scheduler thread"""
        scheduler.start()
        assert scheduler.thread is not None
        assert isinstance(scheduler.thread, threading.Thread)
        scheduler.stop()

    def test_start_thread_is_alive(self, scheduler):
        """Should start thread that is alive"""
        scheduler.start()
        assert scheduler.thread.is_alive()
        scheduler.stop()

    def test_start_thread_name(self, scheduler):
        """Should name thread 'scheduler'"""
        scheduler.start()
        assert scheduler.thread.name == 'scheduler'
        scheduler.stop()

    def test_start_thread_daemon_false(self, scheduler):
        """Should create non-daemon thread"""
        scheduler.start()
        assert scheduler.thread.daemon is False
        scheduler.stop()

    def test_start_already_running_does_nothing(self, scheduler):
        """Should not start a second thread if already running"""
        scheduler.start()
        first_thread = scheduler.thread
        scheduler.start()
        assert scheduler.thread is first_thread
        scheduler.stop()

    def test_start_with_no_entries_does_not_start_thread(self, mock_queue):
        """Should skip starting a thread entirely if there are no schedule entries"""
        s = Scheduler(mock_queue, [])
        s.start()
        assert s.running is False
        assert s.thread is None


class TestSchedulerStop:
    """Test scheduler.stop() method"""

    def test_stop_sets_running_false(self, scheduler):
        """Should set running flag to False"""
        scheduler.start()
        scheduler.stop()
        assert scheduler.running is False

    def test_stop_waits_for_thread(self, scheduler):
        """Should wait for thread to finish"""
        scheduler.start()
        scheduler.stop(timeout=5.0)
        assert not scheduler.thread.is_alive()

    def test_stop_without_start_does_nothing(self, scheduler):
        """Should handle stop without start gracefully"""
        scheduler.stop()
        assert scheduler.running is False

    def test_stop_timeout_logs_warning(self, mock_queue, entries, caplog):
        """Should log warning when scheduler doesn't stop within timeout"""
        block_event = threading.Event()

        def blocking_enqueue(**kwargs):
            block_event.wait(timeout=5)  # Block for up to 5 seconds
            return "job-123"

        mock_queue.enqueue.side_effect = blocking_enqueue

        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1  # fire immediately, then block in enqueue()
        s._entries[1]['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.05)  # Let it start and enter the blocking enqueue call

        with caplog.at_level(logging.WARNING):
            s.stop(timeout=0.01)

        assert any("did not stop within" in r.message for r in caplog.records)

        # Clean up: unblock the thread so it can actually exit
        block_event.set()
        time.sleep(0.1)

    def test_stop_already_stopped_does_nothing(self, scheduler):
        """Should handle double stop gracefully"""
        scheduler.start()
        scheduler.stop()
        scheduler.stop()
        assert scheduler.running is False


class TestSchedulerIsAlive:
    """Test scheduler.is_alive() method"""

    def test_is_alive_before_start(self, scheduler):
        assert scheduler.is_alive() is False

    def test_is_alive_after_start(self, scheduler):
        scheduler.start()
        assert scheduler.is_alive() is True
        scheduler.stop()

    def test_is_alive_after_stop(self, scheduler):
        scheduler.start()
        scheduler.stop()
        assert scheduler.is_alive() is False

    def test_is_alive_no_thread(self, scheduler):
        scheduler.thread = None
        assert scheduler.is_alive() is False


class TestSchedulerGetStatus:
    """Test scheduler.get_status() method"""

    def test_get_status_returns_dict(self, scheduler):
        status = scheduler.get_status()
        assert isinstance(status, dict)

    def test_get_status_includes_running(self, scheduler):
        status = scheduler.get_status()
        assert status['running'] is False

    def test_get_status_includes_entry_count(self, scheduler):
        status = scheduler.get_status()
        assert status['entry_count'] == 2

    def test_get_status_includes_last_fire_none_initially(self, scheduler):
        status = scheduler.get_status()
        assert status['last_fire'] is None

    def test_get_status_includes_next_fires(self, scheduler):
        status = scheduler.get_status()
        assert len(status['next_fires']) == 2
        assert status['next_fires'][0]['context'] == 'cron'

    def test_get_status_running_scheduler(self, scheduler):
        scheduler.start()
        status = scheduler.get_status()
        assert status['running'] is True
        assert status['thread_alive'] is True
        scheduler.stop()


class TestSchedulerFiring:
    """Test scheduler firing due entries"""

    def test_fires_when_due(self, mock_queue, entries):
        """Should enqueue a job when an entry's next_fire has passed"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1  # already due
        s._entries[1]['next_fire'] = time.time() + 3600  # not due

        s.start()
        time.sleep(0.1)
        s.stop()

        mock_queue.enqueue.assert_called_once_with(context='cron')

    def test_does_not_fire_when_not_due(self, mock_queue, entries):
        """Should not enqueue anything if no entry is due yet"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        for entry in s._entries:
            entry['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.05)
        s.stop()

        mock_queue.enqueue.assert_not_called()

    def test_advances_next_fire_after_firing(self, mock_queue, entries):
        """Should compute a new next_fire after firing, in the future"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1
        s._entries[1]['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.1)
        s.stop()

        assert s._entries[0]['next_fire'] > time.time()

    def test_updates_last_fire(self, mock_queue, entries):
        """Should record the last fire's context, job_id, and timestamp"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1
        s._entries[1]['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.1)
        s.stop()

        assert s.last_fire is not None
        assert s.last_fire['context'] == 'cron'
        assert s.last_fire['job_id'] == 'job-123'

    def test_multiple_due_entries_all_fire(self, mock_queue, entries):
        """Should fire every due entry in the same tick, not just the first"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1
        s._entries[1]['next_fire'] = time.time() - 1

        s.start()
        time.sleep(0.1)
        s.stop()

        assert mock_queue.enqueue.call_count == 2
        contexts = {c.kwargs['context'] for c in mock_queue.enqueue.call_args_list}
        assert contexts == {'cron', 'nightly'}

    def test_enqueue_error_does_not_crash_loop(self, mock_queue, entries):
        """Should log and continue if queue.enqueue() raises"""
        mock_queue.enqueue.side_effect = Exception("queue error")
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1
        s._entries[1]['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.1)

        assert s.is_alive()
        s.stop()

    def test_loop_survives_unexpected_error(self, mock_queue, entries):
        """Should log and keep running if the loop body itself raises (not just _fire)"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        s._entries[0]['next_fire'] = time.time() - 1
        s._entries[1]['next_fire'] = time.time() + 3600

        # Make advancing the cron iterator explode after it fires once,
        # simulating an unexpected error outside of _fire()'s own try/except
        original_get_next = s._entries[0]['iter'].get_next

        def failing_get_next(*args, **kwargs):
            raise RuntimeError("boom")

        s._entries[0]['iter'].get_next = failing_get_next

        s.start()
        time.sleep(0.1)

        assert s.is_alive()
        s.stop()

    def test_no_misfire_catchup(self, mock_queue, entries):
        """A single overdue entry fires once per tick, not repeatedly to 'catch up'"""
        s = Scheduler(mock_queue, entries, poll_interval=0.01)
        # Simulate a fire time far in the past
        s._entries[0]['next_fire'] = time.time() - 10000
        s._entries[1]['next_fire'] = time.time() + 3600

        s.start()
        time.sleep(0.1)
        s.stop()

        # Fired once (advances to the next real future occurrence, not a backlog)
        assert mock_queue.enqueue.call_count == 1
        assert s._entries[0]['next_fire'] > time.time()


class TestSchedulerRepr:
    """Test scheduler.__repr__() method"""

    def test_repr_before_start(self, scheduler):
        repr_str = repr(scheduler)
        assert 'Scheduler' in repr_str
        assert 'running=False' in repr_str
        assert 'entries=2' in repr_str

    def test_repr_after_start(self, scheduler):
        scheduler.start()
        repr_str = repr(scheduler)
        assert 'running=True' in repr_str
        scheduler.stop()
