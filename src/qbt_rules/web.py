"""The dashboard: server-rendered pages (Jinja2), the login form, /static and /metrics.

The pages are FastAPI routes on the API's app (api.create_app calls ``register``), so they
share its session (Starlette's SessionMiddleware, sessions.py): logging in through the form
logs the browser in to the JSON API too, which is what the rules editor's script calls.

Links. Every URL a page or a redirect carries is relative to the page it is on
(``relative_url``), never absolute. So the dashboard works unchanged behind a reverse proxy
or an ingress that serves it under a path prefix (``/qbt/`` -> ``/``), with or without a
configured root path: the browser resolves ``../jobs`` against wherever it really is.

Auth. A page needs the login session. Without one it redirects to the login form, carrying
the page as ``?next=`` (an app path, sanitised to a same-origin path). A valid ``?key=`` on a
page URL logs the browser in and redirects to the same URL without ``key=``, so the key
doesn't stay in the address bar or the history; an ``X-API-Key`` header logs in and serves the
page. The login form posts the key in its body, with the session's CSRF token.

/metrics renders the app's interpose Registry (metrics.py). It needs the API key, as
``X-API-Key`` or ``?key=``, never the login session; it answers 404 while metrics.enabled is off.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

import yaml
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from qbt_rules import __version__, api, metrics, sessions

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Messages the login form shows for its ?error= values
LOGIN_ERRORS = {
    "1": "Invalid API key.",
    "csrf": "The sign-in form expired. Try again.",
}


# -- Links -----------------------------------------------------------------------------------------


def relative_url(from_path: str, to_path: str, query: str = "") -> str:
    """``to_path`` (and ``query``) as a URL relative to the page at ``from_path``.

    Both are paths as the server sees them. The result always starts with ``./`` or ``../``,
    so it can't be read as a scheme or a host, and resolves to ``to_path`` under whatever
    prefix the browser sees in front of both (a reverse proxy's, or the root path).
    """
    here = from_path.split("/")[1:-1]  # the page's directory
    there = to_path.split("/")[1:]
    # Directories both share (never the target's last segment, which may be a file)
    common = 0
    while common < min(len(here), len(there) - 1) and here[common] == there[common]:
        common += 1
    url = "../" * (len(here) - common) + "/".join(there[common:])
    if not url.startswith("../"):
        url = "./" + url
    return f"{url}?{query}" if query else url


def _query(params: dict[str, Any] | None) -> str:
    """A query string from ``params``, leaving out the ones that are None."""
    return urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)


def href(request: Request, name: str, query: dict[str, Any] | None = None, **path: Any) -> str:
    """The route ``name``'s URL, relative to this request's page (the templates' ``href``)."""
    return relative_url(request.url.path, request.url_for(name, **path).path, _query(query))


def app_path(request: Request) -> str:
    """This request's path inside the app: without the root path, if one is set."""
    path = request.url.path
    root = str(request.scope.get("root_path", "")).rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        path = path[len(root) :]
    return path or "/"


def redirect(request: Request, to_app_path: str, query: str = "") -> RedirectResponse:
    """A 302 to an app path (``/jobs``), relative to this request's page."""
    root = str(request.scope.get("root_path", "")).rstrip("/")
    target = root + to_app_path if request.url.path.startswith(root + "/") else to_app_path
    return RedirectResponse(relative_url(request.url.path, target, query), status_code=302)


def sanitize_next(next_url: str | None) -> str:
    """Reduce a ``?next=`` value to a same-origin app path and query, without ``key=``.

    The scheme and host are dropped, and leading slashes and backslashes collapse to one
    slash, so ``https://evil.example/x``, ``//evil.example/x`` and ``/\\evil.example`` all
    become a path here (``/x``, ``/x``, ``/evil.example``). Applied when the form is rendered
    and again to the value the POST sends back, which is client input either way.
    """
    parsed = urlsplit(next_url or "")
    path = "/" + parsed.path.lstrip("/\\").replace("\\", "/")
    params = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "key"]
    query = urlencode(params)
    return path + (f"?{query}" if query else "")


def _without_key(request: Request) -> str:
    """This request's query string with every ``key=`` removed."""
    return urlencode([(k, v) for k, v in request.query_params.multi_items() if k != "key"])


# -- Templates -------------------------------------------------------------------------------------


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


def _template_globals(request: Request) -> dict[str, Any]:
    """What every template can use, besides its own context.

    ``href(name, query={...}, **path_params)`` and ``static_href(path)`` (with ``?v=<version>``
    so an upgrade never runs a cached old script) give relative URLs; ``csrf_token()`` is the
    session's token, for forms and for the editor's API calls.
    """

    def page_href(name: str, query: dict[str, Any] | None = None, **path: Any) -> str:
        return href(request, name, query, **path)

    def static_href(path: str, versioned: bool = True) -> str:
        return href(request, "static", {"v": __version__} if versioned else None, path=path)

    return {
        "version": __version__,
        "csrf_token": lambda: sessions.csrf_token(request.session),
        "href": page_href,
        "static_href": static_href,
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_template_globals])
templates.env.filters["timeago"] = _timeago


