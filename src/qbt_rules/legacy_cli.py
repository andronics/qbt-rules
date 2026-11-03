#!/usr/bin/env python3
"""
qbt-rules CLI - Client-server architecture

Supports two modes:
1. Server mode (--serve): Runs HTTP API server with worker
2. Client mode (default): Submits jobs to server via HTTP API

Job management commands: --list-jobs, --job-status, --cancel-job, --stats

The settings come from config.py (interpose); a CLI flag overrides its
setting (apply_cli_overrides). The get_*_config() functions hand the legacy
server, worker and engine the plain dicts they take, revealing secrets only
there, at the edge (TODO(4f): the Typer CLI passes config.Config instead).
"""

import argparse
import dataclasses
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from interpose.secret import Secret

from qbt_rules import cli_ui
from qbt_rules import config as settings_module
from qbt_rules.arguments import create_parser, process_args, validate_torrent_hash
from qbt_rules.config_loader import Config
from qbt_rules.errors import handle_errors
from qbt_rules.log_setup import get_logger, setup_logging
from qbt_rules.qbittorrent import QBittorrentAPI

# logging.getLogger() returns the same object before and after setup_logging()
logger = get_logger(__name__)

# CLI flag (argparse dest) -> (setting key, config.Config field, conversion).
# Each flag beats every other source of its setting.
CLI_OVERRIDES: dict[str, tuple[str, str, Any]] = {
    "server_host": ("listen.host", "host", str),
    "server_port": ("listen.port", "port", int),
    "server_api_key": ("server.api_key", "api_key", Secret),
    "server_workers": ("server.workers", "workers", int),
    "client_server_url": ("client.server_url", "client_server_url", str),
    "client_api_key": ("client.api_key", "client_api_key", Secret),
    "queue_backend": ("queue.backend", "queue_backend", str),
    "queue_sqlite_path": ("queue.sqlite_path", "sqlite_path", Path),
    "queue_redis_url": ("queue.redis_url", "redis_url", Secret),
    "log_level": ("logging.level", "log_level", str),
}


def apply_cli_overrides(
    args: argparse.Namespace, settings: settings_module.Config
) -> settings_module.Config:
    """The settings with every CLI flag given applied over them"""
    changes: dict[str, Any] = {}
    sources = dict(settings.sources)
    for dest, (key, field_name, convert) in CLI_OVERRIDES.items():
        value = getattr(args, dest, None)
        if value is not None:
            changes[field_name] = convert(value)
            sources[key] = f"--{dest.replace('_', '-')}"
    if getattr(args, "trace", False):
        changes["trace_mode"] = True
        sources["logging.trace_mode"] = "--trace"
    if getattr(args, "dry_run", False):
        changes["dry_run"] = True
        sources["dry_run"] = "--dry-run"
    if not changes:
        return settings
    return dataclasses.replace(settings, **changes, sources=sources)


def load_config(config_path: Path | None, args: argparse.Namespace) -> Config:
    """The settings (with the CLI flags applied) and rules.yml"""
    settings = apply_cli_overrides(args, settings_module.load_config(config_path))
    return Config(settings)


def get_logging_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The logging settings, for setup_logging()

    Returns:
        Dictionary with 'level' (str), 'file' (Path, or None for the
        console only), 'trace_mode' (bool), 'http_access' (bool),
        'client_mode' (bool -- True for any invocation other than --serve,
        used by setup_logging() to keep console output bare in client mode
        while the log file still gets full diagnostic detail), 'max_bytes'
        (int -- rotate the log file once it reaches this size, 0 disables
        rotation), 'backup_count' (int -- rotated files to keep)
    """
    s = config_obj.settings
    return {
        "level": s.log_level,
        "file": s.log_file,
        "trace_mode": s.trace_mode,
        "http_access": s.http_access,
        "client_mode": not getattr(args, "serve", False),
        "max_bytes": s.log_max_bytes,
        "backup_count": s.log_backup_count,
    }


def get_qbittorrent_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    qBittorrent's Web UI address and login

    Returns:
        Dictionary with 'host', 'username', 'password'
    """
    s = config_obj.settings
    return {"host": s.qbt_host, "username": s.qbt_username, "password": s.qbt_password.reveal()}


