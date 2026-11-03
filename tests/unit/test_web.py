"""The dashboard (web.py): the pages, the login form, /static and /metrics, through TestClient.

The JSON API's tests are tests/unit/test_api_routes.py and tests/golden. TODO(4e): /metrics
moves onto interpose's Registry.
"""

import dataclasses
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from interpose.secret import Secret

from qbt_rules import __version__, api, metrics, web
from qbt_rules.config import Config, load_config
from qbt_rules.config_loader import Config as RulesConfig
from qbt_rules.queue_manager import JobStatus, QueueManager
from qbt_rules.web import _summarize_error, _timeago, relative_url, sanitize_next

API_KEY = "test-api-key-12345"
KEY = {"X-API-Key": API_KEY}

JOB: dict[str, Any] = {
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


class StubWorker:
    def __init__(self) -> None:
        self.status: dict[str, Any] = {
            "running": True,
            "last_job_completed": "2025-01-01T12:00:00",
        }

    def run(self, stop: Any) -> None:
        stop.wait()

    def is_alive(self) -> bool:
        return True

    def get_status(self) -> dict[str, Any]:
        return self.status


@pytest.fixture
def queue() -> MagicMock:
    queue = MagicMock()
    queue.__class__.__name__ = "SQLiteQueue"
    queue.get_job.return_value = dict(JOB)
    queue.list_jobs.return_value = []
    queue.count_jobs.return_value = 0
    queue.get_queue_depth.return_value = 0
    queue.get_stats.return_value = {
        "total_jobs": 0,
        "pending": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "average_execution_time": None,
    }
    return queue


@pytest.fixture
def worker() -> StubWorker:
    return StubWorker()


@pytest.fixture
def rules() -> MagicMock:
    """The running rules config, for /rules, the editor page and the scheduler gauge"""
    config = MagicMock()
    config.get_rules.return_value = [
        {"id": "delete-old", "meta": {"description": "Delete old torrents"}, "context": "nightly"},
        {"id": "block-exe", "name": "Block executables", "enabled": False, "context": None},
    ]
    config.schedule = [
        {"cron": "*/30 * * * *", "context": "cron"},
        {"cron": "0 3 * * *", "context": "nightly"},
    ]
    return config


@pytest.fixture
def settings(tmp_path: Path) -> Config:
    environ = {"QBT_RULES_SERVER_API_KEY": API_KEY, "QBT_RULES_STATE_DIR": str(tmp_path)}
    return load_config(tmp_path / "missing.yaml", environ=environ)


def make_client(
    settings: Config,
    queue: MagicMock,
    worker: StubWorker,
    rules: MagicMock | None = None,
    root_path: str = "",
    **changes: Any,
) -> TestClient:
    services = api.Services(
        queue=cast(QueueManager, queue), worker=worker, rules=cast(RulesConfig | None, rules)
    )
    if changes:
        settings = dataclasses.replace(settings, **changes)
    app = api.create_app(settings, services)
    return TestClient(app, follow_redirects=False, root_path=root_path)


@pytest.fixture
def client(settings: Config, queue: MagicMock, worker: StubWorker) -> TestClient:
    """No rules config: the rules pages say so"""
    return make_client(settings, queue, worker)


@pytest.fixture
def client_with_rules(
    settings: Config, queue: MagicMock, worker: StubWorker, rules: MagicMock
) -> TestClient:
    return make_client(settings, queue, worker, rules)


def csrf_of(page: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


def log_in(client: TestClient, next_url: str = "/", key: str = API_KEY) -> httpx2.Response:
    """Load the login form, then post it with its CSRF token"""
    form = client.get("/login")
    return client.post(
        "/login", data={"key": key, "next": next_url, "csrf_token": csrf_of(form.text)}
    )


def resolve(response: httpx2.Response) -> str:
    """Where a redirect goes, as the browser resolves its relative Location"""
    return urljoin(str(response.request.url), response.headers["Location"])


def location_path(response: httpx2.Response) -> str:
    """The resolved Location's path and query"""
    url = urlsplit(resolve(response))
    return url.path + (f"?{url.query}" if url.query else "")


def links(body: str) -> list[str]:
    return re.findall(r'(?:href|src|action)="([^"]*)"', body)


PAGES = ["/", "/jobs", "/jobs/test-job-id-123", "/rules", "/rules/edit"]


# -- Links -----------------------------------------------------------------------------------------


class TestRelativeUrl:
    @pytest.mark.parametrize(
        ("here", "there", "expected"),
        [
            ("/", "/", "./"),
            ("/", "/jobs", "./jobs"),
            ("/jobs", "/", "./"),
            ("/jobs/abc", "/jobs", "../jobs"),
            ("/jobs/abc", "/jobs/def", "./def"),
            ("/rules/edit", "/api/rules/source", "../api/rules/source"),
            ("/qbt/jobs", "/qbt", "../qbt"),
            ("/qbt/jobs", "/qbt/", "./"),
            ("/qbt/rules/edit", "/qbt/static/editor.js", "../static/editor.js"),
            ("/a/b", "/x:y", "../x:y"),
        ],
    )
    def test_resolves_back_to_the_target(self, here: str, there: str, expected: str) -> None:
        assert relative_url(here, there) == expected
        # Under any prefix the browser sees, it still lands on the target
        for prefix in ("", "/qbt", "/a/b"):
            resolved = urlsplit(urljoin(f"http://h{prefix}{here}", expected)).path
            assert resolved == f"{prefix}{there}"

    def test_query(self) -> None:
        assert relative_url("/login", "/jobs", "status=failed") == "./jobs?status=failed"


class TestSanitizeNext:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "/"),
            ("", "/"),
            ("/jobs?status=failed", "/jobs?status=failed"),
            ("jobs", "/jobs"),
            ("https://evil.example/steal?key=x", "/steal"),
            ("//evil.example/steal", "/steal"),
            ("///evil.example", "/evil.example"),
            ("/\\evil.example", "/evil.example"),
            ("\\\\evil.example/x", "/evil.example/x"),
            ("javascript:alert(1)", "/alert(1)"),
            ("/jobs?key=old&status=failed", "/jobs?status=failed"),
            ("/jobs#frag", "/jobs"),
        ],
    )
    def test_same_origin_paths_only(self, value: str | None, expected: str) -> None:
        assert sanitize_next(value) == expected


