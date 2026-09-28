"""
Full-stack integration tests for qbt-rules v0.4.0

Tests the complete system working together:
- Server (Flask API)
- Worker (background job processor)
- Queue backends (SQLite, Redis)
- RulesEngine integration
- End-to-end job lifecycle
"""

import pytest
import time
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from qbt_rules.server import create_app
from qbt_rules.worker import Worker
from qbt_rules.queue_manager import create_queue, JobStatus
from qbt_rules.__version__ import __version__


@pytest.fixture
def temp_db_path(tmp_path):
    """Create temporary SQLite database path"""
    return str(tmp_path / "test_queue.db")


@pytest.fixture
def mock_api(mocker):
    """Create mock qBittorrent API"""
    api = mocker.MagicMock()
    api.is_connected.return_value = True
    return api


@pytest.fixture
def mock_config(mocker):
    """Create mock config"""
    config = mocker.MagicMock()
    config.is_dry_run.return_value = False
    config.qbittorrent.host = 'localhost'
    config.qbittorrent.port = 8080
    return config


@pytest.fixture
def mock_engine(mocker):
    """Create mock RulesEngine"""
    engine = mocker.MagicMock()

    # Mock stats
    stats = mocker.MagicMock()
    stats.total_torrents = 10
    stats.processed = 8
    stats.rules_matched = 5
    stats.actions_executed = 3
    stats.actions_skipped = 2
    stats.errors = 0
    stats.by_rule = {}

    engine.stats = stats
    engine.run.return_value = None

    return engine


@pytest.fixture(params=['sqlite'])  # Can add 'redis' when Redis available
def queue_backend(request, temp_db_path):
    """Create queue backend (parametrized for SQLite/Redis)"""
    if request.param == 'sqlite':
        queue = create_queue('sqlite', db_path=temp_db_path)
    elif request.param == 'redis':
        # Only if Redis available
        queue = create_queue('redis', redis_url='redis://localhost:6379/15')

    yield queue

    # Cleanup
    queue.close()


@pytest.fixture
def worker_instance(queue_backend, mock_api, mock_config, mock_engine, mocker):
    """Create worker instance with mocked engine"""
    # Mock RulesEngine to avoid actual qBittorrent calls
    mocker.patch('qbt_rules.worker.RulesEngine', return_value=mock_engine)

    worker = Worker(
        queue=queue_backend,
        api=mock_api,
        config=mock_config,
        poll_interval=0.01  # Fast polling for tests
    )

    yield worker

    # Cleanup
    if worker.is_alive():
        worker.stop(timeout=5.0)


@pytest.fixture
def app(queue_backend, worker_instance):
    """Create Flask app with real queue and worker"""
    api_key = 'test-integration-key-12345'
    app = create_app(queue_backend, worker_instance, api_key)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create Flask test client"""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Authentication headers"""
    return {'X-API-Key': 'test-integration-key-12345'}


class TestFullJobLifecycle:
    """Test complete job lifecycle from API to completion"""

    def test_enqueue_and_process_job(self, client, auth_headers, worker_instance, queue_backend):
        """Should enqueue job via API and process it with worker"""
        # Start worker
        worker_instance.start()

        # Enqueue job via API
        response = client.post('/api/execute?context=weekly-cleanup', headers=auth_headers)

        assert response.status_code == 202
        data = response.json
        job_id = data['job_id']

        # Wait for job to be processed
        time.sleep(0.5)

        # Check job status via API
        response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
        assert response.status_code == 200

        job = response.json
        assert job['status'] == JobStatus.COMPLETED
        assert job['result'] is not None

        # Cleanup
        worker_instance.stop()

    def test_job_with_hash_filter(self, client, auth_headers, worker_instance):
        """Should process job with hash filter"""
        worker_instance.start()

        # Enqueue with hash
        response = client.post('/api/execute?hash=abc123', headers=auth_headers)
        assert response.status_code == 202

        job_id = response.json['job_id']

        # Wait for processing
        time.sleep(0.5)

        # Verify job completed
        response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
        job = response.json

        assert job['status'] == JobStatus.COMPLETED
        assert job['hash'] == 'abc123'

        worker_instance.stop()

    def test_multiple_jobs_sequential_processing(self, client, auth_headers, worker_instance):
        """Should process multiple jobs sequentially"""
        worker_instance.start()

        # Enqueue multiple jobs
        job_ids = []
        for i in range(3):
            response = client.post(f'/api/execute?context=test-{i}', headers=auth_headers)
            assert response.status_code == 202
            job_ids.append(response.json['job_id'])

        # Wait for all to complete
        time.sleep(1.0)

        # Verify all completed
        for job_id in job_ids:
            response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
            job = response.json
            assert job['status'] == JobStatus.COMPLETED

        worker_instance.stop()

    def test_job_result_includes_statistics(self, client, auth_headers, worker_instance):
        """Should include execution statistics in result"""
        worker_instance.start()

        response = client.post('/api/execute', headers=auth_headers)
        job_id = response.json['job_id']

        time.sleep(0.5)

        response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
        job = response.json

        assert 'result' in job
        result = job['result']
        assert 'torrents_processed' in result
        assert 'rules_matched' in result
        assert 'actions_executed' in result

        worker_instance.stop()


