"""
Tests for web.py: the Flask dashboard pages, the login form and /metrics

TODO(4d, 4e): these move to the FastAPI dashboard and interpose's metrics. The JSON
API's tests are tests/unit/test_api_routes.py and tests/golden.
"""

import json
import os
from datetime import UTC, datetime

import pytest

from qbt_rules import __version__
from qbt_rules.queue_manager import JobStatus
from qbt_rules.web import _summarize_error, create_app


@pytest.fixture
def mock_queue(mocker):
    """Create mock queue manager"""
    queue = mocker.MagicMock()
    queue.__class__.__name__ = "SQLiteQueue"

    # Default behaviors
    queue.enqueue.return_value = "test-job-id-123"
    queue.get_job.return_value = {
        "job_id": "test-job-id-123",
        "context": "test",
        "hash": None,
        "status": JobStatus.PENDING,
        "created_at": "2025-01-01T12:00:00",
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    queue.list_jobs.return_value = []
    queue.count_jobs.return_value = 0
    queue.get_queue_depth.return_value = 0
    queue.health_check.return_value = True
    queue.get_stats.return_value = {
        "total_jobs": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "average_execution_time": None,
    }
    queue.cancel_job.return_value = True

    return queue


@pytest.fixture
def mock_worker(mocker):
    """Create mock worker"""
    worker = mocker.MagicMock()
    worker.is_alive.return_value = True
    worker.running = True
    worker.get_status.return_value = {"running": True, "last_job_completed": "2025-01-01T12:00:00"}

    return worker


@pytest.fixture
def app(mock_queue, mock_worker):
    """Create Flask test app with mocked dependencies"""
    api_key = "test-api-key-12345"
    app = create_app(mock_queue, mock_worker, api_key)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create Flask test client"""
    return app.test_client()


@pytest.fixture
def valid_headers():
    """Valid API key headers"""
    return {"X-API-Key": "test-api-key-12345"}


class TestErrorHandlers:
    """Test error handlers"""

    def test_404_handler(self, client):
        """Should return JSON 404 error"""
        response = client.get("/nonexistent-endpoint")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["error"] == "Not Found"
        assert "Endpoint not found" in data["message"]

    def test_404_handler_returns_json(self, client):
        """Should return JSON content type"""
        response = client.get("/api/invalid")

        assert response.content_type == "application/json"


class TestMissingLineCoverage:
    """Tests specifically designed to cover missing lines in web.py"""

    def test_500_error_handler_direct_call(self, app, mocker):
        """Directly test the 500 error handler function (lines 379-380)"""
        mock_logger = mocker.patch("qbt_rules.web.logger")

        with app.app_context():
            # Set TESTING to False and PROPAGATE_EXCEPTIONS to False
            # to allow error handlers to work
            app.config["TESTING"] = False
            app.config["PROPAGATE_EXCEPTIONS"] = False

            # Add a route that will trigger an error
            @app.route("/trigger-500")
            def trigger():
                raise Exception("Test exception")

            client = app.test_client()
            response = client.get("/trigger-500")

            # Verify we got a 500 response with our error handler's message
            assert response.status_code == 500
            data = json.loads(response.data)
            assert data["error"] == "Internal Server Error"
            assert data["message"] == "An unexpected error occurred"

            # Verify logger was called (line 379)
            mock_logger.error.assert_called()
            args = str(mock_logger.error.call_args)
            assert "Internal server error" in args


class TestSummarizeError:
    """Test _summarize_error() -- extracts the final exception's summary
    from a full traceback, for the job detail dashboard page."""

    def test_empty_string_returns_empty(self):
        assert _summarize_error("") == ""

    def test_plain_message_with_no_traceback_returned_as_is(self):
        assert _summarize_error("Something just broke") == "Something just broke"

    def test_single_exception_line(self):
        assert _summarize_error("ValueError: bad input") == "ValueError: bad input"

    def test_chained_exceptions_returns_only_the_final_one(self):
        """A traceback with multiple 'During handling of...'-chained
        exceptions should surface only the last (most relevant) one,
        not the earlier framework-internal causes."""
        traceback_text = (
            "Traceback (most recent call last):\n"
            '  File "urllib3/connection.py", line 204, in _new_conn\n'
            "    sock = connection.create_connection(\n"
            "socket.gaierror: [Errno -2] Name or service not known\n"
            "\n"
            "The above exception was the direct cause of the following exception:\n"
            "\n"
            "Traceback (most recent call last):\n"
            '  File "qbt_rules/qbittorrent.py", line 70, in _ensure_connected\n'
            "    self.client.auth_log_in()\n"
            "qbittorrentapi.exceptions.APIConnectionError: Failed to connect\n"
            "\n"
            "During handling of the above exception, another exception occurred:\n"
            "\n"
            "Traceback (most recent call last):\n"
            '  File "qbt_rules/worker.py", line 161, in _process_job\n'
            "    result = self._execute_job(context, hash_filter)\n"
            "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent server\n"
            "  • Host: http://unreachable.invalid:8080\n"
            "  • Fix: Check that qBittorrent is running"
        )

        summary = _summarize_error(traceback_text)

        assert summary.startswith(
            "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent server"
        )
        assert "Fix: Check that qBittorrent is running" in summary
        assert "socket.gaierror" not in summary
        assert "APIConnectionError" not in summary
        assert 'File "' not in summary

    def test_multiline_custom_error_message_kept_intact(self):
        """This project's own error classes format multi-line, bulleted
        messages -- the whole thing (not just the first line) should be
        part of the summary, since it's all one logical error."""
        traceback_text = (
            "Traceback (most recent call last):\n"
            '  File "qbt_rules/worker.py", line 1, in x\n'
            "    raise ConfigurationError(...)\n"
            "qbt_rules.errors.ConfigurationError: Invalid config\n"
            "  • File: /config/config.yml\n"
            "  • Fix: Check the syntax"
        )

        summary = _summarize_error(traceback_text)

        assert summary == (
            "qbt_rules.errors.ConfigurationError: Invalid config\n"
            "  • File: /config/config.yml\n"
            "  • Fix: Check the syntax"
        )


class TestTimeago:
    """Test _timeago() -- the timeago Jinja filter behind dashboard
    "Created" columns (e.g. "2 hours ago")."""

    def test_none_returns_empty_string(self):
        from qbt_rules.web import _timeago

        assert _timeago(None) == ""

    def test_invalid_string_returned_unchanged(self):
        from qbt_rules.web import _timeago

        assert _timeago("not a timestamp") == "not a timestamp"

    def test_just_now(self):

        from qbt_rules.web import _timeago

        assert _timeago(datetime.now(UTC)) == "just now"

    def test_minutes_ago(self):
        from datetime import timedelta

        from qbt_rules.web import _timeago

        dt = datetime.now(UTC) - timedelta(minutes=5)
        assert _timeago(dt) == "5 minutes ago"

    def test_singular_unit_has_no_trailing_s(self):
        from datetime import timedelta

        from qbt_rules.web import _timeago

        dt = datetime.now(UTC) - timedelta(hours=1)
        assert _timeago(dt) == "1 hour ago"

    def test_days_ago(self):
        from datetime import timedelta

        from qbt_rules.web import _timeago

        dt = datetime.now(UTC) - timedelta(days=4)
        assert _timeago(dt) == "4 days ago"

    def test_iso_string_is_parsed(self):
        """Some unit-test fixtures elsewhere in this file pass created_at
        as a plain ISO string rather than a real datetime -- the filter
        must handle both, matching what real job dicts vs. test mocks
        actually carry."""
        from datetime import timedelta

        from qbt_rules.web import _timeago

        dt = datetime.now(UTC) - timedelta(days=2)
        assert _timeago(dt.isoformat()) == "2 days ago"

    def test_naive_datetime_treated_as_utc(self):
        from datetime import timedelta

        from qbt_rules.web import _timeago

        dt = (datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None)
        assert _timeago(dt) == "3 hours ago"


class TestDashboardRoutes:
    """Test the read-only web dashboard (/, /jobs, /rules)"""

    @pytest.fixture
    def mock_config(self, mocker):
        """Mock Config instance for the rules view"""
        config = mocker.MagicMock()
        config.get_rules.return_value = [
            {
                "name": "Delete old torrents",
                "enabled": True,
                "context": "nightly",
                "stop_on_match": False,
            },
            {"name": "Block executables", "enabled": False, "context": None, "stop_on_match": True},
        ]
        return config

    @pytest.fixture
    def app_with_config(self, mock_queue, mock_worker, mock_config):
        """Flask app created WITH a config reference (rules view available)"""
        app = create_app(mock_queue, mock_worker, "test-api-key-12345", config=mock_config)
        app.config["TESTING"] = True
        return app

    @pytest.fixture
    def client_with_config(self, app_with_config):
        return app_with_config.test_client()

    # -- Auth -----------------------------------------------------------

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/jobs",
            "/jobs/test-job-id-123",
            "/rules",
        ],
    )
    def test_missing_key_redirects_to_login(self, client, path):
        """Every dashboard route redirects a human to /login without a key,
        instead of the JSON API's raw 401 -- a browser can't do anything
        useful with a 401 body."""
        response = client.get(path)
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

    def test_missing_key_redirect_preserves_destination_and_query(self, client):
        """?next= on the login redirect should round-trip the original
        path and non-key query params, so a login lands back where the
        user was headed (e.g. still filtered/paginated)."""
        from urllib.parse import parse_qs, urlparse

        response = client.get("/jobs?status=failed&limit=10")

        assert response.status_code == 302
        location = response.headers["Location"]
        next_value = parse_qs(urlparse(location).query)["next"][0]
        assert next_value == "/jobs?status=failed&limit=10"

    def test_wrong_key_redirects_to_login_with_error(self, client):
        """An invalid (not just missing) key should also redirect, with
        ?error=1 so the login form can show a message."""
        response = client.get("/jobs?key=totally-wrong-key")

        assert response.status_code == 302
        assert "error=1" in response.headers["Location"]

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/jobs",
            "/jobs/test-job-id-123",
            "/rules",
        ],
    )
    def test_accepts_query_param_key(self, client, path):
        response = client.get(f"{path}?key=test-api-key-12345")
        assert response.status_code == 200

    # -- Login form -------------------------------------------------------

    def test_login_page_renders_without_a_key(self, client):
        """/login itself must never require a key -- otherwise there's no
        way to ever reach it."""
        response = client.get("/login")

        assert response.status_code == 200
        assert "<form" in response.data.decode()

    def test_login_page_shows_error_message(self, client):
        response = client.get("/login?error=1")

        assert "Invalid API key" in response.data.decode()

    def test_login_page_no_error_message_by_default(self, client):
        response = client.get("/login")

        assert "Invalid API key" not in response.data.decode()

    def test_login_form_posts_to_login_with_next_as_a_hidden_field(self, client):
        """The form posts to /login itself (not a GET straight to the
        destination) -- the key is submitted in the POST body, so it never
        appears in the URL bar or browser history. next is carried as one
        opaque hidden field (path+query together), not split into a field
        per query param, since a POST's body isn't subject to a GET form's
        "action's own query string gets replaced by the submission"
        behavior the way it would be split for a GET-based form."""
        response = client.get("/login?next=%2Fjobs%3Fstatus%3Dfailed")
        body = response.data.decode()

        assert 'method="post"' in body
        assert 'action="/login"' in body
        assert 'name="next" value="/jobs?status=failed"' in body

    def test_login_form_next_value_ignores_key_in_next_query(self, client):
        """A stray ?key= inside next's own query string shouldn't survive
        into the hidden field -- the visible password field is the only
        source of the key on submission."""
        response = client.get("/login?next=%2Fjobs%3Fkey%3Dold-key%26status%3Dfailed")
        body = response.data.decode()

        assert "old-key" not in body
        assert 'name="next" value="/jobs?status=failed"' in body

    def test_login_post_with_correct_key_redirects_to_next_without_key(self, client):
        """A successful login redirects straight to next, with no ?key= in
        the Location -- the whole point of moving auth into the session."""
        response = client.post(
            "/login", data={"key": "test-api-key-12345", "next": "/jobs?status=failed"}
        )

        assert response.status_code == 302
        assert response.headers["Location"] == "/jobs?status=failed"

    def test_login_post_with_wrong_key_redirects_back_with_error(self, client):
        response = client.post("/login", data={"key": "wrong-key", "next": "/jobs"})

        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.startswith("/login")
        assert "error=1" in location

    def test_login_post_sanitizes_next_before_redirecting(self, client):
        """Defense in depth: even though the hidden field is already
        sanitized when rendered, a tampered/crafted next in the POST body
        itself must still be neutered before being used as a redirect
        target, since it's client-controlled input either way."""
        response = client.post(
            "/login",
            data={
                "key": "test-api-key-12345",
                "next": "https://evil.example/steal?key=test-api-key-12345",
            },
        )

        assert response.status_code == 302
        assert response.headers["Location"] == "/steal"

    def test_login_then_resubmit_reaches_destination(self, client):
        """End-to-end: get redirected to login, then submit the form's
        implied request (next path + key) and land on the real page."""
        redirected = client.get("/jobs?status=failed")
        login_page = client.get(redirected.headers["Location"])
        assert login_page.status_code == 200

        response = client.get("/jobs?status=failed&key=test-api-key-12345")
        assert response.status_code == 200

    def test_session_persists_auth_across_requests_without_key(self, client):
        """The whole point of this: authenticate once (either via the
        login POST or a direct ?key= bootstrap link), then subsequent
        requests on the same browser session shouldn't need ?key= repeated
        in every URL."""
        first = client.get("/?key=test-api-key-12345")
        assert first.status_code == 200

        second = client.get("/jobs")
        assert second.status_code == 200

        third = client.get("/rules")
        assert third.status_code == 200

    def test_login_post_establishes_session_for_later_requests(self, client):
        """Same guarantee, but arriving via the login form's POST rather
        than a direct ?key= link."""
        login_response = client.post("/login", data={"key": "test-api-key-12345", "next": "/"})
        assert login_response.status_code == 302

        response = client.get("/jobs")
        assert response.status_code == 200

    def test_no_session_still_redirects_to_login(self, client):
        """A client that never authenticated at all still gets redirected,
        confirming the session check doesn't accidentally allow everyone
        through."""
        response = client.get("/jobs")

        assert response.status_code == 302
        assert response.headers["Location"].startswith("/login")

    def test_rendered_dashboard_links_never_carry_the_key(self, client):
        """The nav, job links, and pagination should no longer embed
        ?key= now that the session covers auth -- that was the entire
        point of this change."""
        client.get("/?key=test-api-key-12345")
        response = client.get("/jobs")
        body = response.data.decode()

        assert "key=test-api-key-12345" not in body

    # -- Overview ---------------------------------------------------------

    def test_overview_renders_stats(self, client, mock_queue):
        mock_queue.get_stats.return_value = {
            "total_jobs": 42,
            "pending": 1,
            "processing": 2,
            "completed": 35,
            "failed": 3,
            "cancelled": 1,
            "average_execution_time": 1.5,
        }
        response = client.get("/?key=test-api-key-12345")

        assert response.status_code == 200
        body = response.data.decode()
        assert "35" in body  # completed count, "Jobs by status"
        assert __version__ in body  # topbar brand, every dashboard page

    def test_overview_rules_summary_names_link_to_rules_page_anchor(
        self, client_with_config, mock_config
    ):
        """Each rule name in the overview's Rules summary table should
        link to that same rule's card on /rules, addressed by the
        1-based index rules.html gives each <details id="rule-N">."""
        response = client_with_config.get("/?key=test-api-key-12345")
        body = response.data.decode()

        assert "/rules#rule-1" in body
        assert "/rules#rule-2" in body

    def test_rules_page_details_have_matching_anchor_ids(self, client_with_config):
        """The /rules page's rule cards must expose the #rule-N ids the
        overview's summary links target."""
        response = client_with_config.get("/rules?key=test-api-key-12345")
        body = response.data.decode()

        assert 'id="rule-1"' in body
        assert 'id="rule-2"' in body

    @pytest.mark.parametrize("path", ["/", "/jobs", "/rules"])
    def test_version_appears_in_topbar_on_every_page(self, client, path):
        """version is injected via a context processor (base.html's shared
        topbar), not threaded through each route's render_template() call
        -- confirm it actually reaches pages other than the overview."""
        response = client.get(f"{path}?key=test-api-key-12345")

        assert __version__ in response.data.decode()

    def test_overview_no_longer_shows_worker_status(self, client, mock_worker):
        """The Status card (Worker/Queue backend/Total jobs/Version) was
        removed from the overview page -- confirm worker.get_status() data
        genuinely isn't rendered anywhere on it anymore."""
        mock_worker.get_status.return_value = {"running": False, "last_job_completed": None}
        response = client.get("/?key=test-api-key-12345")

        assert response.status_code == 200
        assert "Stopped" not in response.data.decode()

    # -- Jobs list ----------------------------------------------------------

    def test_jobs_list_empty_state(self, client, mock_queue):
        mock_queue.list_jobs.return_value = []
        response = client.get("/jobs?key=test-api-key-12345")

        assert response.status_code == 200
        assert "No jobs found" in response.data.decode()

    def test_jobs_list_renders_jobs(self, client, mock_queue):
        mock_queue.list_jobs.return_value = [
            {
                "job_id": "abcdef12-3456-7890-abcd-ef1234567890",
                "status": JobStatus.COMPLETED,
                "context": "nightly",
                "created_at": "2025-01-01T12:00:00",
            },
        ]
        mock_queue.count_jobs.return_value = 1
        response = client.get("/jobs?key=test-api-key-12345")

        assert response.status_code == 200
        body = response.data.decode()
        assert "abcdef12" in body
        assert "nightly" in body
        assert "badge-completed" in body

    def test_jobs_list_passes_status_filter_through(self, client, mock_queue):
        client.get("/jobs?key=test-api-key-12345&status=failed")

        mock_queue.list_jobs.assert_called_once_with(status="failed", limit=50, offset=0)
        mock_queue.count_jobs.assert_called_once_with(status="failed")

    def test_jobs_list_pagination_next_link_when_more_remain(self, client, mock_queue):
        mock_queue.list_jobs.return_value = [
            {"job_id": f"job-{i}", "status": "completed", "context": None, "created_at": "now"}
            for i in range(50)
        ]
        mock_queue.count_jobs.return_value = 200
        response = client.get("/jobs?key=test-api-key-12345&limit=50&offset=0")

        body = response.data.decode()
        assert "Next" in body
        assert "Previous" not in body

    def test_jobs_list_pagination_previous_link_when_offset_positive(self, client, mock_queue):
        mock_queue.list_jobs.return_value = [
            {"job_id": "job-x", "status": "completed", "context": None, "created_at": "now"},
        ]
        mock_queue.count_jobs.return_value = 60
        response = client.get("/jobs?key=test-api-key-12345&limit=50&offset=50")

        assert "Previous" in response.data.decode()

    # -- Job detail -----------------------------------------------------

    def test_job_detail_found(self, client, mock_queue):
        mock_queue.get_job.return_value = {
            "job_id": "test-job-id-123",
            "status": JobStatus.COMPLETED,
            "context": "nightly",
            "hash": None,
            "created_at": "2025-01-01T12:00:00",
            "started_at": "2025-01-01T12:00:01",
            "completed_at": "2025-01-01T12:00:05",
            "result": {"torrents_processed": 10, "actions_executed": 3},
            "error": None,
        }
        response = client.get("/jobs/test-job-id-123?key=test-api-key-12345")

        assert response.status_code == 200
        body = response.data.decode()
        assert "test-job-id-123" in body
        assert "torrents_processed" in body

    def test_job_detail_shows_error(self, client, mock_queue):
        mock_queue.get_job.return_value = {
            "job_id": "test-job-id-123",
            "status": JobStatus.FAILED,
            "context": None,
            "hash": None,
            "created_at": "2025-01-01T12:00:00",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": "Traceback: something broke",
        }
        response = client.get("/jobs/test-job-id-123?key=test-api-key-12345")

        assert "something broke" in response.data.decode()

    def test_job_detail_long_traceback_shows_summary_with_collapsed_full_trace(
        self, client, mock_queue
    ):
        """A multi-exception traceback should render the compact summary
        by default, with the full trace tucked behind a <details> toggle
        rather than dumped inline."""
        full_traceback = (
            "Traceback (most recent call last):\n"
            '  File "urllib3/connection.py", line 204, in _new_conn\n'
            "socket.gaierror: [Errno -2] Name or service not known\n"
            "\n"
            "During handling of the above exception, another exception occurred:\n"
            "\n"
            "Traceback (most recent call last):\n"
            '  File "qbt_rules/worker.py", line 161, in _process_job\n'
            "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent server\n"
            "  • Fix: Check that qBittorrent is running"
        )
        mock_queue.get_job.return_value = {
            "job_id": "test-job-id-123",
            "status": JobStatus.FAILED,
            "context": None,
            "hash": None,
            "created_at": "2025-01-01T12:00:00",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": full_traceback,
        }
        response = client.get("/jobs/test-job-id-123?key=test-api-key-12345")
        body = response.data.decode()

        assert "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent server" in body
        assert "<details>" in body
        assert "Show full traceback" in body
        assert "socket.gaierror" in body  # present, but inside the collapsed <details> block

    def test_job_detail_short_error_has_no_details_toggle(self, client, mock_queue):
        """When the summary IS the whole error (no traceback framing to
        strip), there's nothing extra to hide -- no <details> toggle."""
        mock_queue.get_job.return_value = {
            "job_id": "test-job-id-123",
            "status": JobStatus.FAILED,
            "context": None,
            "hash": None,
            "created_at": "2025-01-01T12:00:00",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": "ValueError: bad input",
        }
        response = client.get("/jobs/test-job-id-123?key=test-api-key-12345")
        body = response.data.decode()

        assert "ValueError: bad input" in body
        assert "<details>" not in body

    def test_job_detail_not_found(self, client, mock_queue):
        mock_queue.get_job.return_value = None
        response = client.get("/jobs/nonexistent?key=test-api-key-12345")

        assert response.status_code == 404
        assert "not found" in response.data.decode().lower()

    # -- Rules --------------------------------------------------------------

    def test_rules_unavailable_without_config(self, client):
        """create_app() without config= -- the shared `app` fixture's case"""
        response = client.get("/rules?key=test-api-key-12345")

        assert response.status_code == 200
        assert "unavailable" in response.data.decode().lower()

    def test_rules_renders_when_config_provided(self, client_with_config, mock_config):
        response = client_with_config.get("/rules?key=test-api-key-12345")

        assert response.status_code == 200
        body = response.data.decode()
        assert "Delete old torrents" in body
        assert "Block executables" in body
        mock_config.get_rules.assert_called_once()

    def test_rules_empty_state(self, client_with_config, mock_config):
        mock_config.get_rules.return_value = []
        response = client_with_config.get("/rules?key=test-api-key-12345")

        assert response.status_code == 200
        assert "No rules configured" in response.data.decode()

    def test_rules_condition_tree_renders_all_sibling_gates(self, client_with_config, mock_config):
        """A conditions dict can carry more than one of all/any/none as
        sibling keys at once -- engine.py ANDs every key present, e.g. a
        rule with both `all:` and `none:` at the top level. The tree
        render must show every present gate, not just the first one it
        finds (regression: originally picked one via an if/elif chain,
        silently dropping the others)."""
        mock_config.get_rules.return_value = [
            {
                "name": "Multi-gate rule",
                "enabled": True,
                "context": None,
                "stop_on_match": False,
                "conditions": {
                    "all": [{"field": "info.state", "operator": "in", "value": ["stalledDL"]}],
                    "none": [
                        {"any": [{"field": "info.category", "operator": "in", "value": ["keep"]}]}
                    ],
                },
                "actions": [{"type": "stop"}],
            }
        ]
        response = client_with_config.get("/rules?key=test-api-key-12345")
        body = response.data.decode()

        assert "tnode gate op-all" in body
        assert "tnode gate op-none" in body
        assert "tnode gate op-any" in body
        assert "info.category" in body

    # -- Access log filtering -------------------------------------------


