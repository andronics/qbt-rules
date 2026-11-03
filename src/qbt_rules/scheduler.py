"""
Scheduler - Internal cron scheduler for recurring jobs

Reads a list of {cron, context} entries and enqueues a job for each one
when its cron expression fires, replacing the need for an external cron
job / systemd timer / sidecar container hitting the HTTP API on a schedule.

Runs in a separate thread, structurally parallel to Worker. Calls
queue.enqueue() directly -- no HTTP round-trip, no request context
needed, since QueueManager.enqueue() has no such coupling.
"""

import logging
import threading
import time
from typing import Any

from croniter import croniter

from qbt_rules import metrics
from qbt_rules.queue_manager import QueueManager

logger = logging.getLogger(__name__)


class Scheduler:
    """
    Background scheduler that enqueues jobs on a cron schedule

    Runs in a separate thread, checking each configured entry's next-fire
    time on every poll tick and enqueuing a job when it's due.

    The server runs one process (template-python decision 0008), and the
    app's lifespan runs this once, in a thread (run()), so it fires once
    per cron tick. A second replica would fire every entry a second time.
    """

    def __init__(
        self, queue: QueueManager, entries: list[dict[str, str]], poll_interval: float = 30.0
    ):
        """
        Initialize scheduler

        Args:
            queue: Queue manager instance
            entries: List of {'cron': str, 'context': str} dicts, already
                     validated (see Config._load_schedule)
            poll_interval: Seconds between checks for due entries (default: 30.0)
        """
        self.queue = queue
        self.poll_interval = poll_interval

        self.running = False
        self.thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_fire: dict[str, Any] | None = None

        now = time.time()
        self._entries: list[dict[str, Any]] = []
        for entry in entries:
            cron_iter = croniter(entry["cron"], now)
            self._entries.append(
                {
                    "cron": entry["cron"],
                    "context": entry["context"],
                    "iter": cron_iter,
                    "next_fire": cron_iter.get_next(float),
                }
            )

        logger.info(f"Scheduler initialized with {len(self._entries)} entries")

    def start(self) -> None:
        """Start scheduler thread"""
        if not self._entries:
            logger.info("No schedule entries configured, scheduler not started")
            return

        if self.running and self.thread and self.thread.is_alive():
            logger.warning("Scheduler already running")
            return

        self.running = True
        self._stop = threading.Event()
        self.thread = threading.Thread(
            target=self._run_loop, args=(self._stop,), daemon=False, name="scheduler"
        )
        self.thread.start()
        logger.info("Scheduler thread started")

    def stop(self, timeout: float = 30.0) -> None:
        """
        Stop scheduler thread gracefully

        Args:
            timeout: Maximum seconds to wait for the thread to exit
        """
        if not self.running:
            return

        logger.info("Stopping scheduler...")
        self.running = False
        self._stop.set()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)

            if self.thread.is_alive():
                logger.warning(f"Scheduler did not stop within {timeout}s timeout")
            else:
                logger.info("Scheduler stopped gracefully")

    @property
    def has_entries(self) -> bool:
        return bool(self._entries)

    def run(self, stop: threading.Event) -> None:
        """
        The scheduler loop, in the calling thread, until stop is set

        The server's target for api.BackgroundThreads (registered only when
        there are entries)
        """
        self.thread = threading.current_thread()
        self.running = True
        try:
            self._run_loop(stop)
        finally:
            self.running = False

    def is_alive(self) -> bool:
        """Check if scheduler thread is alive"""
        return self.thread is not None and self.thread.is_alive()

    def get_status(self) -> dict[str, Any]:
        """
        Get scheduler status

        Returns:
            Dictionary with scheduler status information
        """
        return {
            "running": self.running,
            "thread_alive": self.is_alive(),
            "entry_count": len(self._entries),
            "last_fire": self.last_fire,
            "next_fires": [
                {"context": e["context"], "cron": e["cron"], "next_fire": e["next_fire"]}
                for e in self._entries
            ],
        }

    def _run_loop(self, stop: threading.Event) -> None:
        """Main scheduler loop: until stop is set"""
        logger.info("Scheduler loop started")

        while not stop.is_set():
            try:
                now = time.time()
                for entry in self._entries:
                    if now >= entry["next_fire"]:
                        self._fire(entry)
                        entry["next_fire"] = entry["iter"].get_next(float)

                stop.wait(self.poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in scheduler loop: {e}", exc_info=True)
                stop.wait(self.poll_interval)

        logger.info("Scheduler loop exited")

    def _fire(self, entry: dict[str, Any]) -> None:
        """
        Enqueue a job for a due schedule entry

        No misfire catch-up: if the process was down when a fire time
        passed, it's simply skipped, matching the external-cron behavior
        this replaces.
        """
        try:
            job_id = self.queue.enqueue(context=entry["context"])
            logger.info(
                f"Scheduled job enqueued: {job_id} (context={entry['context']}, "
                f"cron={entry['cron']})"
            )
            self.last_fire = {"context": entry["context"], "job_id": job_id, "at": time.time()}
            metrics.record_scheduler_fire(True)
        except Exception as e:
            logger.error(
                f"Failed to enqueue scheduled job (context={entry['context']}): {e}", exc_info=True
            )
            metrics.record_scheduler_fire(False)

    def __repr__(self) -> str:
        return f"<Scheduler running={self.running} entries={len(self._entries)}>"
