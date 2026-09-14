#!/usr/bin/env python3
"""
qbt-rules CLI - Client-server architecture

Supports two modes:
1. Server mode (--serve): Runs HTTP API server with worker
2. Client mode (default): Submits jobs to server via HTTP API

Job management commands: --list-jobs, --job-status, --cancel-job, --stats
"""

import sys
import os
import time
import requests
from pathlib import Path
from typing import Optional

from qbt_rules.arguments import create_parser, process_args, validate_torrent_hash
from qbt_rules.config import load_config, resolve_config, parse_int, parse_bool, ENV_VAR_MAP
from qbt_rules.api import QBittorrentAPI
from qbt_rules.errors import handle_errors
from qbt_rules.logging import setup_logging, get_logger

logger = None  # Set after logging is configured


def get_server_config(args, config_obj) -> dict:
    """
    Get server configuration from CLI args, env vars, or config file

    Returns:
        Dictionary with server configuration
    """
    return {
        'host': resolve_config(
            getattr(args, 'server_host', None),
            ENV_VAR_MAP.get('server.host', 'QBT_RULES_SERVER_HOST'),
            config_obj.config,
            'server.host',
            default='0.0.0.0'
        ),
        'port': parse_int(resolve_config(
            getattr(args, 'server_port', None),
            ENV_VAR_MAP.get('server.port', 'QBT_RULES_SERVER_PORT'),
            config_obj.config,
            'server.port',
            default=5000
        )),
        'api_key': resolve_config(
            getattr(args, 'server_api_key', None),
            ENV_VAR_MAP.get('server.api_key', 'QBT_RULES_SERVER_API_KEY'),
            config_obj.config,
            'server.api_key',
            default=None
        ),
        'workers': parse_int(resolve_config(
            getattr(args, 'server_workers', None),
            ENV_VAR_MAP.get('server.workers', 'QBT_RULES_SERVER_WORKERS'),
            config_obj.config,
            'server.workers',
            default=1
        ))
    }


def get_client_config(args, config_obj) -> dict:
    """
    Get client configuration from CLI args, env vars, or config file

    Returns:
        Dictionary with client configuration
    """
    return {
        'server_url': resolve_config(
            getattr(args, 'client_server_url', None),
            ENV_VAR_MAP.get('client.server_url', 'QBT_RULES_CLIENT_SERVER_URL'),
            config_obj.config,
            'client.server_url',
            default='http://localhost:5000'
        ),
        'api_key': resolve_config(
            getattr(args, 'client_api_key', None),
            ENV_VAR_MAP.get('client.api_key', 'QBT_RULES_CLIENT_API_KEY'),
            config_obj.config,
            'client.api_key',
            default=None
        )
    }


def get_queue_config(args, config_obj) -> dict:
    """
    Get queue configuration from CLI args, env vars, or config file

    Returns:
        Dictionary with queue configuration
    """
    return {
        'backend': resolve_config(
            getattr(args, 'queue_backend', None),
            ENV_VAR_MAP.get('queue.backend', 'QBT_RULES_QUEUE_BACKEND'),
            config_obj.config,
            'queue.backend',
            default='sqlite'
        ),
        'sqlite_path': resolve_config(
            getattr(args, 'queue_sqlite_path', None),
            ENV_VAR_MAP.get('queue.sqlite_path', 'QBT_RULES_QUEUE_SQLITE_PATH'),
            config_obj.config,
            'queue.sqlite_path',
            default='/config/qbt-rules.db'
        ),
        'redis_url': resolve_config(
            getattr(args, 'queue_redis_url', None),
            ENV_VAR_MAP.get('queue.redis_url', 'QBT_RULES_QUEUE_REDIS_URL'),
            config_obj.config,
            'queue.redis_url',
            default='redis://localhost:6379/0'
        )
    }


def get_notifications_config(args, config_obj) -> dict:
    """
    Get notifications configuration from CLI args, env vars, or config file

    Resolved once at server startup (same as server_config/queue_config)
    so the notify action's default webhook URL supports _FILE secrets --
    ActionExecutor never has access to CLI args, so it can't do this
    resolution itself; it's threaded down as an already-resolved dict.

    Returns:
        Dictionary with notifications configuration
    """
    return {
        'default_webhook_url': resolve_config(
            getattr(args, 'notifications_default_webhook_url', None),
            ENV_VAR_MAP.get('notifications.default_webhook_url', 'QBT_RULES_NOTIFICATIONS_WEBHOOK_URL'),
            config_obj.config,
            'notifications.default_webhook_url',
            default=None
        ),
        'default_service': resolve_config(
            getattr(args, 'notifications_default_service', None),
            ENV_VAR_MAP.get('notifications.default_service', 'QBT_RULES_NOTIFICATIONS_SERVICE'),
            config_obj.config,
            'notifications.default_service',
            default='generic'
        ),
    }


