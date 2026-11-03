"""
Tests for qbt_rules.legacy_cli module (v0.4.0 client-server architecture)
"""

import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from qbt_rules.config import PLACEHOLDER_API_KEY, ConfigError
from qbt_rules.config import load_config as load_settings
from qbt_rules.config_loader import Config
from qbt_rules.legacy_cli import (
    apply_cli_overrides,
    cancel_job_command,
    get_client_config,
    get_integrations_config,
    get_logging_config,
    get_metrics_config,
    get_notifications_config,
    get_qbittorrent_config,
    get_queue_config,
    get_server_config,
    job_status_command,
    list_jobs_command,
    run_client_mode,
    run_server_mode,
    stats_command,
    wait_for_job,
)

# No config file and no rules.yml: every setting from its default or the given environment
MISSING = Path("/nonexistent/qbt-rules/config.yaml")


def make_config(args=None, environ=None, path=MISSING):
    """The running configuration legacy_cli.main() would build from these flags"""
    settings = load_settings(path, environ=environ or {})
    return Config(apply_cli_overrides(args or Namespace(), settings))


def with_config(args):
    """(args, the configuration built from them), for run_client_mode(*...)"""
    return args, make_config(args)


class TestApplyCliOverrides:
    """A CLI flag beats every other source of its setting"""

    def test_no_flags_changes_nothing(self):
        settings = load_settings(MISSING, environ={})
        assert apply_cli_overrides(Namespace(), settings) is settings

    def test_flags_win_and_are_named_as_the_source(self):
        args = Namespace(
            server_host="127.0.0.1",
            server_port=8080,
            server_api_key="cli-key",
            server_workers=2,
            client_server_url="http://remote:5000",
            client_api_key="client-key",
            queue_backend="redis",
            queue_sqlite_path="/srv/q.db",
            queue_redis_url="redis://r:6379/2",
            log_level="DEBUG",
            trace=True,
            dry_run=True,
        )
        env = {"QBT_RULES_LISTEN_PORT": "9000", "QBT_RULES_SERVER_API_KEY": "env-key"}
        s = make_config(args, env).settings
        assert (s.host, s.port, s.workers) == ("127.0.0.1", 8080, 2)
        assert s.api_key.reveal() == "cli-key"
        assert s.client_api_key.reveal() == "client-key"
        assert (s.client_server_url, s.queue_backend) == ("http://remote:5000", "redis")
        assert s.sqlite_path == Path("/srv/q.db")
        assert s.redis_url.reveal() == "redis://r:6379/2"
        assert (s.log_level, s.trace_mode, s.dry_run) == ("DEBUG", True, True)
        assert s.sources["listen.port"] == "--server-port"
        assert s.sources["dry_run"] == "--dry-run"
        assert s.problems == ()

    def test_false_flags_leave_the_settings(self):
        args = Namespace(trace=False, dry_run=False)
        s = make_config(args, {"QBT_RULES_DRY_RUN": "true"}).settings
        assert (s.dry_run, s.trace_mode) == (True, False)


