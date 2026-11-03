"""
The dashboard: server-rendered pages (Flask + Jinja2), the login form, /static and /metrics

TODO(4d): the dashboard moves to FastAPI. Until then this Flask app is mounted under the
FastAPI app (api.py, through a2wsgi) for its paths only (api.DASHBOARD_PATHS); every JSON
route is api.py's. TODO(4e): /metrics moves onto interpose's Registry.

The login session is the FastAPI app's (Starlette's SessionMiddleware): ScopeSessionInterface
hands Flask the ASGI scope's session instead of a cookie of its own, so a login here is a
login for the JSON API too (sessions.py).
"""

import logging
import re
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import yaml
from flask import (
    Flask,
    Request,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.sessions import SecureCookieSession, SecureCookieSessionInterface, SessionMixin
from flask.typing import ResponseReturnValue

from qbt_rules import __version__, metrics, sessions
from qbt_rules.config_loader import Config
from qbt_rules.queue_manager import QueueManager

logger = logging.getLogger(__name__)

# Global references (set by create_app)
# create_app() sets these before the app serves anything
queue: QueueManager = None  # type: ignore[assignment]
worker: Any = None  # api.WorkerLike
# "" when no API key is configured: every authenticated request is refused (503)
api_key_config: str = ""
dashboard_config: Config | None = None
metrics_enabled: bool = False

# Largest request body accepted (the FastAPI app refuses larger ones first)
MAX_REQUEST_BYTES = 2 * 1024 * 1024


class ScopeSessionInterface(SecureCookieSessionInterface):
    """Flask's session, kept in the ASGI scope's session (Starlette's SessionMiddleware)

    Under the FastAPI app, a2wsgi puts the ASGI scope in the WSGI environ: the session is
    read from scope["session"] and written back to it, and SessionMiddleware signs and sets
    the one cookie. Run on its own (the Flask test client), Flask's own cookie is used.
    """

    def open_session(self, app: Flask, request: Request) -> SecureCookieSession | None:
        scope = request.environ.get("asgi.scope")
        if scope is None or "session" not in scope:
            return super().open_session(app, request)
        return SecureCookieSession(dict(scope["session"]))

    def save_session(self, app: Flask, session: SessionMixin, response: Response) -> None:
        scope = request.environ.get("asgi.scope")
        if scope is None or "session" not in scope:
            super().save_session(app, session, response)
            return
        if session.modified:
            scope["session"].clear()
            scope["session"].update({k: v for k, v in session.items() if k != "_permanent"})


def _timeago(value: datetime | str | None) -> str:
    """
    Jinja filter: render a timestamp as relative time ("2 hours ago")

    Args:
        value: A timezone-aware datetime (as list_jobs()/get_job() return
            for created_at/started_at/completed_at), an ISO-8601 string
            (the shape some unit-test fixtures use directly), or None

    Returns:
        A human-readable relative time string, the original string
        unchanged if it isn't valid ISO-8601, or '' for None
    """
    if value is None:
        return ""

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    seconds = (datetime.now(UTC) - value).total_seconds()
    if seconds < 60:
        return "just now"

    for unit_seconds, unit_name in (
        (86400 * 365, "year"),
        (86400 * 30, "month"),
        (86400, "day"),
        (3600, "hour"),
        (60, "minute"),
    ):
        count = int(seconds / unit_seconds)
        if count >= 1:
            return f"{count} {unit_name}{'' if count == 1 else 's'} ago"

    return "just now"


def create_app(
    queue_manager: QueueManager,
    worker_instance: Any,
    api_key: str,
    config: Config | None = None,
    metrics_config: dict[str, Any] | None = None,
    editor: bool = True,
) -> Flask:
    """
    Create the dashboard's Flask application

    Args:
        queue_manager: Queue manager instance
        worker_instance: Worker instance
        api_key: API authentication key. "" (none configured) starts the
            server anyway: authenticated requests get a 503 that says so,
            and /api/health lists it under config_problems
        config: Loaded Config instance, used by the read-only /rules
            view. Optional (defaults to None) so existing callers that don't
            need the dashboard's rules view are unaffected; that one route
            reports itself unavailable if config wasn't provided
        metrics_config: Resolved {'enabled': bool, 'multiproc_dir': str}
            from legacy_cli.py's get_metrics_config(). Optional (defaults to None,
            treated as disabled) -- metrics.init() must already have been
            called by the caller before this, since that's what actually
            makes prometheus_client importable/configured; this just
            controls whether /metrics and the HTTP request hooks are wired up
        editor: server.editor_enabled. Unused here since the editor's JSON
            API moved to api_rules.py; kept for the 4d port's signature

    Returns:
        Configured Flask app
    """
    global queue, worker, api_key_config, dashboard_config, metrics_enabled

    queue = queue_manager
    worker = worker_instance
    api_key_config = api_key
    dashboard_config = config
    metrics_enabled = bool(metrics_config and metrics_config.get("enabled"))

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    # Lax keeps the dashboard session cookie off cross-site POST/PUTs --
    # the first line of defence for the editor's write endpoints, with the
    # X-CSRF-Token check in require_api_key_or_session as the second
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.jinja_env.filters["timeago"] = _timeago

    # Under FastAPI the session is the ASGI scope's; the secret signs Flask's own
    # cookie only when this app runs on its own (tests)
    app.session_interface = ScopeSessionInterface()
    app.secret_key = sessions.session_secret(api_key)

    @app.context_processor
    def _inject_version() -> dict[str, Any]:
        """Makes {{ version }} available in every dashboard template via
        base.html's shared topbar, without threading it through every
        individual route's render_template() call -- and {{ csrf_token() }}
        for pages that call the JSON API with the session cookie."""
        return {"version": __version__, "csrf_token": lambda: sessions.csrf_token(session)}

    # Disable Flask's default logger (use our configured logger instead)
    app.logger.disabled = True
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    register_error_handlers(app)
    register_dashboard_routes(app)
    if metrics_enabled:
        register_metrics_routes(app)
        _register_http_metrics_hooks(app)

    logger.info("Dashboard application created")
    return app


NO_API_KEY_MESSAGE = (
    "No API key is configured on the server: set QBT_RULES_SERVER_API_KEY_FILE (or "
    "server.api_key) and restart"
)


def _key_matches(key: str | None) -> bool:
    """Whether key is the configured API key (never, when none is configured)"""
    return bool(key and api_key_config and secrets.compare_digest(key, api_key_config))


def require_api_key[**P](f: Callable[P, ResponseReturnValue]) -> Callable[P, ResponseReturnValue]:
    """
    The API key (?key= or X-API-Key) for /metrics: 401 without it, 503 when the
    server has none (the same answers as api.require_api_key)
    """

    @wraps(f)
    def decorated_function(*args: P.args, **kwargs: P.kwargs) -> ResponseReturnValue:
        if not api_key_config:
            return jsonify({"error": "Service Unavailable", "message": NO_API_KEY_MESSAGE}), 503
        key = request.args.get("key") or request.headers.get("X-API-Key")
        if not _key_matches(key):
            return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)

    return decorated_function


