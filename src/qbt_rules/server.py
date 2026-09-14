"""
HTTP API Server - Flask application with job queue integration

Provides REST API for:
- Job execution (queueing jobs)
- Job status and management
- Health checks and statistics
- Authentication via API key
"""

import os
import re
import secrets
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from functools import wraps

from flask import Flask, request, jsonify, Response, render_template

from qbt_rules.queue_manager import QueueManager, JobStatus
from qbt_rules.worker import Worker
from qbt_rules.config import Config
from qbt_rules.__version__ import __version__

logger = logging.getLogger(__name__)

# Global references (set by create_app)
queue: QueueManager = None
worker: Worker = None
api_key_config: str = None
dashboard_config: Optional[Config] = None


def create_app(
    queue_manager: QueueManager,
    worker_instance: Worker,
    api_key: str,
    config: Optional[Config] = None
) -> Flask:
    """
    Create and configure Flask application

    Args:
        queue_manager: Queue manager instance
        worker_instance: Worker instance
        api_key: API authentication key
        config: Loaded Config instance, used by the read-only /dashboard/rules
            view. Optional (defaults to None) so existing callers that don't
            need the dashboard's rules view are unaffected; that one route
            reports itself unavailable if config wasn't provided

    Returns:
        Configured Flask app
    """
    global queue, worker, api_key_config, dashboard_config

    queue = queue_manager
    worker = worker_instance
    api_key_config = api_key
    dashboard_config = config

    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    # Disable Flask's default logger (use our configured logger instead)
    app.logger.disabled = True
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    # Register blueprints/routes
    register_routes(app)
    register_dashboard_routes(app)

    logger.info("Flask application created")
    return app