class TestGetConfigDicts:
    """The plain dicts the legacy server, worker and engine take"""

    def test_logging(self):
        config = make_config(environ={"QBT_RULES_LOGGING_FILE": "qbt.log"})
        assert get_logging_config(Namespace(serve=True), config) == {
            "level": "INFO",
            "file": Path("/var/lib/qbt-rules/qbt.log"),
            "trace_mode": False,
            "http_access": False,
            "client_mode": False,
            "max_bytes": 10 * 1024 * 1024,
            "backup_count": 5,
        }
        assert get_logging_config(Namespace(), make_config())["file"] is None
        assert get_logging_config(Namespace(), make_config())["client_mode"] is True

    def test_qbittorrent_password_is_revealed_here(self):
        env = {"QBT_RULES_QBITTORRENT_PASSWORD": "pw", "QBT_RULES_QBITTORRENT_HOST": "http://q"}
        assert get_qbittorrent_config(Namespace(), make_config(environ=env)) == {
            "host": "http://q",
            "username": "admin",
            "password": "pw",
        }

    def test_server(self):
        assert get_server_config(Namespace(), make_config()) == {
            "host": "0.0.0.0",  # noqa: S104  the default
            "port": 5000,
            "api_key": "",
            "workers": 1,
            "editor_enabled": True,
        }
        env = {"QBT_RULES_SERVER_EDITOR_ENABLED": "false"}
        assert get_server_config(Namespace(), make_config(environ=env))["editor_enabled"] is False

    def test_queue(self):
        assert get_queue_config(Namespace(), make_config()) == {
            "backend": "sqlite",
            "sqlite_path": "/var/lib/qbt-rules/qbt-rules.db",
            "redis_url": "redis://localhost:6379/0",
            "cleanup_after": 7 * 86400,
        }
        env = {"QBT_RULES_QUEUE_CLEANUP_AFTER": "0"}
        assert get_queue_config(Namespace(), make_config(environ=env))["cleanup_after"] is None

    def test_notifications(self):
        assert get_notifications_config(Namespace(), make_config()) == {
            "webhook_url": None,
            "service": "generic",
        }

    def test_integrations(self):
        env = {
            "QBT_RULES_INTEGRATIONS_SONARR_URL": "http://sonarr:8989",
            "QBT_RULES_INTEGRATIONS_SONARR_API_KEY_FILE": "/dev/null",
        }
        assert get_integrations_config(Namespace(), make_config(environ=env)) == {
            "sonarr": {"url": "http://sonarr:8989", "api_key": None},
            "radarr": {"url": None, "api_key": None},
            "trackie": {"url": None, "max_age": 3 * 3600, "timeout": 10.0},
        }

    def test_metrics(self):
        assert get_metrics_config(Namespace(), make_config()) == {
            "enabled": False,
            "multiproc_dir": "/tmp/qbt-rules-metrics",  # noqa: S108  the default
        }

    @pytest.mark.parametrize(
        ("environ", "expected"),
        [
            ({}, ""),
            ({"QBT_RULES_SERVER_API_KEY": "server"}, "server"),
            ({"QBT_RULES_SERVER_API_KEY": "server", "QBT_RULES_CLIENT_API_KEY": "own"}, "own"),
            (
                {
                    "QBT_RULES_SERVER_API_KEY": "server",
                    "QBT_RULES_CLIENT_API_KEY": PLACEHOLDER_API_KEY,
                },
                "server",
            ),
        ],
    )
    def test_client_key_falls_back_to_the_server_key(self, environ, expected):
        # The usual client is `docker exec <container> qbt-rules ...`, beside the server's key
        client = get_client_config(Namespace(), make_config(environ=environ))
        assert client == {"server_url": "http://localhost:5000", "api_key": expected}


class TestRunServerMode:
    """run_server_mode(): the FastAPI app under uvicorn (server.serve)"""

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.server.serve")
    def test_serves_the_settings_with_the_flags_applied(self, mock_serve, mock_logger):
        args = Namespace(
            serve=True,
            server_host="127.0.0.1",
            server_port=5001,
            server_api_key="test-key",
            server_workers=1,
        )
        config_obj = make_config(args)

        run_server_mode(args, config_obj, {"http_access": False})

        [settings] = mock_serve.call_args.args
        assert settings is config_obj.settings
        assert (settings.host, settings.port, settings.api_key.reveal()) == (
            "127.0.0.1",
            5001,
            "test-key",
        )

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.server.serve")
    def test_refuses_more_than_one_worker_from_the_flag(self, mock_serve, mock_logger):
        """config.py refuses server.workers > 1; --server-workers skips that check"""
        args = Namespace(server_workers=2)

        with pytest.raises(ConfigError, match="one process"):
            run_server_mode(args, make_config(args), {"http_access": False})
        assert not mock_serve.called

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.server.serve")
    def test_starts_without_api_key(self, mock_serve, mock_logger):
        """With no API key the server still starts (the image's smoke test runs it with no
        configuration): the problem is logged, and /api/health reports it"""
        run_server_mode(Namespace(), make_config(), {"http_access": False})

        assert mock_serve.called
        logged = " ".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
        assert "server.api_key is not set" in logged

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.server.serve")
    def test_warns_about_the_port_alias(self, mock_serve, mock_logger):
        """QBT_RULES_SERVER_PORT works, but the image's healthcheck reads QBT_RULES_LISTEN_PORT"""
        env = {"QBT_RULES_SERVER_PORT": "8080", "QBT_RULES_SERVER_API_KEY": "k"}

        run_server_mode(Namespace(), make_config(environ=env), {"http_access": False})

        assert mock_serve.call_args.args[0].port == 8080
        assert "set QBT_RULES_LISTEN_PORT instead" in mock_logger.warning.call_args.args[0]

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.server.serve")
    @patch("qbt_rules.metrics.init")
    def test_metrics_get_a_clean_multiprocess_directory(
        self, mock_init, mock_serve, mock_logger, tmp_path, monkeypatch
    ):
        multiproc = tmp_path / "metrics"
        multiproc.mkdir()
        (multiproc / "counter_1.db").write_bytes(b"stale")
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
        env = {
            "QBT_RULES_METRICS_ENABLED": "true",
            "QBT_RULES_METRICS_MULTIPROC_DIR": str(multiproc),
        }

        run_server_mode(Namespace(), make_config(environ=env), {"http_access": False})

        assert not (multiproc / "counter_1.db").exists()
        assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(multiproc)
        mock_init.assert_called_once_with(enabled=True)