class TestMetricsRoutes:
    """Test the Prometheus /metrics endpoint and its HTTP request hooks"""

    @pytest.fixture
    def app_with_metrics(self, mock_queue, mock_worker):
        """Flask app created WITH metrics enabled -- mirrors legacy_cli.py's real
        startup order: metrics.init(enabled=True) before create_app()"""
        from qbt_rules import metrics

        metrics.init(enabled=True)

        app = create_app(
            mock_queue,
            mock_worker,
            "test-api-key-12345",
            metrics_config={
                "enabled": True,
                "multiproc_dir": os.environ["PROMETHEUS_MULTIPROC_DIR"],
            },
        )
        app.config["TESTING"] = True
        return app

    @pytest.fixture
    def client_with_metrics(self, app_with_metrics):
        return app_with_metrics.test_client()

    def test_metrics_route_not_registered_when_disabled(self, client):
        """The shared `client` fixture's app was created without
        metrics_config -- /metrics shouldn't exist at all, not just 401"""
        response = client.get("/metrics?key=test-api-key-12345")
        assert response.status_code == 404

    def test_metrics_requires_api_key(self, client_with_metrics):
        response = client_with_metrics.get("/metrics")
        assert response.status_code == 401

    def test_metrics_accepts_query_param_key(self, client_with_metrics):
        response = client_with_metrics.get("/metrics?key=test-api-key-12345")
        assert response.status_code == 200

    def test_metrics_content_type_is_prometheus_exposition_format(self, client_with_metrics):
        response = client_with_metrics.get("/metrics?key=test-api-key-12345")
        assert response.content_type.startswith("text/plain")

    def test_metrics_includes_queue_and_worker_state_gauges(
        self, client_with_metrics, mock_queue, mock_worker
    ):
        mock_queue.get_queue_depth.return_value = 5
        mock_worker.get_status.return_value = {"running": True, "last_job_completed": None}

        response = client_with_metrics.get("/metrics?key=test-api-key-12345")
        body = response.data.decode()

        assert 'qbt_rules_queue_depth{backend="SQLiteQueue"} 5.0' in body
        assert "qbt_rules_worker_running 1.0" in body

    def test_metrics_scheduler_entries_from_dashboard_config(self, mock_queue, mock_worker, mocker):
        """schedule_entry_count is read from the same dashboard_config
        global the /rules route already uses, not a separate
        param -- confirm it reflects config.schedule's length"""
        from qbt_rules import metrics

        metrics.init(enabled=True)

        mock_config = mocker.MagicMock()
        mock_config.schedule = [
            {"cron": "*/30 * * * *", "context": "cron"},
            {"cron": "0 3 * * *", "context": "nightly"},
        ]

        app = create_app(
            mock_queue,
            mock_worker,
            "test-api-key-12345",
            config=mock_config,
            metrics_config={
                "enabled": True,
                "multiproc_dir": os.environ["PROMETHEUS_MULTIPROC_DIR"],
            },
        )
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.get("/metrics?key=test-api-key-12345")
        assert "qbt_rules_scheduler_entries 2.0" in response.data.decode()

    def test_http_requests_recorded_for_other_routes(self, client_with_metrics):
        client_with_metrics.get("/login")
        response = client_with_metrics.get("/metrics?key=test-api-key-12345")
        body = response.data.decode()

        assert 'qbt_rules_http_requests_total{endpoint="login",method="GET",status="200"}' in body

    def test_metrics_endpoint_itself_excluded_from_http_request_metrics(self, client_with_metrics):
        """Scraping /metrics shouldn't create a self-referential
        'metrics_endpoint'-labeled entry in its own output"""
        client_with_metrics.get("/metrics?key=test-api-key-12345")
        response = client_with_metrics.get("/metrics?key=test-api-key-12345")
        body = response.data.decode()

        assert 'endpoint="metrics_endpoint"' not in body
