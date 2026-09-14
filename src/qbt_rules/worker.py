"""
Worker Process - Background job processor

Consumes jobs from queue and executes them using RulesEngine.
Runs in separate thread with graceful shutdown support.
"""

import threading
import time
import logging
import traceback
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from qbt_rules.queue_manager import QueueManager, JobStatus
from qbt_rules.api import QBittorrentAPI
from qbt_rules.engine import RulesEngine
from qbt_rules.config import Config

logger = logging.getLogger(__name__)


class Worker:
    """
    Background worker that processes queued jobs

    Runs in a separate thread, continuously polling the queue for pending jobs.
    Each job is executed sequentially using the RulesEngine.
    """

    def __init__(
        self,
        queue: QueueManager,
        api: QBittorrentAPI,
        config: Config,
        poll_interval: float = 1.0,
        notifications_config: Optional[Dict[str, str]] = None
    ):
        """
        Initialize worker

        Args:
            queue: Queue manager instance
            api: qBittorrent API client
            config: Configuration object
            poll_interval: Seconds to wait between queue polls (default: 1.0)
            notifications_config: Pre-resolved notifications config (default
                webhook URL/service, already _FILE-resolved) for the notify
                action -- resolved once at server startup, since ActionExecutor
                has no access to CLI args to resolve _FILE secrets itself
        """
        self.queue = queue
        self.api = api
        self.config = config
        self.poll_interval = poll_interval
        self.notifications_config = notifications_config

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_job_completed: Optional[datetime] = None

        logger.info("Worker initialized")

    def start(self):
        """Start worker thread"""
        # Check if truly running (thread exists and is alive)
        if self.running and self.thread and self.thread.is_alive():
            logger.warning("Worker already running")
            return

        # Reset state and start new thread
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=False, name="worker")
        self.thread.start()
        logger.info("Worker thread started")

    def stop(self, timeout: float = 30.0):
        """
        Stop worker thread gracefully

        Args:
            timeout: Maximum seconds to wait for current job to complete
        """
        if not self.running:
            return

        logger.info("Stopping worker...")
        self.running = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)

            if self.thread.is_alive():
                logger.warning(f"Worker did not stop within {timeout}s timeout")
            else:
                logger.info("Worker stopped gracefully")

    def is_alive(self) -> bool:
        """Check if worker thread is alive"""
        return self.thread is not None and self.thread.is_alive()

    def get_status(self) -> Dict[str, Any]:
        """
        Get worker status

        Returns:
            Dictionary with worker status information
        """
        return {
            'running': self.running,
            'thread_alive': self.is_alive(),
            'last_job_completed': self.last_job_completed.isoformat() if self.last_job_completed else None,
            'queue_depth': self.queue.get_queue_depth()
        }

    def _run_loop(self):
        """Main worker loop - runs in separate thread"""
        logger.info("Worker loop started")

        while self.running:
            try:
                # Try to dequeue a job
                job = self.queue.dequeue()

                if job:
                    # Process job
                    self._process_job(job)
                else:
                    # Queue empty, sleep and retry
                    time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}", exc_info=True)
                time.sleep(self.poll_interval)

        logger.info("Worker loop exited")

    def _process_job(self, job: Dict[str, Any]):
        """
        Process a single job

        Args:
            job: Job dictionary from queue
        """
        job_id = job['job_id']
        context = job.get('context')
        hash_filter = job.get('hash')

        logger.info(f"Processing job {job_id} (context={context}, hash={hash_filter})")

        started_at = datetime.now(timezone.utc)

        try:
            # Execute job via RulesEngine
            result = self._execute_job(context, hash_filter)

            # Mark job as completed
            completed_at = datetime.now(timezone.utc)
            self.queue.update_status(
                job_id=job_id,
                status=JobStatus.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                result=result
            )

            self.last_job_completed = completed_at

            execution_time = (completed_at - started_at).total_seconds()
            logger.info(
                f"Job {job_id} completed successfully in {execution_time:.2f}s "
                f"(torrents: {result.get('torrents_processed', 0)}, "
                f"rules matched: {result.get('rules_matched', 0)}, "
                f"actions: {result.get('actions_executed', 0)})"
            )

        except Exception as e:
            # Mark job as failed
            error_msg = f"{type(e).__name__}: {str(e)}"
            error_trace = traceback.format_exc()

            completed_at = datetime.now(timezone.utc)
            self.queue.update_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                error=error_trace
            )

            logger.error(f"Job {job_id} failed: {error_msg}")
            logger.debug(f"Job {job_id} traceback:\n{error_trace}")

    def _execute_job(self, context: Optional[str], hash_filter: Optional[str]) -> Dict[str, Any]:
        """
        Execute job using RulesEngine

        Args:
            context: Context filter (weekly-cleanup, torrent-imported, etc.)
            hash_filter: Optional torrent hash filter

        Returns:
            Job result dictionary with execution statistics

        Raises:
            Exception: Any error during execution (will be caught and logged)
        """
        # Determine dry-run mode from config
        dry_run = self.config.is_dry_run()

        # Create RulesEngine instance
        engine = RulesEngine(
            api=self.api,
            config=self.config,
            dry_run=dry_run,
            notifications_config=self.notifications_config
        )

        # Execute rules
        engine.run(context=context, torrent_hash=hash_filter)

        # Extract statistics from engine
        stats = engine.stats

        result = {
            'total_torrents': stats.total_torrents,
            'torrents_processed': stats.processed,
            'rules_matched': stats.rules_matched,
            'actions_executed': stats.actions_executed,
            'actions_skipped': stats.actions_skipped,
            'errors': stats.errors,
            'dry_run': dry_run
        }

        return result

    def __repr__(self) -> str:
        return f"<Worker running={self.running} alive={self.is_alive()}>"