def _next_url_without_key() -> str:
    """
    Build a same-origin path+query string for the current request, with
    any ?key= stripped out -- used as the "next" destination a rejected
    dashboard request redirects back to after a successful login.
    """
    args = request.args.to_dict(flat=False)
    args.pop("key", None)
    query = "&".join(f"{k}={v}" for k, vs in args.items() for v in vs)
    return request.path + (f"?{query}" if query else "")


def _sanitize_next(next_url: str | None) -> str:
    """
    Reduce an arbitrary ?next= value down to a same-origin path+query,
    discarding any scheme/host component and any embedded ?key=.

    Used both when rendering the login form (so its hidden `next` field
    only ever holds a safe value) and again right before issuing the
    post-login redirect (defense in depth -- that hidden field is still
    client-controlled input by the time it comes back in the POST body).
    This is what makes a crafted next unable to send anyone off-site,
    since redirect() only ever receives something already reduced to a
    bare path+query, never a full URL, and can't be tricked into treating
    a scheme-relative or absolute URL as one.
    """
    parsed = urlparse(next_url or "")
    params = parse_qs(parsed.query)
    params.pop("key", None)
    query = urlencode(params, doseq=True)
    return (parsed.path or "/") + (f"?{query}" if query else "")


def require_api_key_dashboard[**P](
    f: Callable[P, ResponseReturnValue],
) -> Callable[P, ResponseReturnValue]:
    """
    Like require_api_key, but for browser-facing dashboard routes

    A scripted API client can handle a JSON 401 -- a human in a browser
    can't do anything useful with one. A valid ?key=/header still works
    as a direct, one-shot bootstrap (and refreshes the session), but
    normal navigation no longer needs the key repeated in every URL:
    a successful check establishes a signed session cookie, checked
    here on every subsequent request before falling back to requiring
    the key again. On neither a valid key nor a valid session, redirects
    to the /login form, carrying the originally requested URL through as
    ?next= so a successful login lands back where the user was headed.
    """

    @wraps(f)
    def decorated_function(*args: P.args, **kwargs: P.kwargs) -> ResponseReturnValue:
        key = request.args.get("key") or request.headers.get("X-API-Key")

        if _key_matches(key):
            sessions.log_in(session)
            return f(*args, **kwargs)

        if api_key_config and sessions.is_logged_in(session):
            return f(*args, **kwargs)

        login_kwargs: dict[str, Any] = {"next": _next_url_without_key()}
        if key:
            # A key was provided but it was wrong, as opposed to a first
            # visit with no key/session at all -- show an error on the form.
            login_kwargs["error"] = 1
        return redirect(url_for("login", **login_kwargs))

    return decorated_function