def require_api_key(f):
    """
    Decorator for endpoints requiring API key authentication

    Checks for API key in:
    1. Query parameter: ?key=xxx
    2. Header: X-API-Key: xxx

    Returns 401 if missing or invalid.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get API key from query param or header
        key = request.args.get('key') or request.headers.get('X-API-Key')

        # Constant-time comparison to prevent timing attacks
        if not key or not secrets.compare_digest(key, api_key_config):
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Invalid or missing API key'
            }), 401

        return f(*args, **kwargs)

    return decorated_function


def register_routes(app: Flask):
    """Register all API routes"""

    @app.route('/api/execute', methods=['POST'])
    @require_api_key
    def execute():
        """
        Queue job for execution

        Query Parameters:
            context (optional): Context filter (weekly-cleanup, torrent-imported, etc.)
            hash (optional): Torrent hash filter
            key (required): API key

        Returns:
            202: Job queued successfully
            400: Invalid parameters
            401: Unauthorized
        """
        context = request.args.get('context')
        hash_filter = request.args.get('hash')

        try:
            # Enqueue job
            job_id = queue.enqueue(context=context, hash_filter=hash_filter)

            # Get full job details
            job = queue.get_job(job_id)

            logger.info(f"Job queued: {job_id} (context={context}, hash={hash_filter})")

            return jsonify(job), 202

        except Exception as e:
            logger.error(f"Error queueing job: {e}", exc_info=True)
            return jsonify({
                'error': 'Internal Server Error',
                'message': str(e)
            }), 500

    @app.route('/api/jobs', methods=['GET'])
    @require_api_key
    def list_jobs():
        """
        List jobs with filtering and pagination

        Query Parameters:
            status (optional): Filter by status
            context (optional): Filter by context
            limit (optional): Max results (default: 50, max: 100)
            offset (optional): Pagination offset (default: 0)
            key (required): API key

        Returns:
            200: List of jobs
            401: Unauthorized
        """
        status = request.args.get('status')
        context = request.args.get('context')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        # Validate status
        if status and not QueueManager.validate_status(status):
            return jsonify({
                'error': 'Bad Request',
                'message': f'Invalid status: {status}'
            }), 400

        try:
            jobs = queue.list_jobs(
                status=status,
                context=context,
                limit=limit,
                offset=offset
            )

            total = queue.count_jobs(status=status)

            return jsonify({
                'total': total,
                'limit': limit,
                'offset': offset,
                'jobs': jobs
            }), 200

        except Exception as e:
            logger.error(f"Error listing jobs: {e}", exc_info=True)
            return jsonify({
                'error': 'Internal Server Error',
                'message': str(e)
            }), 500

    @app.route('/api/jobs/<job_id>', methods=['GET'])
    @require_api_key
    def get_job(job_id: str):
        """
        Get job by ID

        Path Parameters:
            job_id: Job ID (UUID)

        Query Parameters:
            key (required): API key

        Returns:
            200: Job details
            404: Job not found
            401: Unauthorized
        """
        job = queue.get_job(job_id)

        if not job:
            return jsonify({
                'error': 'Not Found',
                'message': f'Job not found: {job_id}'
            }), 404

        return jsonify(job), 200

    @app.route('/api/jobs/<job_id>', methods=['DELETE'])
    @require_api_key
    def cancel_job(job_id: str):
        """
        Cancel pending job

        Path Parameters:
            job_id: Job ID (UUID)

        Query Parameters:
            key (required): API key

        Returns:
            200: Job cancelled
            400: Job cannot be cancelled (not pending)
            404: Job not found
            401: Unauthorized
        """
        job = queue.get_job(job_id)

        if not job:
            return jsonify({
                'error': 'Not Found',
                'message': f'Job not found: {job_id}'
            }), 404

        if job['status'] != JobStatus.PENDING:
            return jsonify({
                'error': 'Bad Request',
                'message': f"Cannot cancel job in status: {job['status']}"
            }), 400

        success = queue.cancel_job(job_id)

        if success:
            logger.info(f"Job cancelled: {job_id}")
            return jsonify({
                'job_id': job_id,
                'status': JobStatus.CANCELLED,
                'message': 'Job cancelled successfully'
            }), 200
        else:
            return jsonify({
                'error': 'Internal Server Error',
                'message': 'Failed to cancel job'
            }), 500

    @app.route('/api/health', methods=['GET'])
    def health():
        """
        Health check endpoint (no authentication required)

        Returns:
            200: Service healthy
            503: Service unhealthy
        """
        errors = []

        # Check queue backend
        if not queue.health_check():
            errors.append("Queue backend not accessible")

        # Check worker
        if not worker.is_alive():
            errors.append("Worker thread not running")

        # Check for stuck processing jobs
        processing_count = queue.count_jobs(JobStatus.PROCESSING)
        if processing_count > 5:  # Arbitrary threshold
            errors.append(f"Too many processing jobs: {processing_count}")

        if errors:
            return jsonify({
                'status': 'unhealthy',
                'errors': errors,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503

        # Healthy response
        worker_status = worker.get_status()

        return jsonify({
            'status': 'healthy',
            'version': __version__,
            'queue': {
                'backend': queue.__class__.__name__,
                'pending_jobs': queue.get_queue_depth(),
                'processing_jobs': queue.count_jobs(JobStatus.PROCESSING)
            },
            'worker': {
                'status': 'running' if worker_status['running'] else 'stopped',
                'last_job_completed': worker_status['last_job_completed']
            },
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200

    @app.route('/api/stats', methods=['GET'])
    @require_api_key
    def stats():
        """
        Get server statistics

        Query Parameters:
            key (required): API key

        Returns:
            200: Statistics
            401: Unauthorized
        """
        try:
            queue_stats = queue.get_stats()
            worker_status = worker.get_status()

            return jsonify({
                'jobs': {
                    'total': queue_stats['total_jobs'],
                    'pending': queue_stats['pending'],
                    'processing': queue_stats['processing'],
                    'completed': queue_stats['completed'],
                    'failed': queue_stats['failed'],
                    'cancelled': queue_stats['cancelled']
                },
                'performance': {
                    'average_execution_time': f"{queue_stats['average_execution_time']}s" if queue_stats['average_execution_time'] else None,
                },
                'queue': {
                    'backend': queue.__class__.__name__,
                    'depth': queue.get_queue_depth()
                },
                'worker': {
                    'status': 'running' if worker_status['running'] else 'stopped',
                    'last_job_completed': worker_status['last_job_completed']
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 200

        except Exception as e:
            logger.error(f"Error getting stats: {e}", exc_info=True)
            return jsonify({
                'error': 'Internal Server Error',
                'message': str(e)
            }), 500

    @app.route('/api/version', methods=['GET'])
    def version():
        """
        Get version information (no authentication required)

        Returns:
            200: Version info
        """
        return jsonify({
            'version': __version__,
            'api_version': '1.0',
            'python_version': os.sys.version.split()[0]
        }), 200

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors"""
        return jsonify({
            'error': 'Not Found',
            'message': 'Endpoint not found'
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors"""
        logger.error(f"Internal server error: {error}", exc_info=True)
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred'
        }), 500


_TRACEBACK_EXCEPTION_LINE = re.compile(r'^[A-Za-z_][\w.]*(?:Error|Exception|Warning)\b.*:', re.MULTILINE)


def _summarize_error(error: str) -> str:
    """
    Extract the final exception's summary line(s) from a full Python
    traceback (as stored by worker.py via traceback.format_exc())

    A traceback can be a chain of several exceptions ("During handling
    of the above exception..."), each contributing its own zero-indent
    "SomeError: message" line -- stack frame lines are always indented,
    so matching only zero-indent lines and taking the last match finds
    the final, most relevant exception, skipping past every earlier
    cause and every "File ..." frame line. Returns everything from that
    point to the end of the string (covering multi-line messages, like
    this project's own bulleted ConnectionError format).

    Falls back to the input's last non-empty line if it doesn't look
    like a Python traceback at all.
    """
    if not error:
        return error

    matches = list(_TRACEBACK_EXCEPTION_LINE.finditer(error))
    if not matches:
        lines = error.strip().splitlines()
        return lines[-1] if lines else error

    return error[matches[-1].start():].strip()


def register_dashboard_routes(app: Flask):
    """
    Register read-only web dashboard routes

    Server-rendered via Flask + Jinja2 (templates in src/qbt_rules/templates/),
    reusing the same queue/worker/config data the JSON API already exposes --
    no new query logic. Auth reuses require_api_key via the same ?key=
    query param the JSON API supports; every internal link carries it
    forward so navigating between pages stays authenticated.
    """

    @app.route('/dashboard', methods=['GET'])
    @require_api_key
    def dashboard_overview():
        """Dashboard home: worker/queue status + job counts by status"""
        queue_stats = queue.get_stats()
        worker_status = worker.get_status()

        return render_template(
            'dashboard.html',
            active='overview',
            api_key=request.args.get('key', ''),
            queue_backend=queue.__class__.__name__,
            queue_stats=queue_stats,
            worker_status=worker_status,
            version=__version__,
        )

    @app.route('/dashboard/jobs', methods=['GET'])
    @require_api_key
    def dashboard_jobs():
        """Paginated job list, optionally filtered by status"""
        status = request.args.get('status')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        jobs = queue.list_jobs(status=status, limit=limit, offset=offset)
        total = queue.count_jobs(status=status)

        return render_template(
            'jobs.html',
            active='jobs',
            api_key=request.args.get('key', ''),
            jobs=jobs,
            total=total,
            limit=limit,
            offset=offset,
            status=status,
        )

    @app.route('/dashboard/jobs/<job_id>', methods=['GET'])
    @require_api_key
    def dashboard_job_detail(job_id: str):
        """Single job's full detail, including result/error if present"""
        job = queue.get_job(job_id)
        error_summary = _summarize_error(job['error']) if job and job.get('error') else None

        return render_template(
            'job_detail.html',
            active='jobs',
            api_key=request.args.get('key', ''),
            job=job,
            job_id=job_id,
            error_summary=error_summary,
        ), (200 if job else 404)

    @app.route('/dashboard/rules', methods=['GET'])
    @require_api_key
    def dashboard_rules():
        """Read-only rules.yml view, sourced from the same hot-reload-aware
        Config.get_rules() the rules engine itself uses"""
        rules = dashboard_config.get_rules() if dashboard_config is not None else None

        return render_template(
            'rules.html',
            active='rules',
            api_key=request.args.get('key', ''),
            rules=rules,
            config_available=dashboard_config is not None,
        )


def run_server(
    app: Flask,
    host: str = '0.0.0.0',
    port: int = 5000,
    workers: int = 1,
    log_http_access: bool = False
):
    """
    Run Flask app with Gunicorn in production mode

    Args:
        app: Flask application
        host: Bind address
        port: Bind port
        workers: Number of Gunicorn workers
        log_http_access: Enable HTTP access logging (default: False to suppress health checks)
    """
    from gunicorn.app.base import BaseApplication
    from gunicorn.glogging import Logger

    class FilteredLogger(Logger):
        """Custom Gunicorn logger that filters out health check and dashboard requests"""

        def access(self, resp, req, environ, request_time):
            """Override access log to filter /api/health and /dashboard* requests"""
            # Only filter if log_http_access is False
            if not log_http_access:
                # Skip logging for health check endpoint
                if environ.get('PATH_INFO') == '/api/health':
                    return
                # Skip logging for dashboard pages -- the dashboard's only
                # auth mechanism is a ?key= query param, and a browsing
                # session hits many more URLs than a scripted API client
                # typically would, so logging every one repeats the key
                # in cleartext far more than the JSON API does
                if environ.get('PATH_INFO', '').startswith('/dashboard'):
                    return

            # Log all other requests (or all requests if log_http_access is True)
            super().access(resp, req, environ, request_time)

    class StandaloneApplication(BaseApplication):
        def __init__(self, app, options=None):
            self.application = app
            self.options = options or {}
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key, value)

        def load(self):
            return self.application

    def post_fork(server, worker_process):
        """
        Gunicorn post-fork hook - restart worker thread in forked process

        When Gunicorn forks, threads don't survive the fork. We need to
        restart the worker thread in each forked worker process.
        """
        logger.info(f"Gunicorn worker {worker_process.pid} forked - restarting worker thread")

        # Import here to access the global worker instance
        from qbt_rules.server import worker as worker_instance

        # Stop any existing thread (should be dead anyway after fork)
        if worker_instance.running:
            worker_instance.running = False

        # Restart the worker thread in this process
        worker_instance.start()
        logger.info(f"Worker thread restarted in Gunicorn worker {worker_process.pid}")

    options = {
        'bind': f'{host}:{port}',
        'workers': workers,
        'worker_class': 'sync',
        'timeout': 120,
        'accesslog': '-',  # Log to stdout
        'errorlog': '-',   # Log to stderr
        'loglevel': 'warning',
        'logger_class': FilteredLogger,  # Use custom logger to filter health checks
        'preload_app': True,  # Load app before forking workers
        'post_fork': post_fork,  # Restart worker thread after fork
    }

    logger.info(f"Starting Gunicorn server on {host}:{port} with {workers} worker(s)")

    app_instance = StandaloneApplication(app, options)
    app_instance.run()