def get_server_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The HTTP server's settings

    Returns:
        Dictionary with 'host', 'port', 'api_key' ("" when none is
        configured), 'workers', 'editor_enabled'
    """
    s = config_obj.settings
    return {
        "host": s.host,
        "port": s.port,
        "api_key": s.api_key.reveal(),
        "workers": s.workers,
        "editor_enabled": s.editor_enabled,
    }


def get_client_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The CLI client's settings

    When no client key is set (or it's the 0.10.x placeholder, which
    config.py treats as unset), the server's key is used instead. The
    usual client is `docker exec <container> qbt-rules ...` inside the
    server's own container, where the server key is right there.

    Returns:
        Dictionary with 'server_url' and 'api_key' ("" when neither is set)
    """
    s = config_obj.settings
    api_key = s.client_api_key or s.api_key
    return {"server_url": s.client_server_url, "api_key": api_key.reveal()}


def get_queue_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The job queue's settings

    Returns:
        Dictionary with 'backend', 'sqlite_path' (str), 'redis_url' and
        'cleanup_after' (seconds, or None to keep finished jobs)
    """
    s = config_obj.settings
    return {
        "backend": s.queue_backend,
        "sqlite_path": str(s.sqlite_path),
        "redis_url": s.redis_url.reveal(),
        "cleanup_after": s.cleanup_after,
    }


def get_notifications_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The notify action's defaults

    Resolved once at server startup and threaded down as a dict, since
    ActionExecutor never sees the settings itself.

    Returns:
        Dictionary with 'webhook_url' (None when unset) and 'service'
    """
    s = config_obj.settings
    return {"webhook_url": s.webhook_url.reveal() or None, "service": s.notify_service}