def register_error_handlers(app: Flask) -> None:
    """The JSON error bodies, for the dashboard's paths ({"error", "message"}, as api.py)"""

    @app.errorhandler(405)
    def method_not_allowed(error: Exception) -> ResponseReturnValue:
        """Handle 405 errors"""
        return jsonify(
            {
                "error": "Method Not Allowed",
                "message": f"{request.method} is not allowed for this endpoint",
            }
        ), 405

    @app.errorhandler(413)
    def too_large(error: Exception) -> ResponseReturnValue:
        """Handle bodies over MAX_CONTENT_LENGTH"""
        return jsonify(
            {
                "error": "Payload Too Large",
                "message": f"Request body exceeds {MAX_REQUEST_BYTES // (1024 * 1024)} MB",
            }
        ), 413

    @app.errorhandler(404)
    def not_found(error: Exception) -> ResponseReturnValue:
        """Handle 404 errors"""
        return jsonify({"error": "Not Found", "message": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(error: Exception) -> ResponseReturnValue:
        """Handle 500 errors"""
        logger.error(f"Internal server error: {error}", exc_info=True)
        return jsonify(
            {"error": "Internal Server Error", "message": "An unexpected error occurred"}
        ), 500


_TRACEBACK_EXCEPTION_LINE = re.compile(
    r"^[A-Za-z_][\w.]*(?:Error|Exception|Warning)\b.*:", re.MULTILINE
)


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

    return error[matches[-1].start() :].strip()


def register_dashboard_routes(app: Flask) -> None:
    """
    Register read-only web dashboard routes

    Server-rendered via Flask + Jinja2 (templates in src/qbt_rules/templates/),
    reusing the same queue/worker/config data the JSON API already exposes --
    no new query logic. Lives at the site root (/, /jobs, /rules) rather
    than under a /dashboard/ prefix, distinct from the /api/* and /metrics
    namespaces. Auth is via require_api_key_dashboard (same ?key= query
    param the JSON API supports, but redirects a human to /login instead
    of a JSON 401 on failure); every internal link carries the key forward
    so navigating between pages stays authenticated.
    """

    @app.route("/login", methods=["GET", "POST"])
    def login() -> ResponseReturnValue:
        """
        API key entry form for browser use

        Not behind require_api_key_dashboard itself -- that would make it
        impossible to ever reach. On success, establishes the session
        require_api_key_dashboard checks on every subsequent request, so
        the key doesn't need to be repeated in every URL from here on.

        `next` (where to go after a successful submission) is always run
        through _sanitize_next() before being used as a redirect target --
        both when rendering it into the form's hidden field and again on
        the POST that reads it back -- so a crafted next can't send anyone
        off-site.
        """
        if request.method == "POST":
            key = request.form.get("key", "")
            next_url = _sanitize_next(request.form.get("next"))

            if _key_matches(key):
                sessions.log_in(session)
                return redirect(next_url)

            return redirect(url_for("login", next=next_url, error=1))

        next_url = _sanitize_next(request.args.get("next"))

        return render_template(
            "login.html",
            next=next_url,
            error=bool(request.args.get("error")),
            no_api_key=not api_key_config,
        )

    @app.route("/", methods=["GET"])
    @require_api_key_dashboard
    def dashboard_overview() -> ResponseReturnValue:
        """Dashboard home: job counts by status, recent activity, rules summary"""
        queue_stats = queue.get_stats()
        recent_jobs = queue.list_jobs(limit=5)

        rules = dashboard_config.get_rules() if dashboard_config is not None else None
        rules_summary = (
            {
                "total": len(rules),
                "enabled": sum(1 for r in rules if r.get("enabled", True)),
                "rules": rules,
            }
            if rules is not None
            else None
        )

        return render_template(
            "dashboard.html",
            active="overview",
            queue_stats=queue_stats,
            recent_jobs=recent_jobs,
            rules_summary=rules_summary,
        )

    @app.route("/jobs", methods=["GET"])
    @require_api_key_dashboard
    def dashboard_jobs() -> ResponseReturnValue:
        """Paginated job list, optionally filtered by status"""
        status = request.args.get("status")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        jobs = queue.list_jobs(status=status, limit=limit, offset=offset)
        total = queue.count_jobs(status=status)

        return render_template(
            "jobs.html",
            active="jobs",
            jobs=jobs,
            total=total,
            limit=limit,
            offset=offset,
            status=status,
        )

    @app.route("/jobs/<job_id>", methods=["GET"])
    @require_api_key_dashboard
    def dashboard_job_detail(job_id: str) -> ResponseReturnValue:
        """Single job's full detail, including result/error if present"""
        job = queue.get_job(job_id)
        error_summary = _summarize_error(job["error"]) if job and job.get("error") else None

        return render_template(
            "job_detail.html",
            active="jobs",
            job=job,
            job_id=job_id,
            error_summary=error_summary,
        ), (200 if job else 404)

    @app.route("/rules", methods=["GET"])
    @require_api_key_dashboard
    def dashboard_rules() -> ResponseReturnValue:
        """Read-only rules.yml view, sourced from the same hot-reload-aware
        Config.get_rules() the rules engine itself uses"""
        rules = dashboard_config.get_rules() if dashboard_config is not None else None

        # Pair each rule with its own resolved-YAML text for the template's
        # per-rule "Show resolved YAML" panel, without mutating the rule
        # dicts get_rules() returns (those may be a direct reference to the
        # engine's cached resolved rules, not a defensive copy).
        rules_with_yaml = (
            [(rule, yaml.dump(rule, default_flow_style=False, sort_keys=False)) for rule in rules]
            if rules
            else []
        )

        return render_template(
            "rules.html",
            active="rules",
            rules=rules,
            rules_with_yaml=rules_with_yaml,
            config_available=dashboard_config is not None,
        )

    @app.route("/rules/edit", methods=["GET"])
    @require_api_key_dashboard
    def dashboard_rules_edit() -> ResponseReturnValue:
        """rules.yml editor -- the page itself is static; everything it
        shows comes from the /api/rules/* and /api/config/source endpoints"""
        return render_template(
            "rules_edit.html",
            active="rules",
            config_available=dashboard_config is not None,
        )


def register_metrics_routes(app: Flask) -> None:
    """
    Register the Prometheus /metrics endpoint

    Only called from create_app() when metrics are enabled -- by that
    point metrics.init(enabled=True) has already run (in legacy_cli.py, before
    Gunicorn forks), so prometheus_client is guaranteed importable here.
    """

    @app.route("/metrics", methods=["GET"])
    @require_api_key
    def metrics_endpoint() -> ResponseReturnValue:
        """
        Prometheus scrape endpoint

        Combines multiprocess-aggregated event counters/histograms (HTTP
        requests, actions executed, job duration, scheduler fires) with
        on-demand state gauges computed fresh from the same data /api/stats
        and /api/health already expose (queue depth/job counts, worker
        status, schedule entry count) -- see metrics.py's module docstring
        for why these are split into two different collection strategies.
        """
        worker_status = worker.get_status()
        schedule_entry_count = len(dashboard_config.schedule) if dashboard_config is not None else 0

        output = metrics.generate_metrics_output(
            queue_backend=queue.__class__.__name__,
            queue_depth=queue.get_queue_depth(),
            job_counts=queue.get_stats(),
            worker_running=worker_status["running"],
            worker_last_job_completed=worker_status["last_job_completed"],
            schedule_entry_count=schedule_entry_count,
        )
        return Response(output, mimetype=metrics.content_type())


def _register_http_metrics_hooks(app: Flask) -> None:
    """
    Register before_request/after_request hooks recording HTTP request
    count/duration metrics for every route except /metrics itself (avoids a
    self-referential scrape-of-scrape metric, standard practice)
    """

    @app.before_request
    def _metrics_start_timer() -> None:
        g._metrics_start_time = time.time()

    @app.after_request
    def _metrics_record_request(response: Response) -> Response:
        if request.endpoint != "metrics_endpoint" and hasattr(g, "_metrics_start_time"):
            duration = time.time() - g._metrics_start_time
            metrics.record_http_request(
                method=request.method,
                endpoint=request.endpoint or "unknown",
                status=response.status_code,
                duration=duration,
            )
        return response