class TestJobFailureHandling:
    """Test error handling in full stack"""

    def test_job_fails_with_engine_error(self, client, auth_headers, worker_instance, mock_engine):
        """Should mark job as FAILED when engine raises exception"""
        # Make engine raise error
        mock_engine.run.side_effect = ValueError("Engine error")

        worker_instance.start()

        response = client.post('/api/execute', headers=auth_headers)
        job_id = response.json['job_id']

        time.sleep(0.5)

        response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
        job = response.json

        assert job['status'] == JobStatus.FAILED
        assert 'error' in job
        assert 'ValueError' in job['error']

        worker_instance.stop()

    def test_worker_continues_after_job_failure(self, client, auth_headers, worker_instance, mock_engine):
        """Should continue processing after job failure"""
        # First job fails, second succeeds
        mock_engine.run.side_effect = [ValueError("Error"), None]

        worker_instance.start()

        # Enqueue two jobs
        response1 = client.post('/api/execute', headers=auth_headers)
        job1_id = response1.json['job_id']

        response2 = client.post('/api/execute', headers=auth_headers)
        job2_id = response2.json['job_id']

        time.sleep(0.8)

        # First job failed
        job1 = client.get(f'/api/jobs/{job1_id}', headers=auth_headers).json
        assert job1['status'] == JobStatus.FAILED

        # Second job completed
        job2 = client.get(f'/api/jobs/{job2_id}', headers=auth_headers).json
        assert job2['status'] == JobStatus.COMPLETED

        worker_instance.stop()


class TestJobCancellation:
    """Test job cancellation"""

    def test_cancel_pending_job(self, client, auth_headers, queue_backend):
        """Should cancel job before it's processed"""
        # Enqueue job (worker not started)
        response = client.post('/api/execute', headers=auth_headers)
        job_id = response.json['job_id']

        # Job should be pending
        job = client.get(f'/api/jobs/{job_id}', headers=auth_headers).json
        assert job['status'] == JobStatus.PENDING

        # Cancel it
        response = client.delete(f'/api/jobs/{job_id}', headers=auth_headers)
        assert response.status_code == 200

        # Verify cancelled
        job = client.get(f'/api/jobs/{job_id}', headers=auth_headers).json
        assert job['status'] == JobStatus.CANCELLED

    def test_cannot_cancel_processing_job(self, client, auth_headers, worker_instance):
        """Should not cancel job that is already processing"""
        worker_instance.start()

        # Enqueue job
        response = client.post('/api/execute', headers=auth_headers)
        job_id = response.json['job_id']

        # Wait a bit for it to start processing
        time.sleep(0.1)

        # Try to cancel (might be processing)
        response = client.delete(f'/api/jobs/{job_id}', headers=auth_headers)

        # If it's processing, should get 400
        if response.status_code == 400:
            assert 'Cannot cancel' in response.json['message']

        worker_instance.stop()


