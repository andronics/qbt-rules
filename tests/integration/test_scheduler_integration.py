"""
Integration tests for the internal cron scheduler

Verifies the Scheduler enqueues real jobs into a real queue backend end
to end -- not just that it calls a mocked queue.enqueue().
"""

import time

import pytest

from qbt_rules.queue_manager import create_queue
from qbt_rules.scheduler import Scheduler


@pytest.fixture
def temp_db_path(tmp_path):
    """Create temporary SQLite database path"""
    return str(tmp_path / "test_scheduler_queue.db")


@pytest.fixture
def queue_backend(temp_db_path):
    """Create a real SQLite queue backend"""
    queue = create_queue('sqlite', db_path=temp_db_path)
    yield queue
    queue.close()


class TestSchedulerEndToEnd:
    """Verify a due schedule entry actually lands a job in the real queue"""

    def test_due_entry_enqueues_real_job(self, queue_backend):
        """A due schedule entry should produce a real, retrievable queued job"""
        scheduler = Scheduler(
            queue=queue_backend,
            entries=[{'cron': '* * * * *', 'context': 'nightly'}],
            poll_interval=0.01,
        )
        # Force immediate firing instead of waiting for a real minute boundary
        scheduler._entries[0]['next_fire'] = time.time() - 1

        scheduler.start()
        time.sleep(0.1)
        scheduler.stop()

        jobs = queue_backend.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]['context'] == 'nightly'
        assert jobs[0]['status'] == 'pending'

    def test_multiple_ticks_enqueue_multiple_jobs(self, queue_backend):
        """Firing on successive ticks should enqueue a separate job each time"""
        scheduler = Scheduler(
            queue=queue_backend,
            entries=[{'cron': '* * * * *', 'context': 'nightly'}],
            poll_interval=0.02,
        )
        scheduler._entries[0]['next_fire'] = time.time() - 1

        scheduler.start()
        time.sleep(0.05)
        # Force it due again for a second fire
        scheduler._entries[0]['next_fire'] = time.time() - 1
        time.sleep(0.05)
        scheduler.stop()

        jobs = queue_backend.list_jobs()
        assert len(jobs) == 2
        assert all(j['context'] == 'nightly' for j in jobs)

    def test_regression_replaces_external_cron_sweep(self, queue_backend):
        """
        Acceptance test for the malware-incident fix (see BUGS.md): that fix
        relied on an external 30-minute cron hitting context=cron. A
        schedule: entry with the same context must produce the same job
        submission the external cron job used to.
        """
        scheduler = Scheduler(
            queue=queue_backend,
            entries=[{'cron': '*/30 * * * *', 'context': 'cron'}],
            poll_interval=0.01,
        )
        scheduler._entries[0]['next_fire'] = time.time() - 1

        scheduler.start()
        time.sleep(0.1)
        scheduler.stop()

        jobs = queue_backend.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]['context'] == 'cron'
        assert jobs[0]['hash'] is None  # sweeps the whole library, same as the external cron did