def render(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, status_code=status_code)


class Static(StaticFiles):
    """/static, revalidated on every use (``Cache-Control: no-cache``, as Flask served it).

    The pages ask for ``?v=<version>``, so a new release is a new URL; within one version the
    ETag and Last-Modified answers make a reload cheap.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# -- Auth ------------------------------------------------------------------------------------------


class LoginRedirect(Exception):
    """Raised by ``require_login``: answer with this redirect instead of the page."""

    def __init__(self, response: RedirectResponse) -> None:
        super().__init__("login required")
        self.response = response


def _key_matches(request: Request, key: str | None) -> bool:
    configured: str = request.app.state.api_key
    return bool(key and configured and secrets.compare_digest(key, configured))


def require_login(request: Request) -> None:
    """A page's auth: the login session, or the API key once (which starts a session).

    - ``?key=`` that matches: log in, and redirect to this URL without ``key=``.
    - ``X-API-Key`` that matches: log in and serve the page.
    - A session (and an API key configured): serve the page.
    - Otherwise: redirect to the login form with ``?next=`` this page (and ``error=1`` when a
      key was sent but was wrong). With no API key configured, the form says so.

    A 503 before anything else while the app is starting, as for the JSON routes.
    """
    api.services(request)
    query_key = request.query_params.get("key")
    key = query_key or request.headers.get("X-API-Key")
    if _key_matches(request, key):
        sessions.log_in(request.session)
        if query_key:
            raise LoginRedirect(redirect(request, app_path(request), _without_key(request)))
        return
    if request.app.state.api_key and sessions.is_logged_in(request.session):
        return
    rest = _without_key(request)
    login = {"next": app_path(request) + (f"?{rest}" if rest else ""), "error": 1 if key else None}
    raise LoginRedirect(redirect(request, "/login", _query(login)))


Page = [Depends(require_login)]


# -- Routes ----------------------------------------------------------------------------------------

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


def _int_param(request: Request, name: str, default: int) -> int:
    """A non-negative integer query parameter, or ``default`` when it isn't one."""
    try:
        return max(int(request.query_params.get(name, default)), 0)
    except ValueError:
        return default