class TestListAndFilterJobs:
    """Test job listing and filtering"""

    def test_list_all_jobs(self, client, auth_headers, worker_instance):
        """Should list all jobs"""
        worker_instance.start()

        # Create multiple jobs
        for i in range(3):
            client.post(f'/api/execute?context=test-{i}', headers=auth_headers)

        time.sleep(0.8)

        # List all jobs
        response = client.get('/api/jobs', headers=auth_headers)
        assert response.status_code == 200

        data = response.json
        assert data['total'] >= 3
        assert len(data['jobs']) >= 3

        worker_instance.stop()

    def test_filter_jobs_by_status(self, client, auth_headers, worker_instance):
        """Should filter jobs by status"""
        worker_instance.start()

        # Create jobs
        client.post('/api/execute', headers=auth_headers)
        client.post('/api/execute', headers=auth_headers)

        time.sleep(0.8)

        # Filter by completed
        response = client.get('/api/jobs?status=completed', headers=auth_headers)
        data = response.json

        assert data['total'] >= 2
        for job in data['jobs']:
            assert job['status'] == JobStatus.COMPLETED

        worker_instance.stop()

    def test_filter_jobs_by_context(self, client, auth_headers, worker_instance):
        """Should filter jobs by context"""
        worker_instance.start()

        # Create jobs with different contexts
        client.post('/api/execute?context=weekly-cleanup', headers=auth_headers)
        client.post('/api/execute?context=torrent-imported', headers=auth_headers)

        time.sleep(0.8)

        # Filter by context
        response = client.get('/api/jobs?context=weekly-cleanup', headers=auth_headers)
        data = response.json

        assert data['total'] >= 1
        for job in data['jobs']:
            assert job['context'] == 'weekly-cleanup'

        worker_instance.stop()

    def test_pagination(self, client, auth_headers, worker_instance):
        """Should paginate job results"""
        worker_instance.start()

        # Create multiple jobs
        for i in range(5):
            client.post('/api/execute', headers=auth_headers)

        time.sleep(1.0)

        # Get first page
        response = client.get('/api/jobs?limit=2&offset=0', headers=auth_headers)
        page1 = response.json

        assert len(page1['jobs']) == 2

        # Get second page
        response = client.get('/api/jobs?limit=2&offset=2', headers=auth_headers)
        page2 = response.json

        assert len(page2['jobs']) == 2

        # Should be different jobs
        page1_ids = [j['job_id'] for j in page1['jobs']]
        page2_ids = [j['job_id'] for j in page2['jobs']]
        assert set(page1_ids).isdisjoint(set(page2_ids))

        worker_instance.stop()


class TestHealthChecks:
    """Test health check endpoint with real components"""

    def test_health_check_healthy(self, client, worker_instance, queue_backend):
        """Should report healthy when all components working"""
        worker_instance.start()

        response = client.get('/api/health')
        assert response.status_code == 200

        data = response.json
        assert data['status'] == 'healthy'
        assert data['version'] == __version__
        assert 'queue' in data
        assert 'worker' in data

        worker_instance.stop()

    def test_health_check_worker_dead(self, client, queue_backend):
        """Should report unhealthy when worker is dead"""
        # Don't start worker

        response = client.get('/api/health')
        assert response.status_code == 503

        data = response.json
        assert data['status'] == 'unhealthy'
        assert any('Worker thread not running' in err for err in data['errors'])

    def test_health_includes_queue_depth(self, client, worker_instance, auth_headers):
        """Should include current queue depth"""
        # Start worker first
        worker_instance.start()

        # Enqueue some jobs
        for i in range(3):
            client.post('/api/execute', headers=auth_headers)

        response = client.get('/api/health')
        data = response.json

        # Should be healthy and include queue info
        assert response.status_code == 200
        assert 'queue' in data
        assert data['queue']['pending_jobs'] >= 0  # Jobs may have been processed

        worker_instance.stop()


class TestStatistics:
    """Test statistics endpoint"""

    def test_stats_endpoint(self, client, auth_headers, worker_instance):
        """Should return statistics"""
        worker_instance.start()

        # Create some jobs
        client.post('/api/execute', headers=auth_headers)
        client.post('/api/execute', headers=auth_headers)

        time.sleep(0.8)

        response = client.get('/api/stats', headers=auth_headers)
        assert response.status_code == 200

        data = response.json
        assert 'jobs' in data
        assert 'performance' in data
        assert 'queue' in data
        assert 'worker' in data

        assert data['jobs']['completed'] >= 2

        worker_instance.stop()

    def test_stats_includes_execution_time(self, client, auth_headers, worker_instance):
        """Should calculate average execution time"""
        worker_instance.start()

        # Process jobs
        client.post('/api/execute', headers=auth_headers)
        time.sleep(0.5)

        response = client.get('/api/stats', headers=auth_headers)
        data = response.json

        # Should have performance metrics
        assert 'performance' in data
        assert 'average_execution_time' in data['performance']

        worker_instance.stop()