def get_schedule_config(args, config_obj) -> list:
    """
    Get the schedule configuration (list of {cron, context} entries)

    Unlike the other get_*_config functions, this has no CLI-arg or
    per-field env-var override -- a list of recurring jobs doesn't map to
    a single flag/variable the way scalar config does. It's config.yml's
    'schedule' section as-is, already validated at load time by
    Config._load_schedule().

    Returns:
        List of schedule entry dicts (possibly empty)
    """
    return config_obj.schedule


def run_server_mode(args, config_obj):
    """
    Run server mode - Start HTTP API server with worker

    Args:
        args: Parsed CLI arguments
        config_obj: Loaded configuration object
    """
    logger.info("=" * 60)
    logger.info("Starting qbt-rules server")
    logger.info("=" * 60)

    # Get configurations
    server_config = get_server_config(args, config_obj)
    queue_config = get_queue_config(args, config_obj)
    notifications_config = get_notifications_config(args, config_obj)

    # Validate API key
    if not server_config['api_key']:
        logger.error("Server API key is required. Set via:")
        logger.error("  - CLI: --server-api-key <key>")
        logger.error("  - Env: QBT_RULES_SERVER_API_KEY or QBT_RULES_SERVER_API_KEY_FILE")
        logger.error("  - Config: server.api_key in config.yml")
        sys.exit(1)

    # Initialize queue
    from qbt_rules.queue_manager import create_queue
    queue = create_queue(
        backend=queue_config['backend'],
        db_path=queue_config['sqlite_path'],
        redis_url=queue_config['redis_url']
    )
    logger.info(f"Queue backend: {queue.__class__.__name__}")

    # Initialize qBittorrent API (lazy initialization - won't connect until first job)
    qbt_config = config_obj.get_qbittorrent_config()
    api = QBittorrentAPI(
        host=qbt_config['host'],
        username=qbt_config['user'],
        password=qbt_config['pass'],
        connect_now=False  # Defer connection until first job execution
    )
    logger.info(f"qBittorrent: {qbt_config['host']} (will connect on first job)")

    # Initialize worker
    from qbt_rules.worker import Worker
    worker = Worker(queue=queue, api=api, config=config_obj, notifications_config=notifications_config)
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
    from qbt_rules.server import create_app, run_server
    app = create_app(
        queue_manager=queue,
        worker_instance=worker,
        api_key=server_config['api_key']
    )

    # Run server
    logger.info(f"Starting server on {server_config['host']}:{server_config['port']}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    # Get HTTP access logging preference
    log_http_access = config_obj.get('logging.http_access', False)

    try:
        run_server(
            app=app,
            host=server_config['host'],
            port=server_config['port'],
            workers=server_config['workers'],
            log_http_access=log_http_access
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        scheduler.stop()
        worker.stop()
        logger.info("Server stopped")


def run_client_mode(args, config_obj):
    """
    Run client mode - Submit job to server via HTTP API

    Args:
        args: Parsed CLI arguments
        config_obj: Loaded configuration object
    """
    client_config = get_client_config(args, config_obj)

    # Validate API key
    if not client_config['api_key']:
        logger.error("Client API key is required. Set via:")
        logger.error("  - CLI: --client-api-key <key>")
        logger.error("  - Env: QBT_RULES_CLIENT_API_KEY or QBT_RULES_CLIENT_API_KEY_FILE")
        logger.error("  - Config: client.api_key in config.yml")
        sys.exit(1)

    # Determine context and hash
    context = args.context if hasattr(args, 'context') and args.context else None
    hash_filter = args.hash if hasattr(args, 'hash') and args.hash else None

    # Validate hash if provided
    if hash_filter:
        try:
            hash_filter = validate_torrent_hash(hash_filter)
        except ValueError as e:
            logger.error(f"Invalid torrent hash: {e}")
            sys.exit(1)

    # Submit job to server
    server_url = client_config['server_url'].rstrip('/')
    api_key = client_config['api_key']

    logger.info(f"Submitting job to {server_url}")
    logger.info(f"  Context: {context or 'none'}")
    logger.info(f"  Hash: {hash_filter or 'all torrents'}")

    try:
        response = requests.post(
            f"{server_url}/api/execute",
            params={
                'context': context,
                'hash': hash_filter,
                'key': api_key
            },
            timeout=10
        )

        if response.status_code == 202:
            job = response.json()
            logger.info(f"✓ Job queued: {job['job_id']}")
            logger.info(f"  Status: {job['status']}")
            logger.info(f"  Queued at: {job['created_at']}")

            # Wait for completion if requested
            if args.wait:
                wait_for_job(server_url, api_key, job['job_id'])

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


def wait_for_job(server_url: str, api_key: str, job_id: str):
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
                f"{server_url}/api/jobs/{job_id}",
                params={'key': api_key},
                timeout=10
            )

            if response.status_code == 200:
                job = response.json()
                status = job['status']

                if status == 'completed':
                    logger.info(f"✓ Job completed successfully")
                    result = job.get('result', {})
                    logger.info(f"  Torrents processed: {result.get('torrents_processed', 0)}")
                    logger.info(f"  Rules matched: {result.get('rules_matched', 0)}")
                    logger.info(f"  Actions executed: {result.get('actions_executed', 0)}")
                    return
                elif status == 'failed':
                    logger.error(f"✗ Job failed")
                    error = job.get('error', 'Unknown error')
                    logger.error(f"  Error: {error}")
                    sys.exit(1)
                elif status == 'cancelled':
                    logger.warning(f"Job was cancelled")
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


def list_jobs_command(args, config_obj):
    """List jobs command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config['server_url'].rstrip('/')
    api_key = client_config['api_key']

    status_filter = getattr(args, 'status_filter', None)
    limit = getattr(args, 'limit', 20)

    try:
        response = requests.get(
            f"{server_url}/api/jobs",
            params={
                'status': status_filter,
                'limit': limit,
                'key': api_key
            },
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            jobs = data['jobs']

            if not jobs:
                logger.info("No jobs found")
                return

            logger.info(f"\nJobs (showing {len(jobs)} of {data['total']} total):\n")
            logger.info(f"{'Job ID':<38} {'Status':<12} {'Context':<15} {'Created'}")
            logger.info("-" * 100)

            for job in jobs:
                logger.info(
                    f"{job['job_id']:<38} {job['status']:<12} "
                    f"{job.get('context', 'none'):<15} {job['created_at']}"
                )

        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        sys.exit(1)


def job_status_command(args, config_obj):
    """Get job status command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config['server_url'].rstrip('/')
    api_key = client_config['api_key']

    job_id = args.job_id

    try:
        response = requests.get(
            f"{server_url}/api/jobs/{job_id}",
            params={'key': api_key},
            timeout=10
        )

        if response.status_code == 200:
            job = response.json()

            logger.info(f"\nJob Details:")
            logger.info(f"  Job ID: {job['job_id']}")
            logger.info(f"  Status: {job['status']}")
            logger.info(f"  Context: {job.get('context', 'none')}")
            logger.info(f"  Hash: {job.get('hash', 'all')}")
            logger.info(f"  Created: {job['created_at']}")
            logger.info(f"  Started: {job['started_at'] or 'not started'}")
            logger.info(f"  Completed: {job['completed_at'] or 'not completed'}")

            if job.get('result'):
                logger.info(f"\n  Result:")
                for key, value in job['result'].items():
                    logger.info(f"    {key}: {value}")

            if job.get('error'):
                logger.info(f"\n  Error:")
                logger.info(f"    {job['error']}")

        elif response.status_code == 404:
            logger.error(f"Job not found: {job_id}")
        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        sys.exit(1)


def cancel_job_command(args, config_obj):
    """Cancel job command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config['server_url'].rstrip('/')
    api_key = client_config['api_key']

    job_id = args.cancel_job_id

    try:
        response = requests.delete(
            f"{server_url}/api/jobs/{job_id}",
            params={'key': api_key},
            timeout=10
        )

        if response.status_code == 200:
            logger.info(f"✓ Job cancelled: {job_id}")
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


def stats_command(args, config_obj):
    """Get server stats command"""
    client_config = get_client_config(args, config_obj)
    server_url = client_config['server_url'].rstrip('/')
    api_key = client_config['api_key']

    try:
        response = requests.get(
            f"{server_url}/api/stats",
            params={'key': api_key},
            timeout=10
        )

        if response.status_code == 200:
            stats = response.json()

            logger.info(f"\nServer Statistics:")
            logger.info(f"\n  Jobs:")
            logger.info(f"    Total: {stats['jobs']['total']}")
            logger.info(f"    Pending: {stats['jobs']['pending']}")
            logger.info(f"    Processing: {stats['jobs']['processing']}")
            logger.info(f"    Completed: {stats['jobs']['completed']}")
            logger.info(f"    Failed: {stats['jobs']['failed']}")
            logger.info(f"    Cancelled: {stats['jobs']['cancelled']}")

            logger.info(f"\n  Performance:")
            avg_time = stats['performance']['average_execution_time']
            logger.info(f"    Average execution time: {avg_time or 'N/A'}")

            logger.info(f"\n  Queue:")
            logger.info(f"    Backend: {stats['queue']['backend']}")
            logger.info(f"    Depth: {stats['queue']['depth']}")

            logger.info(f"\n  Worker:")
            logger.info(f"    Status: {stats['worker']['status']}")
            logger.info(f"    Last job completed: {stats['worker']['last_job_completed'] or 'never'}")

        else:
            logger.error(f"Server error: {response.status_code}")

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        sys.exit(1)


@handle_errors
def main():
    """Main entry point for qbt-rules CLI"""
    global logger

    # Parse arguments
    parser = create_parser()
    args = parser.parse_args()

    # Process arguments and get config directory
    config_dir = process_args(args)

    # Load configuration
    config = load_config(config_dir)

    # Setup logging
    trace_mode = config.get_trace_mode()
    setup_logging(config, trace_mode)
    logger = get_logger(__name__)

    # Handle utility arguments (--validate, --list-rules)
    from qbt_rules.arguments import handle_utility_args
    if handle_utility_args(args, config):
        sys.exit(0)

    # Determine mode
    if args.serve:
        # Server mode
        run_server_mode(args, config)
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


if __name__ == '__main__':
    main()