def get_integrations_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    The integrations: Sonarr/Radarr (arr_blocklist) and trackie (tracker.*)

    Returns:
        Dictionary with 'sonarr' and 'radarr' keys, each {'url', 'api_key'}
        (None when unset), and 'trackie' ({'url', 'max_age', 'timeout'})
    """
    s = config_obj.settings
    return {
        "sonarr": {"url": s.sonarr_url or None, "api_key": s.sonarr_api_key.reveal() or None},
        "radarr": {"url": s.radarr_url or None, "api_key": s.radarr_api_key.reveal() or None},
        # Not an arr: trackie serves tracker-side seeding stats for the
        # tracker.* field namespace. No API key -- it's read-only and meant
        # to sit on the same internal network as qbt-rules.
        "trackie": {
            "url": s.trackie_url or None,
            "max_age": s.trackie_max_age,
            "timeout": s.trackie_timeout,
        },
    }


def get_metrics_config(args: argparse.Namespace, config_obj: Config) -> dict[str, Any]:
    """
    Prometheus metrics settings

    Returns:
        Dictionary with 'enabled' (bool) and 'multiproc_dir' (str)
    """
    s = config_obj.settings
    return {"enabled": s.metrics_enabled, "multiproc_dir": str(s.metrics_multiproc_dir)}


def get_schedule_config(args: argparse.Namespace, config_obj: Config) -> list[dict[str, Any]]:
    """
    The schedule: a list of {cron, context} entries (possibly empty), from
    the config file or the QBT_RULES_SCHEDULE_<N>_CRON/_CONTEXT variables,
    already validated by config.load_config()
    """
    return config_obj.schedule


def run_server_mode(
    args: argparse.Namespace, config_obj: Config, logging_config: dict[str, Any]
) -> None:
    """
    Run server mode - Start HTTP API server with worker

    Args:
        args: Parsed CLI arguments
        config_obj: Loaded configuration object
        logging_config: Pre-resolved dict from get_logging_config(), already
            computed once by main() for setup_logging() -- threaded through
            rather than re-resolved here
    """
    logger.info("=" * 60)
    logger.info("Starting qbt-rules server")
    logger.info("=" * 60)

    # Get configurations
    server_config = get_server_config(args, config_obj)
    queue_config = get_queue_config(args, config_obj)
    notifications_config = get_notifications_config(args, config_obj)
    integrations_config = get_integrations_config(args, config_obj)
    metrics_config = get_metrics_config(args, config_obj)

    # Initialize metrics (must happen before worker/engine/scheduler/server
    # are imported below, so PROMETHEUS_MULTIPROC_DIR is set in os.environ
    # before prometheus_client is first imported anywhere in this process --
    # see metrics.py's module docstring for why this ordering matters)
    if metrics_config["enabled"]:
        multiproc_dir = Path(metrics_config["multiproc_dir"])
        multiproc_dir.mkdir(parents=True, exist_ok=True)
        for stale_file in multiproc_dir.glob("*.db"):
            stale_file.unlink()
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(multiproc_dir)

    from qbt_rules import metrics

    metrics.init(enabled=metrics_config["enabled"])
    if metrics_config["enabled"]:
        logger.info(f"Metrics enabled (multiproc dir: {metrics_config['multiproc_dir']})")

    # Settings it can start without but not fully work without (no API
    # key): start anyway, so /api/health can say what's missing
    for problem in config_obj.settings.problems:
        logger.error(f"Configuration: {problem}")
    if config_obj.settings.sources.get("listen.port", "").startswith("QBT_RULES_SERVER_PORT"):
        logger.warning(
            "QBT_RULES_SERVER_PORT is an alias of QBT_RULES_LISTEN_PORT, the one the image's "
            "healthcheck polls: set QBT_RULES_LISTEN_PORT instead"
        )

    # Initialize queue
    from qbt_rules.queue_manager import create_queue

    queue = create_queue(
        backend=queue_config["backend"],
        db_path=queue_config["sqlite_path"],
        redis_url=queue_config["redis_url"],
    )
    logger.info(f"Queue backend: {queue.__class__.__name__}")

    # Initialize qBittorrent API (lazy initialization - won't connect until first job)
    qbt_config = get_qbittorrent_config(args, config_obj)
    api = QBittorrentAPI(
        host=qbt_config["host"],
        username=qbt_config["username"],
        password=qbt_config["password"],
        connect_now=False,  # Defer connection until first job execution
    )
    logger.info(f"qBittorrent: {qbt_config['host']} (will connect on first job)")

    # Initialize worker
    from qbt_rules.worker import Worker

    worker = Worker(
        queue=queue,
        api=api,
        config=config_obj,
        notifications_config=notifications_config,
        integrations_config=integrations_config,
        cleanup_after=queue_config["cleanup_after"],
    )
    worker.start()
    logger.info("Worker started")

    # Initialize scheduler (internal cron -- must start here, before
    # run_server()/Gunicorn forks, and must NOT be restarted per-fork the
    # way the worker thread is; see Scheduler's docstring)
    from qbt_rules.scheduler import Scheduler

    schedule_entries = get_schedule_config(args, config_obj)
    scheduler = Scheduler(queue=queue, entries=schedule_entries)
    scheduler.start()

    # Create Flask app
    from qbt_rules.web import create_app, run_server

    app = create_app(
        queue_manager=queue,
        worker_instance=worker,
        api_key=server_config["api_key"],
        config=config_obj,
        metrics_config=metrics_config,
        editor=server_config["editor_enabled"],
    )

    # Run server
    logger.info(f"Starting server on {server_config['host']}:{server_config['port']}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    # Get HTTP access logging preference
    log_http_access = logging_config["http_access"]

    try:
        run_server(
            app=app,
            host=server_config["host"],
            port=server_config["port"],
            workers=server_config["workers"],
            log_http_access=log_http_access,
            metrics_enabled=metrics_config["enabled"],
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        scheduler.stop()
        worker.stop()
        logger.info("Server stopped")


def run_client_mode(args: argparse.Namespace, config_obj: Config) -> None:
    """
    Run client mode - Submit job to server via HTTP API

    Args:
        args: Parsed CLI arguments
        config_obj: Loaded configuration object
    """
    client_config = get_client_config(args, config_obj)

    # Validate API key
    if not client_config["api_key"]:
        logger.error("Client API key is required. Set via:")
        logger.error("  - CLI: --client-api-key <key>")
        logger.error("  - Env: QBT_RULES_CLIENT_API_KEY or QBT_RULES_CLIENT_API_KEY_FILE")
        logger.error("  - Config: client.api_key (or server.api_key) in config.yaml")
        sys.exit(1)

    # Determine context and hash
    context = args.context if hasattr(args, "context") and args.context else None
    hash_filter = args.hash if hasattr(args, "hash") and args.hash else None

    # Validate hash if provided
    if hash_filter:
        try:
            hash_filter = validate_torrent_hash(hash_filter)
        except ValueError as e:
            logger.error(f"Invalid torrent hash: {e}")
            sys.exit(1)

    # Submit job to server
    server_url = client_config["server_url"].rstrip("/")
    api_key = client_config["api_key"]

    logger.info(f"Submitting job to {server_url}")
    logger.info(f"  Context: {context or 'none'}")
    logger.info(f"  Hash: {hash_filter or 'all torrents'}")
    dry_run = bool(getattr(args, "dry_run", False))
    if dry_run:
        logger.info("  Dry run: yes")

    params = {"context": context, "hash": hash_filter, "key": api_key}
    if dry_run:
        params["dry_run"] = "true"

    try:
        response = requests.post(f"{server_url}/api/execute", params=params, timeout=10)

        if response.status_code == 202:
            job = response.json()
            if dry_run and job.get("dry_run") is not True:
                # A server older than per-job dry-run ignores the parameter
                # and would run the job for real -- cancel it before it starts
                _cancel_unconfirmed_dry_run(server_url, api_key, job["job_id"])
                sys.exit(1)
            logger.info(f"✓ Job queued: {job['job_id']}")
            logger.info(f"  Status: {job['status']}")
            logger.info(f"  Queued at: {job['created_at']}")

            # Wait for completion if requested
            if args.wait:
                wait_for_job(server_url, api_key, job["job_id"])

        elif response.status_code == 401:
            logger.error("Authentication failed - check API key")
            sys.exit(1)
        else:
            logger.error(f"Server error: {response.status_code}")
            logger.error(f"Response: {response.text}")
            sys.exit(1)

    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to server at {server_url}")
        logger.error("Is the server running? Start with: qbt-rules --serve")
        sys.exit(1)
    except requests.exceptions.Timeout:
        logger.error(f"Connection to {server_url} timed out")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


def _cancel_unconfirmed_dry_run(server_url: str, api_key: str, job_id: str) -> None:
    """Cancel a job the server queued without the dry-run the client asked for"""
    logger.error(
        "The server didn't confirm dry-run for this job (it's older than "
        "per-job dry-run support), so it would have run for real."
    )
    try:
        response = requests.delete(
            f"{server_url}/api/jobs/{job_id}", params={"key": api_key}, timeout=10
        )
        cancelled = response.status_code == 200
    except requests.exceptions.RequestException:
        cancelled = False
    if cancelled:
        logger.error(f"Cancelled job {job_id} before it ran.")
    else:
        logger.error(
            f"Could not cancel job {job_id}; it may already be running. "
            f"Check it with --job-status {job_id}."
        )
    logger.error(
        "Upgrade the server, or set dry_run on the server instead (QBT_RULES_DRY_RUN=true)."
    )


def wait_for_job(server_url: str, api_key: str, job_id: str) -> None:
    """
    Poll server until job completes

    Args:
        server_url: Server URL
        api_key: API key
        job_id: Job ID to monitor
    """
    logger.info(f"\nWaiting for job {job_id} to complete...")

    poll_interval = 2  # seconds
    max_wait = 300  # 5 minutes
    elapsed = 0

    while elapsed < max_wait:
        try:
            response = requests.get(
                f"{server_url}/api/jobs/{job_id}", params={"key": api_key}, timeout=10
            )

            if response.status_code == 200:
                job = response.json()
                status = job["status"]

                if status == "completed":
                    logger.info("✓ Job completed successfully")
                    result = job.get("result", {})
                    logger.info(f"  Torrents processed: {result.get('torrents_processed', 0)}")
                    logger.info(f"  Rules matched: {result.get('rules_matched', 0)}")
                    logger.info(f"  Actions executed: {result.get('actions_executed', 0)}")
                    return
                elif status == "failed":
                    logger.error("✗ Job failed")
                    error = job.get("error", "Unknown error")
                    logger.error(f"  Error: {error}")
                    sys.exit(1)
                elif status == "cancelled":
                    logger.warning("Job was cancelled")
                    sys.exit(1)
                else:
                    # Still processing
                    logger.info(f"  Status: {status} (waiting...)")

            time.sleep(poll_interval)
            elapsed += poll_interval

        except Exception as e:
            logger.error(f"Error polling job status: {e}")
            sys.exit(1)

    logger.error(f"Job did not complete within {max_wait}s")
    sys.exit(1)


def list_jobs_command(args: argparse.Namespace, config_obj: Config) -> None:
    """List jobs command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config["server_url"].rstrip("/")
    api_key = client_config["api_key"]

    status_filter = getattr(args, "status_filter", None)
    limit = getattr(args, "limit", 20)
    output_format = getattr(args, "output", "table")

    try:
        response = requests.get(
            f"{server_url}/api/jobs",
            params={"status": status_filter, "limit": limit, "key": api_key},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            jobs = data["jobs"]

            if output_format == "json":
                cli_ui.print_json(data)
                return

            if not jobs:
                cli_ui.print_message("No jobs found")
                return

            cli_ui.print_table(
                headers=["Job ID", "Status", "Context", "Created"],
                rows=[
                    [job["job_id"], job["status"], job.get("context") or "none", job["created_at"]]
                    for job in jobs
                ],
                title=f"Jobs (showing {len(jobs)} of {data['total']} total):",
            )

        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        sys.exit(1)


def job_status_command(args: argparse.Namespace, config_obj: Config) -> None:
    """Get job status command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config["server_url"].rstrip("/")
    api_key = client_config["api_key"]

    job_id = args.job_status
    output_format = getattr(args, "output", "table")

    try:
        response = requests.get(
            f"{server_url}/api/jobs/{job_id}", params={"key": api_key}, timeout=10
        )

        if response.status_code == 200:
            job = response.json()

            if output_format == "json":
                cli_ui.print_json(job)
                return

            cli_ui.print_kv_section(
                "Job Details:",
                [
                    ("Job ID", job["job_id"]),
                    ("Status", job["status"]),
                    ("Context", job.get("context") or "none"),
                    ("Hash", job.get("hash") or "all"),
                    ("Created", job["created_at"]),
                    ("Started", job["started_at"] or "not started"),
                    ("Completed", job["completed_at"] or "not completed"),
                ],
            )

            if job.get("result"):
                cli_ui.print_kv_section("Result:", list(job["result"].items()), indent=2)

            if job.get("error"):
                cli_ui.print_message(f"\n  Error:\n    {job['error']}")

        elif response.status_code == 404:
            logger.error(f"Job not found: {job_id}")
        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        sys.exit(1)


def cancel_job_command(args: argparse.Namespace, config_obj: Config) -> None:
    """Cancel job command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config["server_url"].rstrip("/")
    api_key = client_config["api_key"]

    job_id = args.cancel_job_id
    output_format = getattr(args, "output", "table")

    try:
        response = requests.delete(
            f"{server_url}/api/jobs/{job_id}", params={"key": api_key}, timeout=10
        )

        if response.status_code == 200:
            if output_format == "json":
                cli_ui.print_json(response.json())
            else:
                cli_ui.print_message(f"✓ Job cancelled: {job_id}")
        elif response.status_code == 400:
            error = response.json()
            logger.error(f"Cannot cancel job: {error['message']}")
        elif response.status_code == 404:
            logger.error(f"Job not found: {job_id}")
        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        sys.exit(1)


def stats_command(args: argparse.Namespace, config_obj: Config) -> None:
    """Get server stats command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config["server_url"].rstrip("/")
    api_key = client_config["api_key"]

    output_format = getattr(args, "output", "table")

    try:
        response = requests.get(f"{server_url}/api/stats", params={"key": api_key}, timeout=10)

        if response.status_code == 200:
            stats = response.json()

            if output_format == "json":
                cli_ui.print_json(stats)
                return

            cli_ui.print_message("\nServer Statistics:")

            cli_ui.print_kv_section(
                "Jobs:",
                [
                    ("Total", stats["jobs"]["total"]),
                    ("Pending", stats["jobs"]["pending"]),
                    ("Processing", stats["jobs"]["processing"]),
                    ("Completed", stats["jobs"]["completed"]),
                    ("Failed", stats["jobs"]["failed"]),
                    ("Cancelled", stats["jobs"]["cancelled"]),
                ],
                indent=2,
            )

            cli_ui.print_kv_section(
                "Performance:",
                [
                    (
                        "Average execution time",
                        stats["performance"]["average_execution_time"] or "N/A",
                    ),
                ],
                indent=2,
            )

            cli_ui.print_kv_section(
                "Queue:",
                [
                    ("Backend", stats["queue"]["backend"]),
                    ("Depth", stats["queue"]["depth"]),
                ],
                indent=2,
            )

            cli_ui.print_kv_section(
                "Worker:",
                [
                    ("Status", stats["worker"]["status"]),
                    ("Last job completed", stats["worker"]["last_job_completed"] or "never"),
                ],
                indent=2,
            )

        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        sys.exit(1)


@handle_errors
def main() -> None:
    """Main entry point for qbt-rules CLI"""
    # Parse arguments. `serve` is the image's CMD (template-python's Dockerfile):
    # a synonym of --serve until the Typer CLI replaces this one (TODO(4f)).
    argv = sys.argv[1:]
    if argv[:1] == ["serve"]:
        argv = ["--serve", *argv[1:]]
    parser = create_parser()
    args = parser.parse_args(argv)

    # The config file (--config, else QBT_RULES_CONFIG, else /etc/qbt-rules/config.yaml)
    config_path = process_args(args)

    # Load configuration
    config = load_config(config_path, args)

    # Setup logging
    logging_config = get_logging_config(args, config)
    setup_logging(logging_config)

    # Handle utility arguments (--validate, --list-rules)
    from qbt_rules.arguments import handle_utility_args

    utility_exit_code = handle_utility_args(args, config)
    if utility_exit_code is not None:
        sys.exit(utility_exit_code)

    # Determine mode
    if args.serve:
        # Server mode
        run_server_mode(args, config, logging_config)
    elif args.list_jobs:
        # List jobs command
        list_jobs_command(args, config)
    elif args.job_status:
        # Job status command
        job_status_command(args, config)
    elif args.cancel_job_id:
        # Cancel job command
        cancel_job_command(args, config)
    elif args.stats:
        # Stats command
        stats_command(args, config)
    else:
        # Client mode (default)
        run_client_mode(args, config)

    sys.exit(0)


if __name__ == "__main__":
    main()