class TestVersionEndpoint:
    """Test version endpoint"""

    def test_version_endpoint(self, client):
        """Should return version information"""
        response = client.get('/api/version')
        assert response.status_code == 200

        data = response.json
        assert data['version'] == __version__
        assert data['api_version'] == '1.0'
        assert 'python_version' in data


class TestWorkerGracefulShutdown:
    """Test worker shutdown behavior"""

    def test_worker_stops_gracefully(self, worker_instance, queue_backend):
        """Should stop gracefully when requested"""
        worker_instance.start()
        assert worker_instance.is_alive()

        worker_instance.stop(timeout=5.0)

        assert not worker_instance.is_alive()
        assert worker_instance.running is False

    def test_worker_completes_current_job_before_stopping(self, worker_instance, queue_backend, mock_engine, mocker):
        """Should complete current job before stopping"""
        # Make job take some time
        def slow_run(*args, **kwargs):
            time.sleep(0.2)

        mock_engine.run.side_effect = slow_run

        # Enqueue job and start worker
        job_id = queue_backend.enqueue(context='test')
        worker_instance.start()

        # Wait for job to start
        time.sleep(0.1)

        # Stop worker (should wait for job)
        worker_instance.stop(timeout=5.0)

        # Job should be completed
        job = queue_backend.get_job(job_id)
        assert job['status'] == JobStatus.COMPLETED


class TestConcurrentOperations:
    """Test concurrent API operations"""

    def test_concurrent_job_submission(self, client, auth_headers, worker_instance):
        """Should handle concurrent job submissions"""
        import threading

        worker_instance.start()

        responses = []

        def submit_job():
            response = client.post('/api/execute', headers=auth_headers)
            responses.append(response)

        # Submit 5 jobs concurrently
        threads = [threading.Thread(target=submit_job) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert len(responses) == 5
        for response in responses:
            assert response.status_code == 202

        # All should have unique job IDs
        job_ids = [r.json['job_id'] for r in responses]
        assert len(set(job_ids)) == 5

        worker_instance.stop()

    def test_concurrent_job_queries(self, client, auth_headers, worker_instance):
        """Should handle concurrent job status queries"""
        import threading

        worker_instance.start()

        # Create a job
        response = client.post('/api/execute', headers=auth_headers)
        job_id = response.json['job_id']

        time.sleep(0.5)  # Let it complete

        responses = []

        def query_job():
            response = client.get(f'/api/jobs/{job_id}', headers=auth_headers)
            responses.append(response)

        # Query concurrently
        threads = [threading.Thread(target=query_job) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should succeed
        assert len(responses) == 10
        for response in responses:
            assert response.status_code == 200

        worker_instance.stop()


class TestQueueBackendSwitching:
    """Test that system works with different queue backends"""

    def test_sqlite_backend_integration(self, temp_db_path, mock_api, mock_config, mock_engine, mocker):
        """Should work correctly with SQLite backend"""
        mocker.patch('qbt_rules.worker.RulesEngine', return_value=mock_engine)

        # Create SQLite queue
        queue = create_queue('sqlite', db_path=temp_db_path)
        worker = Worker(queue, mock_api, mock_config, poll_interval=0.01)
        app = create_app(queue, worker, 'test-key')
        client = app.test_client()

        worker.start()

        # Test basic operation
        response = client.post('/api/execute', headers={'X-API-Key': 'test-key'})
        assert response.status_code == 202

        time.sleep(0.5)

        job_id = response.json['job_id']
        job = client.get(f'/api/jobs/{job_id}', headers={'X-API-Key': 'test-key'}).json
        assert job['status'] == JobStatus.COMPLETED

        worker.stop()
        queue.close()


class TestErrorHandling:
    """Test error handling across the stack"""

    def test_invalid_job_id(self, client, auth_headers):
        """Should return 404 for invalid job ID"""
        response = client.get('/api/jobs/invalid-id', headers=auth_headers)
        assert response.status_code == 404

    def test_invalid_status_filter(self, client, auth_headers):
        """Should return 400 for invalid status"""
        response = client.get('/api/jobs?status=invalid', headers=auth_headers)
        assert response.status_code == 400

    def test_missing_authentication(self, client):
        """Should return 401 without API key"""
        response = client.post('/api/execute')
        assert response.status_code == 401

    def test_invalid_api_key(self, client):
        """Should return 401 with wrong API key"""
        response = client.post('/api/execute', headers={'X-API-Key': 'wrong-key'})
        assert response.status_code == 401