class TestRunClientMode:
    """Test run_client_mode() function"""

    @staticmethod
    def _args(**overrides):
        values = dict(
            context="manual",
            hash=None,
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
            dry_run=False,
        )
        values.update(overrides)
        return Namespace(**values)

    @staticmethod
    def _accepted(job):
        response = Mock(status_code=202)
        response.json.return_value = {
            "job_id": "job-123",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00Z",
            **job,
        }
        return response

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_dry_run_flag_is_sent_to_server(self, mock_post, mock_logger):
        """--dry-run used to be dropped, so the job ran for real"""
        mock_post.return_value = self._accepted({"dry_run": True})

        run_client_mode(*with_config(self._args(dry_run=True)))

        assert mock_post.call_args[1]["params"]["dry_run"] == "true"

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_no_dry_run_param_without_flag(self, mock_post, mock_logger):
        mock_post.return_value = self._accepted({"dry_run": False})

        run_client_mode(*with_config(self._args()))

        assert "dry_run" not in mock_post.call_args[1]["params"]

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.delete")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_cancels_job_when_server_ignores_dry_run(self, mock_post, mock_delete, mock_logger):
        """An older server drops the parameter and would run for real: cancel and fail"""
        mock_post.return_value = self._accepted({})  # no dry_run field at all
        mock_delete.return_value = Mock(status_code=200)

        with pytest.raises(SystemExit) as exc:
            run_client_mode(*with_config(self._args(dry_run=True, wait=True)))

        assert exc.value.code == 1
        assert mock_delete.call_args[0][0] == "http://localhost:5000/api/jobs/job-123"

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_submits_job_successfully(self, mock_post, mock_validate, mock_logger):
        """Should submit job to server successfully"""
        # Mock hash validation
        mock_validate.return_value = "abc123"

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "job_id": "job-123",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_post.return_value = mock_response

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        run_client_mode(args, config_obj)

        # Verify hash was validated
        mock_validate.assert_called_once_with("abc123")

        # Verify request was made
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:5000/api/execute"
        assert call_args[1]["params"]["context"] == "adhoc-run"
        assert call_args[1]["params"]["hash"] == "abc123"
        assert call_args[1]["params"]["key"] == "test-key"

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_connection_error(self, mock_post, mock_validate, mock_exit, mock_logger):
        """Should handle connection errors gracefully"""
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError()
        mock_exit.side_effect = SystemExit(1)
        mock_validate.return_value = "abc123"

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)
        # Verify error was logged
        assert mock_logger.error.called

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_exits_without_api_key(self, mock_exit, mock_logger):
        """Should exit if client API key not provided"""
        mock_exit.side_effect = SystemExit(1)

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key=None,  # No API key
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)
        # Verify error was logged
        assert mock_logger.error.called

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_auth_error(self, mock_post, mock_validate, mock_exit, mock_logger):
        """Should handle authentication errors"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_post.return_value = mock_response
        mock_exit.side_effect = SystemExit(1)
        mock_validate.return_value = "abc123"

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="wrong-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.wait_for_job")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_waits_for_job_when_requested(self, mock_post, mock_wait, mock_validate, mock_logger):
        """Should wait for job completion when --wait flag is set"""
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "job_id": "job-123",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_post.return_value = mock_response
        mock_validate.return_value = "abc123"

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=True,  # Wait for completion
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        run_client_mode(args, config_obj)

        # Verify wait_for_job was called
        mock_wait.assert_called_once_with("http://localhost:5000", "test-key", "job-123")

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_timeout_error(self, mock_post, mock_validate, mock_exit, mock_logger):
        """Should handle timeout errors"""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()
        mock_exit.side_effect = SystemExit(1)
        mock_validate.return_value = "abc123"

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_server_error(self, mock_post, mock_validate, mock_exit, mock_logger):
        """Should handle server errors"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response
        mock_exit.side_effect = SystemExit(1)
        mock_validate.return_value = "abc123"

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_no_context_or_hash(self, mock_post, mock_logger):
        """Should handle missing context and hash"""
        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "job_id": "job-123",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00Z",
        }
        mock_post.return_value = mock_response

        args = Namespace(
            wait=False, client_server_url="http://localhost:5000", client_api_key="test-key"
        )
        config_obj = make_config(args)

        run_client_mode(args, config_obj)

        # Verify request was made with None values
        call_args = mock_post.call_args
        assert call_args[1]["params"]["context"] is None
        assert call_args[1]["params"]["hash"] is None

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_validates_torrent_hash_when_provided(
        self, mock_post, mock_validate, mock_exit, mock_logger
    ):
        """Should validate torrent hash when provided"""
        # Simulate validation error
        mock_validate.side_effect = ValueError("Invalid hash")
        mock_exit.side_effect = SystemExit(1)

        args = Namespace(
            context="adhoc-run",
            hash="invalid-hash",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        # Should have attempted validation
        mock_validate.assert_called_once_with("invalid-hash")
        # Should have exited
        mock_exit.assert_called_once_with(1)


class TestWaitForJob:
    """Test wait_for_job() function"""

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.time.sleep")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_waits_for_job_completion(self, mock_get, mock_sleep, mock_logger):
        """Should poll until job completes"""
        # First call: processing, second call: completed
        mock_response1 = Mock()
        mock_response1.status_code = 200
        mock_response1.json.return_value = {"status": "processing"}

        mock_response2 = Mock()
        mock_response2.status_code = 200
        mock_response2.json.return_value = {
            "status": "completed",
            "result": {"torrents_processed": 10, "rules_matched": 5, "actions_executed": 3},
        }

        mock_get.side_effect = [mock_response1, mock_response2]

        wait_for_job("http://localhost:5000", "test-key", "job-123")

        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.time.sleep")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_shows_error_on_failure(self, mock_get, mock_sleep, mock_exit, mock_logger):
        """Should show error when job fails"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "failed", "error": "Test error"}
        mock_get.return_value = mock_response
        mock_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            wait_for_job("http://localhost:5000", "test-key", "job-123")

        # Should not retry for failed job
        assert mock_get.call_count == 1
        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.time.sleep")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_cancelled_job(self, mock_get, mock_sleep, mock_exit, mock_logger):
        """Should handle cancelled jobs"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "cancelled"}
        mock_get.return_value = mock_response
        mock_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            wait_for_job("http://localhost:5000", "test-key", "job-123")

        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.time.sleep")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_polling_error(self, mock_get, mock_sleep, mock_exit, mock_logger):
        """Should handle errors during polling"""
        mock_get.side_effect = Exception("Network error")
        mock_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            wait_for_job("http://localhost:5000", "test-key", "job-123")

        mock_exit.assert_called_once_with(1)


class TestListJobsCommand:
    """Test list_jobs_command() function"""

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_lists_jobs_successfully(self, mock_get, mock_cli_ui):
        """Should list jobs from server"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 2,
            "jobs": [
                {
                    "job_id": "job-1",
                    "status": "completed",
                    "context": "adhoc-run",
                    "created_at": "2024-01-01T00:00:00Z",
                },
                {
                    "job_id": "job-2",
                    "status": "pending",
                    "context": "automatic",
                    "created_at": "2024-01-01T01:00:00Z",
                },
            ],
        }
        mock_get.return_value = mock_response

        args = Namespace(
            status_filter=None,
            limit=20,
            output="table",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        list_jobs_command(args, config_obj)

        # Verify request was made
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "http://localhost:5000/api/jobs" in call_args[0][0]

        # Verify table was rendered with the expected columns and rows
        mock_cli_ui.print_table.assert_called_once()
        _, kwargs = mock_cli_ui.print_table.call_args
        assert kwargs["headers"] == ["Job ID", "Status", "Context", "Created"]
        assert kwargs["rows"] == [
            ["job-1", "completed", "adhoc-run", "2024-01-01T00:00:00Z"],
            ["job-2", "pending", "automatic", "2024-01-01T01:00:00Z"],
        ]

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_lists_jobs_as_json(self, mock_get, mock_cli_ui):
        """Should print the raw API response as JSON when --output json is set"""
        mock_response = Mock()
        mock_response.status_code = 200
        response_data = {
            "total": 1,
            "jobs": [
                {
                    "job_id": "job-1",
                    "status": "completed",
                    "context": None,
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ],
        }
        mock_response.json.return_value = response_data
        mock_get.return_value = mock_response

        args = Namespace(
            status_filter=None,
            limit=20,
            output="json",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        list_jobs_command(args, config_obj)

        mock_cli_ui.print_json.assert_called_once_with(response_data)
        mock_cli_ui.print_table.assert_not_called()

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_no_jobs(self, mock_get, mock_cli_ui):
        """Should handle empty job list"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 0, "jobs": []}
        mock_get.return_value = mock_response

        args = Namespace(
            output="table", client_server_url="http://localhost:5000", client_api_key="test-key"
        )
        config_obj = make_config(args)

        list_jobs_command(args, config_obj)

        mock_cli_ui.print_message.assert_called_once_with("No jobs found")
        mock_cli_ui.print_table.assert_not_called()

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_error(self, mock_get, mock_exit, mock_logger):
        """Should handle errors"""
        mock_get.side_effect = Exception("Network error")

        args = Namespace(client_server_url="http://localhost:5000", client_api_key="test-key")
        config_obj = make_config(args)

        list_jobs_command(args, config_obj)

        mock_exit.assert_called_once_with(1)


class TestJobStatusCommand:
    """Test job_status_command() function"""

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_gets_job_status(self, mock_get, mock_cli_ui):
        """Should get job status from server"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job_id": "job-123",
            "status": "completed",
            "context": "adhoc-run",
            "hash": "abc123",
            "created_at": "2024-01-01T00:00:00Z",
            "started_at": "2024-01-01T00:00:01Z",
            "completed_at": "2024-01-01T00:00:10Z",
            "result": {"torrents_processed": 10},
        }
        mock_get.return_value = mock_response

        args = Namespace(
            job_status="job-123",
            output="table",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        # Verify request was made
        mock_get.assert_called_once()

        # Verify job details and result sections were rendered
        assert mock_cli_ui.print_kv_section.call_count == 2
        details_call, result_call = mock_cli_ui.print_kv_section.call_args_list
        assert details_call.args[0] == "Job Details:"
        assert ("Job ID", "job-123") in details_call.args[1]
        assert ("Context", "adhoc-run") in details_call.args[1]
        assert result_call.args[0] == "Result:"
        assert result_call.args[1] == [("torrents_processed", 10)]

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_gets_job_status_as_json(self, mock_get, mock_cli_ui):
        """Should print the raw API response as JSON when --output json is set"""
        mock_response = Mock()
        mock_response.status_code = 200
        job_data = {"job_id": "job-123", "status": "completed"}
        mock_response.json.return_value = job_data
        mock_get.return_value = mock_response

        args = Namespace(
            job_status="job-123",
            output="json",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        mock_cli_ui.print_json.assert_called_once_with(job_data)
        mock_cli_ui.print_kv_section.assert_not_called()

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_job_not_found(self, mock_get, mock_logger):
        """Should handle job not found"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        args = Namespace(
            job_status="nonexistent",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        # Verify error was logged
        assert any("Job not found" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_error(self, mock_get, mock_exit, mock_logger):
        """Should handle errors"""
        mock_get.side_effect = Exception("Network error")

        args = Namespace(
            job_status="job-123",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        mock_exit.assert_called_once_with(1)

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_displays_job_with_error(self, mock_get, mock_cli_ui):
        """Should display job with error"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job_id": "job-123",
            "status": "failed",
            "context": "adhoc-run",
            "created_at": "2024-01-01T00:00:00Z",
            "started_at": "2024-01-01T00:00:01Z",
            "completed_at": "2024-01-01T00:00:10Z",
            "error": "Connection timeout",
        }
        mock_get.return_value = mock_response

        args = Namespace(
            job_status="job-123",
            output="table",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        # Verify the error detail was printed
        mock_cli_ui.print_message.assert_called_once()
        assert "Connection timeout" in mock_cli_ui.print_message.call_args.args[0]


class TestCancelJobCommand:
    """Test cancel_job_command() function"""

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_cancels_job(self, mock_delete, mock_cli_ui):
        """Should cancel job on server"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_delete.return_value = mock_response

        args = Namespace(
            cancel_job_id="job-123",
            output="table",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        # Verify request was made
        mock_delete.assert_called_once()
        # Verify success was announced
        mock_cli_ui.print_message.assert_called_once_with("✓ Job cancelled: job-123")

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_cancels_job_as_json(self, mock_delete, mock_cli_ui):
        """Should print the raw API response as JSON when --output json is set"""
        mock_response = Mock()
        mock_response.status_code = 200
        response_data = {
            "job_id": "job-123",
            "status": "cancelled",
            "message": "Job cancelled successfully",
        }
        mock_response.json.return_value = response_data
        mock_delete.return_value = mock_response

        args = Namespace(
            cancel_job_id="job-123",
            output="json",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        mock_cli_ui.print_json.assert_called_once_with(response_data)
        mock_cli_ui.print_message.assert_not_called()

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_handles_cannot_cancel(self, mock_delete, mock_logger):
        """Should handle cannot cancel error"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Job already completed"}
        mock_delete.return_value = mock_response

        args = Namespace(
            cancel_job_id="job-123",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        # Verify error was logged
        assert any("Cannot cancel job" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_handles_job_not_found(self, mock_delete, mock_logger):
        """Should handle job not found"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_delete.return_value = mock_response

        args = Namespace(
            cancel_job_id="nonexistent",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        # Verify error was logged
        assert any("Job not found" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_handles_error(self, mock_delete, mock_exit, mock_logger):
        """Should handle errors"""
        mock_delete.side_effect = Exception("Network error")

        args = Namespace(
            cancel_job_id="job-123",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        mock_exit.assert_called_once_with(1)


class TestStatsCommand:
    """Test stats_command() function"""

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_gets_stats(self, mock_get, mock_cli_ui):
        """Should get server stats"""
        mock_response = Mock()
        mock_response.status_code = 200
        stats_data = {
            "jobs": {
                "total": 100,
                "pending": 5,
                "processing": 1,
                "completed": 90,
                "failed": 3,
                "cancelled": 1,
            },
            "performance": {"average_execution_time": 2.5},
            "queue": {"backend": "SQLite", "depth": 5},
            "worker": {"status": "idle", "last_job_completed": "2024-01-01T00:00:00Z"},
        }
        mock_response.json.return_value = stats_data
        mock_get.return_value = mock_response

        args = Namespace(
            output="table", client_server_url="http://localhost:5000", client_api_key="test-key"
        )
        config_obj = make_config(args)

        stats_command(args, config_obj)

        # Verify request was made
        mock_get.assert_called_once()

        # Verify all four sections were rendered
        assert mock_cli_ui.print_kv_section.call_count == 4
        titles = [c.args[0] for c in mock_cli_ui.print_kv_section.call_args_list]
        assert titles == ["Jobs:", "Performance:", "Queue:", "Worker:"]
        jobs_call = mock_cli_ui.print_kv_section.call_args_list[0]
        assert ("Total", 100) in jobs_call.args[1]

    @patch("qbt_rules.legacy_cli.cli_ui")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_gets_stats_as_json(self, mock_get, mock_cli_ui):
        """Should print the raw API response as JSON when --output json is set"""
        mock_response = Mock()
        mock_response.status_code = 200
        stats_data = {
            "jobs": {
                "total": 100,
                "pending": 5,
                "processing": 1,
                "completed": 90,
                "failed": 3,
                "cancelled": 1,
            },
            "performance": {"average_execution_time": 2.5},
            "queue": {"backend": "SQLite", "depth": 5},
            "worker": {"status": "idle", "last_job_completed": "2024-01-01T00:00:00Z"},
        }
        mock_response.json.return_value = stats_data
        mock_get.return_value = mock_response

        args = Namespace(
            output="json", client_server_url="http://localhost:5000", client_api_key="test-key"
        )
        config_obj = make_config(args)

        stats_command(args, config_obj)

        mock_cli_ui.print_json.assert_called_once_with(stats_data)
        mock_cli_ui.print_kv_section.assert_not_called()

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_server_error(self, mock_get, mock_logger):
        """Should handle server errors"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        args = Namespace(client_server_url="http://localhost:5000", client_api_key="test-key")
        config_obj = make_config(args)

        stats_command(args, config_obj)

        # Verify error was logged
        assert any("Server error" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_error(self, mock_get, mock_exit, mock_logger):
        """Should handle errors"""
        mock_get.side_effect = Exception("Network error")

        args = Namespace(client_server_url="http://localhost:5000", client_api_key="test-key")
        config_obj = make_config(args)

        stats_command(args, config_obj)

        mock_exit.assert_called_once_with(1)


class TestRunClientModeEdgeCases:
    """Test edge cases in run_client_mode() function"""

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.validate_torrent_hash")
    @patch("qbt_rules.legacy_cli.requests.post")
    def test_handles_generic_exception(self, mock_post, mock_validate, mock_exit, mock_logger):
        """Should handle generic exceptions"""
        mock_validate.return_value = "abc123"
        mock_post.side_effect = RuntimeError("Unexpected error")
        mock_exit.side_effect = SystemExit(1)

        args = Namespace(
            context="adhoc-run",
            hash="abc123",
            wait=False,
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        with pytest.raises(SystemExit):
            run_client_mode(args, config_obj)

        mock_exit.assert_called_once_with(1)
        # Verify error was logged
        assert any("Unexpected error" in str(call) for call in mock_logger.error.call_args_list)


class TestWaitForJobEdgeCases:
    """Test edge cases in wait_for_job() function"""

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.sys.exit")
    @patch("qbt_rules.legacy_cli.time.sleep")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_handles_timeout(self, mock_get, mock_sleep, mock_exit, mock_logger):
        """Should timeout if job doesn't complete within max_wait"""
        # Always return processing status
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "processing"}
        mock_get.return_value = mock_response
        mock_exit.side_effect = SystemExit(1)

        with pytest.raises(SystemExit):
            wait_for_job("http://localhost:5000", "test-key", "job-123")

        # Should have called many times (polling)
        assert mock_get.call_count > 10
        mock_exit.assert_called_once_with(1)
        # Verify timeout error was logged
        assert any("did not complete" in str(call) for call in mock_logger.error.call_args_list)


class TestCommandEdgeCases:
    """Test edge cases in command functions"""

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_list_jobs_server_error(self, mock_get, mock_logger):
        """Should handle server errors in list_jobs_command"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        args = Namespace(client_server_url="http://localhost:5000", client_api_key="test-key")
        config_obj = make_config(args)

        list_jobs_command(args, config_obj)

        # Verify server error was logged
        assert any("Server error" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.get")
    def test_job_status_server_error(self, mock_get, mock_logger):
        """Should handle server errors in job_status_command"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        args = Namespace(
            job_status="job-123",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        job_status_command(args, config_obj)

        # Verify server error was logged
        assert any("Server error" in str(call) for call in mock_logger.error.call_args_list)

    @patch("qbt_rules.legacy_cli.logger")
    @patch("qbt_rules.legacy_cli.requests.delete")
    def test_cancel_job_server_error(self, mock_delete, mock_logger):
        """Should handle server errors in cancel_job_command"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_delete.return_value = mock_response

        args = Namespace(
            cancel_job_id="job-123",
            client_server_url="http://localhost:5000",
            client_api_key="test-key",
        )
        config_obj = make_config(args)

        cancel_job_command(args, config_obj)

        # Verify server error was logged
        assert any("Server error" in str(call) for call in mock_logger.error.call_args_list)


class TestMain:
    """Test main() entry point function"""

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--serve"])
    @patch("qbt_rules.legacy_cli.run_server_mode")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_server_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_run_server,
    ):
        """Should run in server mode when --serve flag provided"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_run_server.called
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "serve"])
    @patch("qbt_rules.legacy_cli.run_server_mode")
    @patch("qbt_rules.arguments.handle_utility_args", return_value=None)
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_serve_is_a_synonym_of_dash_dash_serve(
        self,
        mock_exit,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_run_server,
    ):
        """`qbt-rules serve` (the image's CMD) runs the server, as --serve does"""
        mock_load_config.return_value = Mock(config={}, config_dir=Path("/state"))

        from qbt_rules.legacy_cli import main

        main()

        assert mock_run_server.called
        assert mock_run_server.call_args.args[0].serve is True
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--list-jobs"])
    @patch("qbt_rules.legacy_cli.list_jobs_command")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_list_jobs_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_list_jobs,
    ):
        """Should run list_jobs command"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_list_jobs.called
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--job-status", "job-123"])
    @patch("qbt_rules.legacy_cli.job_status_command")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_job_status_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_job_status,
    ):
        """Should run job_status command"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_job_status.called
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--cancel-job", "job-123"])
    @patch("qbt_rules.legacy_cli.cancel_job_command")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_cancel_job_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_cancel_job,
    ):
        """Should run cancel_job command"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_cancel_job.called
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--stats"])
    @patch("qbt_rules.legacy_cli.stats_command")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_stats_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_stats,
    ):
        """Should run stats command"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_stats.called
        mock_exit.assert_called_with(0)

    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--context", "adhoc-run"])
    @patch("qbt_rules.legacy_cli.run_client_mode")
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_client_mode(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        mock_run_client,
    ):
        """Should run in client mode by default"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        mock_handle_utility.return_value = None

        from qbt_rules.legacy_cli import main

        main()

        assert mock_run_client.called
        mock_exit.assert_called_with(0)

    @pytest.mark.parametrize("exit_code", [0, 1])
    @patch("qbt_rules.legacy_cli.sys.argv", ["qbt-rules", "--validate"])
    @patch("qbt_rules.arguments.handle_utility_args")
    @patch("qbt_rules.legacy_cli.get_logger")
    @patch("qbt_rules.legacy_cli.setup_logging")
    @patch("qbt_rules.legacy_cli.load_config")
    @patch("qbt_rules.arguments.process_args")
    @patch("qbt_rules.legacy_cli.sys.exit")
    def test_main_utility_mode_propagates_exit_status(
        self,
        mock_exit,
        mock_process_args,
        mock_load_config,
        mock_setup_logging,
        mock_get_logger,
        mock_handle_utility,
        exit_code,
    ):
        """Should handle utility arguments like --validate"""
        mock_process_args.return_value = "/config"

        mock_config = Mock(config={}, config_dir=Path("/config"))
        mock_load_config.return_value = mock_config

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Utility mode exits early
        mock_handle_utility.return_value = exit_code

        def terminate(code):
            raise SystemExit(code)

        mock_exit.side_effect = terminate

        from qbt_rules.legacy_cli import main

        with pytest.raises(SystemExit) as error:
            main()

        assert error.value.code == exit_code
        mock_exit.assert_called_once_with(exit_code)