async def _form(request: Request) -> dict[str, str]:
    """An urlencoded form body (the login form's), first value per field.

    Read here rather than through python-multipart: the form is three short fields, and the
    API's BodyLimit has already refused anything over 2 MB.
    """
    body = (await request.body()).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def register(app: FastAPI, metrics_on: bool) -> None:
    """Add the dashboard's pages, the login form, /static and (when on) /metrics to ``app``."""

    async def login_redirect(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, LoginRedirect)  # noqa: S101  registered for it only
        return exc.response

    app.add_exception_handler(LoginRedirect, login_redirect)
    app.mount("/static", Static(directory=STATIC_DIR), name="static")

    @app.get("/login", include_in_schema=False)
    def login(request: Request) -> Response:
        """The sign-in form: the API key, posted in the body (never in a URL)."""
        error = request.query_params.get("error")
        return render(
            request,
            "login.html",
            next=sanitize_next(request.query_params.get("next")),
            error=LOGIN_ERRORS.get(error or "", LOGIN_ERRORS["1"] if error else None),
            no_api_key=not request.app.state.api_key,
        )

    @app.post("/login", include_in_schema=False)
    async def login_submit(request: Request) -> Response:
        """Check the CSRF token and the key, then start the session and go to ``next``."""
        form = await _form(request)
        next_url = sanitize_next(form.get("next"))
        if not sessions.csrf_ok(request.session, form.get("csrf_token")):
            return redirect(request, "/login", _query({"next": next_url, "error": "csrf"}))
        if not _key_matches(request, form.get("key")):
            return redirect(request, "/login", _query({"next": next_url, "error": 1}))
        # A fresh session (and CSRF token) for the signed-in browser
        request.session.clear()
        sessions.log_in(request.session)
        path, _, query = next_url.partition("?")
        return redirect(request, path, query)

    @app.get("/", dependencies=Page, include_in_schema=False)
    def dashboard_overview(request: Request) -> Response:
        """Dashboard home: job counts by status, recent activity, rules summary"""
        found = api.services(request)
        rules = found.rules.get_rules() if found.rules is not None else None
        rules_summary = (
            {
                "total": len(rules),
                "enabled": sum(1 for r in rules if r.get("enabled", True)),
                "rules": rules,
            }
            if rules is not None
            else None
        )
        return render(
            request,
            "dashboard.html",
            active="overview",
            queue_stats=found.queue.get_stats(),
            recent_jobs=found.queue.list_jobs(limit=5),
            rules_summary=rules_summary,
        )

    @app.get("/jobs", dependencies=Page, include_in_schema=False)
    def dashboard_jobs(request: Request) -> Response:
        """Paginated job list, optionally filtered by status"""
        queue = api.services(request).queue
        status = request.query_params.get("status") or None
        limit = _int_param(request, "limit", 50) or 50
        offset = _int_param(request, "offset", 0)
        return render(
            request,
            "jobs.html",
            active="jobs",
            jobs=queue.list_jobs(status=status, limit=limit, offset=offset),
            total=queue.count_jobs(status=status),
            limit=limit,
            offset=offset,
            status=status,
        )

    @app.get("/jobs/{job_id}", dependencies=Page, include_in_schema=False)
    def dashboard_job_detail(request: Request, job_id: str) -> Response:
        """Single job's full detail, including result/error if present"""
        job = api.services(request).queue.get_job(job_id)
        error_summary = _summarize_error(job["error"]) if job and job.get("error") else None
        return render(
            request,
            "job_detail.html",
            status_code=200 if job else 404,
            active="jobs",
            job=job,
            job_id=job_id,
            error_summary=error_summary,
        )

    @app.get("/rules", dependencies=Page, include_in_schema=False)
    def dashboard_rules(request: Request) -> Response:
        """Read-only rules.yml view, from the same hot-reloading Config.get_rules() the engine
        uses"""
        config = api.services(request).rules
        rules = config.get_rules() if config is not None else None
        # Each rule beside its own YAML for the "Show resolved YAML" panel, without changing
        # the dicts get_rules() returns (they may be the engine's cached rules)
        rules_with_yaml = (
            [(rule, yaml.dump(rule, default_flow_style=False, sort_keys=False)) for rule in rules]
            if rules
            else []
        )
        return render(
            request,
            "rules.html",
            active="rules",
            rules=rules,
            rules_with_yaml=rules_with_yaml,
            config_available=config is not None,
        )

    @app.get("/rules/edit", dependencies=Page, include_in_schema=False)
    def dashboard_rules_edit(request: Request) -> Response:
        """The rules.yml editor: everything it shows comes from the JSON API (api_rules.py)"""
        return render(
            request,
            "rules_edit.html",
            active="rules",
            config_available=api.services(request).rules is not None,
        )

    def metrics_enabled() -> None:
        if not metrics_on:
            raise api.ApiError(404, "Endpoint not found")

    @app.get(
        "/metrics",
        summary="Prometheus metrics (text exposition)",
        tags=["meta"],
        response_class=Response,
        # In this order: off is a 404 whatever the key, as if the route didn't exist
        dependencies=[Depends(metrics_enabled), *api.KeyOnly],
        responses={
            200: {"content": {metrics.CONTENT_TYPE: {}}, "description": "The metrics"},
            **api.error_responses(404),
            **api.AUTH_ERRORS,
        },
    )
    def metrics_endpoint(request: Request) -> Response:
        """The app's metrics in Prometheus text format, when `metrics.enabled` is on (404 when
        off). Needs the API key, as `X-API-Key` (preferred: Prometheus's `http_headers`) or
        `?key=`; the login session isn't accepted. The wiki's Metrics page lists the metrics.
        """
        # Sync (unlike the template's async route), so the queue reads behind the state gauges
        # run in the threadpool, not on the event loop; metrics.LOCK makes the render safe
        # beside the worker and scheduler threads and the HTTP middleware.
        found = api.services(request)
        worker_status = found.worker.get_status()
        body = request.app.state.qbt_metrics.scrape(
            queue_backend=found.queue.__class__.__name__,
            queue_depth=found.queue.get_queue_depth(),
            job_counts=found.queue.get_stats(),
            worker_running=worker_status["running"],
            worker_last_job_completed=worker_status["last_job_completed"],
            schedule_entry_count=len(found.rules.schedule) if found.rules is not None else 0,
        )
        return Response(body, media_type=metrics.CONTENT_TYPE)