# -- Auth and the login form -----------------------------------------------------------------------


class TestLogin:
    @pytest.mark.parametrize("path", PAGES)
    def test_no_session_redirects_to_login(self, client: TestClient, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 302
        assert location_path(response) == "/login?" + urlencode({"next": path})

    def test_next_keeps_the_query_but_not_the_key(self, client: TestClient) -> None:
        response = client.get("/jobs?status=failed&limit=10", headers={"X-API-Key": ""})
        query = parse_qs(urlsplit(resolve(response)).query)
        assert query["next"] == ["/jobs?status=failed&limit=10"]
        assert "error" not in query

    def test_a_wrong_key_redirects_with_an_error(self, client: TestClient) -> None:
        response = client.get("/jobs?key=totally-wrong-key&status=failed")
        query = parse_qs(urlsplit(resolve(response)).query)
        assert query == {"next": ["/jobs?status=failed"], "error": ["1"]}
        assert "totally-wrong-key" not in response.headers["Location"]

    def test_the_form_never_needs_a_key(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "<form" in response.text
        assert "Invalid API key" not in response.text

    @pytest.mark.parametrize(
        ("error", "message"),
        [("1", "Invalid API key."), ("csrf", "The sign-in form expired"), ("x", "Invalid API")],
    )
    def test_the_form_shows_the_error(self, client: TestClient, error: str, message: str) -> None:
        assert message in client.get(f"/login?error={error}").text

    def test_the_form_posts_the_key_with_next_and_a_csrf_token(self, client: TestClient) -> None:
        body = client.get("/login?next=%2Fjobs%3Fkey%3Dold-key%26status%3Dfailed").text
        assert 'method="post"' in body
        assert 'action="./login"' in body
        assert 'name="next" value="/jobs?status=failed"' in body
        assert 'type="password" id="key" name="key"' in body
        assert csrf_of(body)
        assert "old-key" not in body

    def test_the_form_sanitises_next(self, client: TestClient) -> None:
        body = client.get("/login?next=https%3A%2F%2Fevil.example%2Fsteal").text
        assert 'name="next" value="/steal"' in body
        assert "evil.example" not in body

    def test_logging_in_goes_to_next(self, client: TestClient) -> None:
        response = log_in(client, "/jobs?status=failed")
        assert response.status_code == 302
        assert response.headers["Location"] == "./jobs?status=failed"
        assert client.get("/jobs").status_code == 200
        assert client.get("/rules").status_code == 200

    def test_logging_in_sanitises_next_again(self, client: TestClient) -> None:
        """The hidden field comes back as client input: a crafted one stays on the site"""
        for crafted in ("https://evil.example/steal?key=x", "//evil.example/steal", "/\\evil"):
            response = log_in(client, crafted)
            assert urlsplit(resolve(response)).netloc == "testserver", crafted
        assert location_path(log_in(client, "https://evil.example/steal?key=x")) == "/steal"

    def test_a_wrong_key_is_no_session(self, client: TestClient) -> None:
        response = log_in(client, "/jobs", key="wrong-key")
        assert response.status_code == 302
        assert parse_qs(urlsplit(resolve(response)).query) == {"next": ["/jobs"], "error": ["1"]}
        assert "Set-Cookie" not in response.headers
        assert client.get("/jobs").status_code == 302

    def test_logging_in_starts_a_new_session(self, client: TestClient) -> None:
        before = csrf_of(client.get("/login").text)
        log_in(client)
        page = client.get("/login").text
        assert csrf_of(page) != before

    def test_the_session_cookie(self, client: TestClient) -> None:
        cookie = log_in(client).headers["Set-Cookie"]
        assert cookie.startswith("qbt_rules_session=")
        assert "httponly" in cookie.lower()
        assert "samesite=lax" in cookie.lower()

    def test_no_api_key_configured(
        self, settings: Config, queue: MagicMock, worker: StubWorker
    ) -> None:
        """4b's behaviour: the pages send you to the form, which says what to set"""
        client = make_client(settings, queue, worker, api_key=Secret(""))
        assert location_path(client.get("/")).startswith("/login?")
        page = client.get("/login")
        assert page.status_code == 200
        assert "No API key is configured on the server" in page.text
        # No key logs in, not even an empty one
        assert client.get("/?key=").status_code == 302
        assert log_in(client, key="").status_code == 302
        assert client.get("/").status_code == 302


class TestLoginCsrf:
    def test_a_post_without_the_token_is_refused(self, client: TestClient) -> None:
        client.get("/login")
        response = client.post("/login", data={"key": API_KEY, "next": "/jobs"})
        assert response.status_code == 302
        query = parse_qs(urlsplit(resolve(response)).query)
        assert query == {"next": ["/jobs"], "error": ["csrf"]}
        assert client.get("/jobs").status_code == 302

    def test_a_wrong_token_is_refused(self, client: TestClient) -> None:
        client.get("/login")
        data = {"key": API_KEY, "next": "/", "csrf_token": "forged"}
        assert "error=csrf" in client.post("/login", data=data).headers["Location"]
        assert client.get("/").status_code == 302

    def test_another_sessions_token_is_refused(
        self, client: TestClient, settings: Config, queue: MagicMock, worker: StubWorker
    ) -> None:
        """A cross-site form can't carry this browser's token: it only knows its own"""
        attacker = make_client(settings, queue, worker)
        token = csrf_of(attacker.get("/login").text)
        client.get("/login")
        data = {"key": API_KEY, "next": "/", "csrf_token": token}
        assert "error=csrf" in client.post("/login", data=data).headers["Location"]

    def test_a_post_with_no_session_at_all_is_refused(self, client: TestClient) -> None:
        response = client.post("/login", data={"key": API_KEY, "csrf_token": ""})
        assert "error=csrf" in response.headers["Location"]


class TestKeyInTheUrl:
    def test_a_key_logs_in_and_redirects_without_it(self, client: TestClient) -> None:
        """0.10.x served the page with the key left in the address bar and the history"""
        response = client.get(f"/jobs?status=failed&key={API_KEY}&limit=10")
        assert response.status_code == 302
        assert response.headers["Location"] == "./jobs?status=failed&limit=10"
        assert API_KEY not in response.headers["Location"]
        assert response.headers["Set-Cookie"].startswith("qbt_rules_session=")
        followed = client.get(resolve(response))
        assert followed.status_code == 200
        assert client.get("/api/rules/source").status_code != 401  # the API's session too

    @pytest.mark.parametrize("path", PAGES)
    def test_on_every_page(self, client_with_rules: TestClient, path: str) -> None:
        response = client_with_rules.get(f"{path}?key={API_KEY}")
        assert response.status_code == 302
        assert location_path(response) == path
        assert client_with_rules.get(path).status_code in (200, 404)

    def test_the_header_logs_in_and_serves_the_page(self, client: TestClient) -> None:
        assert client.get("/jobs", headers=KEY).status_code == 200
        assert client.get("/rules").status_code == 200

    def test_a_wrong_header_is_a_wrong_key(self, client: TestClient) -> None:
        response = client.get("/jobs", headers={"X-API-Key": "wrong"})
        assert "error=1" in response.headers["Location"]

    def test_pages_never_link_with_the_key(self, client: TestClient, queue: MagicMock) -> None:
        queue.list_jobs.return_value = [
            {"job_id": "j-1", "status": "completed", "context": None, "created_at": "now"}
        ]
        queue.count_jobs.return_value = 200
        client.get(f"/?key={API_KEY}")
        assert all("key=" not in link for link in links(client.get("/jobs").text))


# -- The pages -------------------------------------------------------------------------------------


class TestDashboardRoutes:
    @pytest.fixture(autouse=True)
    def _logged_in(self, client: TestClient, client_with_rules: TestClient) -> None:
        log_in(client)
        log_in(client_with_rules)

    @pytest.mark.parametrize("path", ["/", "/jobs", "/rules", "/rules/edit"])
    def test_version_in_the_topbar(self, client: TestClient, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert __version__ in response.text

    def test_overview_renders_stats(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_stats.return_value = {
            "total_jobs": 42,
            "pending": 1,
            "processing": 2,
            "completed": 35,
            "failed": 3,
            "cancelled": 1,
            "average_execution_time": 1.5,
        }
        assert "35" in client.get("/").text
        queue.list_jobs.assert_called_once_with(limit=5)

    def test_overview_rules_summary_links_to_the_rule(self, client_with_rules: TestClient) -> None:
        body = client_with_rules.get("/").text
        assert 'href="./rules#rule-1"' in body
        assert 'href="./rules#rule-2"' in body
        assert "Delete old torrents" in body

    def test_overview_no_longer_shows_worker_status(
        self, client: TestClient, worker: StubWorker
    ) -> None:
        worker.status = {"running": False, "last_job_completed": None}
        assert "Stopped" not in client.get("/").text

    def test_jobs_list_empty_state(self, client: TestClient) -> None:
        assert "No jobs found" in client.get("/jobs").text

    def test_jobs_list_renders_jobs(self, client: TestClient, queue: MagicMock) -> None:
        queue.list_jobs.return_value = [
            {
                "job_id": "abcdef12-3456-7890-abcd-ef1234567890",
                "status": JobStatus.COMPLETED,
                "context": "nightly",
                "created_at": datetime.now(UTC) - timedelta(hours=2),
            },
        ]
        queue.count_jobs.return_value = 1
        body = client.get("/jobs").text
        assert 'href="./jobs/abcdef12-3456-7890-abcd-ef1234567890"' in body
        assert "nightly" in body
        assert "badge-completed" in body
        assert "2 hours ago" in body  # the timeago filter

    def test_jobs_list_passes_the_filter_through(
        self, client: TestClient, queue: MagicMock
    ) -> None:
        client.get("/jobs?status=failed")
        queue.list_jobs.assert_called_once_with(status="failed", limit=50, offset=0)
        queue.count_jobs.assert_called_once_with(status="failed")

    @pytest.mark.parametrize(
        ("query", "limit", "offset"),
        [("limit=abc&offset=-3", 50, 0), ("limit=0", 50, 0), ("limit=10&offset=20", 10, 20)],
    )
    def test_jobs_list_bad_numbers_fall_back(
        self, client: TestClient, queue: MagicMock, query: str, limit: int, offset: int
    ) -> None:
        """Flask answered a 500 for limit=abc"""
        assert client.get(f"/jobs?{query}").status_code == 200
        queue.list_jobs.assert_called_once_with(status=None, limit=limit, offset=offset)

    def test_jobs_pagination(self, client: TestClient, queue: MagicMock) -> None:
        queue.list_jobs.return_value = [
            {"job_id": f"job-{i}", "status": "completed", "context": None, "created_at": "now"}
            for i in range(50)
        ]
        queue.count_jobs.return_value = 200
        first = client.get("/jobs?status=completed").text
        assert 'href="./jobs?status=completed&amp;limit=50&amp;offset=50">Next' in first
        assert "Previous" not in first
        later = client.get("/jobs?limit=50&offset=50").text
        assert 'href="./jobs?limit=50&amp;offset=0">&larr; Previous' in later

    def test_job_detail(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_job.return_value = {
            **JOB,
            "status": JobStatus.COMPLETED,
            "result": {"torrents_processed": 10, "actions_executed": 3},
        }
        response = client.get("/jobs/test-job-id-123")
        assert response.status_code == 200
        assert "torrents_processed" in response.text
        assert 'href="../jobs"' in response.text  # back to the list, relative
        queue.get_job.assert_called_with("test-job-id-123")

    def test_job_detail_long_traceback(self, client: TestClient, queue: MagicMock) -> None:
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
        queue.get_job.return_value = {**JOB, "status": JobStatus.FAILED, "error": full_traceback}
        body = client.get("/jobs/test-job-id-123").text
        assert "qbt_rules.errors.ConnectionError: Cannot reach qBittorrent server" in body
        assert "<details>" in body
        assert "Show full traceback" in body
        assert "socket.gaierror" in body

    def test_job_detail_short_error(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_job.return_value = {**JOB, "status": JobStatus.FAILED, "error": "ValueError: x"}
        body = client.get("/jobs/test-job-id-123").text
        assert "ValueError: x" in body
        assert "<details>" not in body

    def test_job_detail_not_found(self, client: TestClient, queue: MagicMock) -> None:
        queue.get_job.return_value = None
        response = client.get("/jobs/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.text.lower()

    def test_rules_unavailable_without_config(self, client: TestClient) -> None:
        assert "unavailable" in client.get("/rules").text.lower()

    def test_rules(self, client_with_rules: TestClient, rules: MagicMock) -> None:
        body = client_with_rules.get("/rules").text
        assert "Delete old torrents" in body
        assert "Block executables" in body
        assert 'id="rule-1"' in body
        assert 'id="rule-2"' in body
        assert 'href="./rules/edit"' in body

    def test_rules_empty_state(self, client_with_rules: TestClient, rules: MagicMock) -> None:
        rules.get_rules.return_value = []
        assert "No rules configured" in client_with_rules.get("/rules").text

    def test_rules_condition_tree_renders_all_sibling_gates(
        self, client_with_rules: TestClient, rules: MagicMock
    ) -> None:
        """all/any/none can be siblings (engine.py ANDs them): every one is drawn"""
        rules.get_rules.return_value = [
            {
                "name": "Multi-gate rule",
                "enabled": True,
                "conditions": {
                    "all": [{"field": "info.state", "operator": "in", "value": ["stalledDL"]}],
                    "none": [
                        {"any": [{"field": "info.category", "operator": "in", "value": ["keep"]}]}
                    ],
                },
                "actions": [{"type": "stop"}],
            }
        ]
        body = client_with_rules.get("/rules").text
        assert "tnode gate op-all" in body
        assert "tnode gate op-none" in body
        assert "tnode gate op-any" in body
        assert "info.category" in body

    def test_starting_is_503(self, settings: Config) -> None:
        """Before the lifespan has built the services (never served by uvicorn)"""
        client = TestClient(api.create_app(settings), follow_redirects=False)
        for path in PAGES:
            assert client.get(path).status_code == 503, path
        assert client.get("/login").status_code == 200


class TestEditorRoutes:
    @pytest.fixture(autouse=True)
    def _logged_in(self, client_with_rules: TestClient) -> None:
        log_in(client_with_rules)

    def editor_config(self, page: str) -> dict[str, str]:
        block = page.split("window.QBT_EDITOR = ", 1)[1].split("</script>", 1)[0]
        return dict(re.findall(r'(\w+): "([^"]*)"', block))

    def test_the_editor_page(self, client_with_rules: TestClient) -> None:
        body = client_with_rules.get("/rules/edit").text
        config = self.editor_config(body)
        assert config["csrfToken"]
        assert config["source"] == "../api/rules/source"
        assert config["acePath"] == "../static/vendor/ace"
        assert f'src="../static/editor.js?v={__version__}"' in body
        assert f'src="../static/vendor/ace/ace.js?v={__version__}"' in body

    def test_every_url_it_builds_reaches_its_route(self, client_with_rules: TestClient) -> None:
        """Resolved like the browser does, against the page: each lands on a JSON route"""
        config = self.editor_config(client_with_rules.get("/rules/edit").text)
        base = "http://testserver/rules/edit"
        expected = {
            "source": "/api/rules/source",
            "validate": "/api/rules/validate",
            "history": "/api/rules/history",
            "catalog": "/api/rules/catalog",
            "config": "/api/config/source",
            "execute": "/api/execute",
            "jobsApi": "/api/jobs",
            "jobsPage": "/jobs",
            "acePath": "/static/vendor/ace",
        }
        for name, path in expected.items():
            assert urlsplit(urljoin(base, config[name])).path == path, name

    def test_the_editor_page_without_a_rules_config(self, client: TestClient) -> None:
        log_in(client)
        body = client.get("/rules/edit").text
        assert "QBT_EDITOR" not in body
        assert "editor.js" not in body

    def test_csrf_token_matches_the_session(self, client_with_rules: TestClient) -> None:
        """The editor's token is the one the API checks on writes"""
        token = self.editor_config(client_with_rules.get("/rules/edit").text)["csrfToken"]
        response = client_with_rules.post(
            "/api/rules/validate", json={"content": "rules: []\n"}, headers={"X-CSRF-Token": token}
        )
        assert response.status_code != 403
        response = client_with_rules.post("/api/rules/validate", json={"content": "rules: []\n"})
        assert response.status_code == 403


# -- Static files ----------------------------------------------------------------------------------


class TestStatic:
    @pytest.mark.parametrize(
        ("path", "content_type"),
        [
            ("/static/editor.js", "text/javascript; charset=utf-8"),
            ("/static/vendor/ace/ace.js", "text/javascript; charset=utf-8"),
            ("/static/vendor/ace/mode-yaml.js", "text/javascript; charset=utf-8"),
        ],
    )
    def test_served_without_login(self, client: TestClient, path: str, content_type: str) -> None:
        response = client.get(f"{path}?v={__version__}")
        assert response.status_code == 200
        assert response.headers["content-type"] == content_type
        assert response.headers["cache-control"] == "no-cache"
        assert response.content == (web.STATIC_DIR / path.removeprefix("/static/")).read_bytes()

    def test_revalidated_by_etag(self, client: TestClient) -> None:
        first = client.get("/static/editor.js")
        again = client.get("/static/editor.js", headers={"If-None-Match": first.headers["etag"]})
        assert again.status_code == 304

    def test_missing_is_a_json_404(self, client: TestClient) -> None:
        response = client.get("/static/nope.js")
        assert response.status_code == 404
        assert response.json() == {"error": "Not Found", "message": "Endpoint not found"}

    def test_no_escaping_the_directory(self, client: TestClient) -> None:
        assert client.get("/static/..%2F__init__.py").status_code == 404
        assert client.get("/static/../web.py").status_code == 404

    def test_every_asset_a_page_references_is_cache_busted(
        self, client_with_rules: TestClient
    ) -> None:
        log_in(client_with_rules)
        body = client_with_rules.get("/rules/edit").text
        assets = [link for link in links(body) if "static/" in link]
        assert len(assets) == 7
        for asset in assets:
            assert asset.endswith(f"?v={__version__}"), asset
            url = urljoin("http://testserver/rules/edit", asset)
            assert client_with_rules.get(url).status_code == 200, asset


# -- Behind a path prefix --------------------------------------------------------------------------


class TestRootPath:
    """Behind a reverse proxy at /qbt: with root_path set (uvicorn --root-path), or a proxy that
    strips the prefix and tells the app nothing. Every link is relative, so both work."""

    @pytest.fixture
    def prefixed(
        self, settings: Config, queue: MagicMock, worker: StubWorker, rules: MagicMock
    ) -> TestClient:
        return make_client(settings, queue, worker, rules, root_path="/qbt")

    def test_the_login_round_trip_stays_under_the_prefix(self, prefixed: TestClient) -> None:
        response = prefixed.get("/qbt/jobs?status=failed")
        assert location_path(response) == "/qbt/login?" + urlencode({"next": "/jobs?status=failed"})
        form = prefixed.get(resolve(response))
        assert 'action="./login"' in form.text
        response = prefixed.post(
            "/qbt/login",
            data={"key": API_KEY, "next": "/jobs?status=failed", "csrf_token": csrf_of(form.text)},
        )
        assert location_path(response) == "/qbt/jobs?status=failed"
        assert prefixed.get(resolve(response)).status_code == 200

    def test_the_key_redirect_stays_under_the_prefix(self, prefixed: TestClient) -> None:
        response = prefixed.get(f"/qbt/rules/edit?key={API_KEY}")
        assert location_path(response) == "/qbt/rules/edit"

    @pytest.mark.parametrize("page", ["/", "/jobs", "/rules", "/rules/edit"])
    def test_every_link_resolves_under_the_prefix(self, prefixed: TestClient, page: str) -> None:
        prefixed.get(f"/qbt/?key={API_KEY}")
        url = f"http://testserver/qbt{page}"
        body = prefixed.get(url).text
        found = links(body)
        assert found
        for link in found:
            assert not link.startswith(("/", "http")), link
            target = urljoin(url, link)
            assert urlsplit(target).path.startswith("/qbt/"), (page, link)
            if "static/" in link or link.startswith("./rules") or "jobs" in link:
                assert prefixed.get(target.split("#")[0]).status_code == 200, (page, link)

    def test_templates_render_with_url_for(self, prefixed: TestClient) -> None:
        """url_for under a root path: the absolute URL carries /qbt, the link is relative"""
        prefixed.get(f"/qbt/?key={API_KEY}")
        body = prefixed.get("/qbt/rules/edit").text
        assert f'src="../static/editor.js?v={__version__}"' in body
        assert "/qbt/" not in body  # nothing absolute: the same page works when stripped

    def test_a_stripping_proxy(self, client_with_rules: TestClient) -> None:
        """The app sees /rules/edit; the browser is at /qbt/rules/edit. Same relative links"""
        client_with_rules.get(f"/?key={API_KEY}")
        body = client_with_rules.get("/rules/edit").text
        for link in links(body):
            assert urlsplit(urljoin("https://proxy/qbt/rules/edit", link)).path.startswith("/qbt/")


# -- /metrics --------------------------------------------------------------------------------------


class TestMetricsRoutes:
    @pytest.fixture
    def client_with_metrics(
        self, settings: Config, queue: MagicMock, worker: StubWorker, rules: MagicMock
    ) -> TestClient:
        metrics.init(enabled=True)
        return make_client(settings, queue, worker, rules, metrics_enabled=True)

    def test_not_there_when_disabled(self, client: TestClient) -> None:
        response = client.get(f"/metrics?key={API_KEY}")
        assert response.status_code == 404
        assert response.json()["error"] == "Not Found"

    def test_needs_the_key(self, client_with_metrics: TestClient) -> None:
        assert client_with_metrics.get("/metrics").status_code == 401
        log_in(client_with_metrics)
        assert client_with_metrics.get("/metrics").status_code == 401  # not the session

    def test_no_api_key_configured(
        self, settings: Config, queue: MagicMock, worker: StubWorker
    ) -> None:
        metrics.init(enabled=True)
        client = make_client(settings, queue, worker, metrics_enabled=True, api_key=Secret(""))
        assert client.get("/metrics", headers={"X-API-Key": ""}).status_code == 503

    def test_key_as_query_or_header(self, client_with_metrics: TestClient) -> None:
        assert client_with_metrics.get(f"/metrics?key={API_KEY}").status_code == 200
        assert client_with_metrics.get("/metrics", headers=KEY).status_code == 200

    def test_content_type_unchanged(self, client_with_metrics: TestClient) -> None:
        """Flask's, charset and all (#28 item 4 is 4e's)"""
        response = client_with_metrics.get("/metrics", headers=KEY)
        assert response.headers["content-type"] == f"{metrics.content_type()}; charset=utf-8"

    def test_state_gauges(
        self, client_with_metrics: TestClient, queue: MagicMock, worker: StubWorker
    ) -> None:
        queue.get_queue_depth.return_value = 5
        worker.status = {"running": True, "last_job_completed": None}
        body = client_with_metrics.get("/metrics", headers=KEY).text
        assert 'qbt_rules_queue_depth{backend="SQLiteQueue"} 5.0' in body
        assert "qbt_rules_worker_running 1.0" in body
        assert "qbt_rules_scheduler_entries 2.0" in body

    def test_http_requests_are_counted_by_route_name(self, client_with_metrics: TestClient) -> None:
        client_with_metrics.get("/login")
        log_in(client_with_metrics)
        client_with_metrics.get("/jobs")
        client_with_metrics.get("/static/editor.js")
        client_with_metrics.get("/metrics", headers=KEY)
        body = client_with_metrics.get("/metrics", headers=KEY).text
        for endpoint, method, status in [
            ("login", "GET", 200),
            ("login", "POST", 302),
            ("dashboard_jobs", "GET", 200),
            ("static", "GET", 200),
        ]:
            line = f'endpoint="{endpoint}",method="{method}",status="{status}"'
            assert f"qbt_rules_http_requests_total{{{line}}}" in body
        assert 'endpoint="metrics_endpoint"' not in body


class TestSummarizeError:
    """Test _summarize_error() -- extracts the final exception's summary
    from a full traceback, for the job detail dashboard page."""

    def test_empty_string_returns_empty(self) -> None:
        assert _summarize_error("") == ""

    def test_plain_message_with_no_traceback_returned_as_is(self) -> None:
        assert _summarize_error("Something just broke") == "Something just broke"

    def test_single_exception_line(self) -> None:
        assert _summarize_error("ValueError: bad input") == "ValueError: bad input"

    def test_chained_exceptions_returns_only_the_final_one(self) -> None:
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

    def test_multiline_custom_error_message_kept_intact(self) -> None:
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

    def test_none_returns_empty_string(self) -> None:

        assert _timeago(None) == ""

    def test_invalid_string_returned_unchanged(self) -> None:

        assert _timeago("not a timestamp") == "not a timestamp"

    def test_just_now(self) -> None:

        assert _timeago(datetime.now(UTC)) == "just now"

    def test_minutes_ago(self) -> None:
        from datetime import timedelta

        dt = datetime.now(UTC) - timedelta(minutes=5)
        assert _timeago(dt) == "5 minutes ago"

    def test_singular_unit_has_no_trailing_s(self) -> None:
        from datetime import timedelta

        dt = datetime.now(UTC) - timedelta(hours=1)
        assert _timeago(dt) == "1 hour ago"

    def test_days_ago(self) -> None:
        from datetime import timedelta

        dt = datetime.now(UTC) - timedelta(days=4)
        assert _timeago(dt) == "4 days ago"

    def test_iso_string_is_parsed(self) -> None:
        """Some unit-test fixtures elsewhere in this file pass created_at
        as a plain ISO string rather than a real datetime -- the filter
        must handle both, matching what real job dicts vs. test mocks
        actually carry."""
        from datetime import timedelta

        dt = datetime.now(UTC) - timedelta(days=2)
        assert _timeago(dt.isoformat()) == "2 days ago"

    def test_naive_datetime_treated_as_utc(self) -> None:
        from datetime import timedelta

        dt = (datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None)
        assert _timeago(dt) == "3 hours ago"
