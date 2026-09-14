"""Tests for the notify action in engine.py (ActionExecutor._execute_notify)."""

import logging
from unittest.mock import Mock, patch

import pytest

from qbt_rules.engine import ActionExecutor


def _mock_response(status_code=200):
    response = Mock()
    response.status_code = status_code
    if status_code >= 400:
        import requests
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Error"
        )
    else:
        response.raise_for_status.return_value = None
    return response


class TestNotifyPayloadShapes:
    """Each service sends a different payload shape to the same requests.post call."""

    @patch('qbt_rules.engine.requests.post')
    def test_discord_payload(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
                'message': 'Torrent {name} matched',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://discord.com/api/webhooks/x/y',
            timeout=10,
            json={'content': 'Torrent Example.Torrent.1080p matched'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_slack_payload(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'slack',
                'url': 'https://hooks.slack.com/services/x',
                'message': 'Torrent {name} matched',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://hooks.slack.com/services/x',
            timeout=10,
            json={'text': 'Torrent Example.Torrent.1080p matched'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_ntfy_payload_is_raw_text_not_json(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'ntfy',
                'url': 'https://ntfy.sh/my-topic',
                'message': 'Torrent {name} matched',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://ntfy.sh/my-topic',
            timeout=10,
            data=b'Torrent Example.Torrent.1080p matched',
        )

    @patch('qbt_rules.engine.requests.post')
    def test_generic_default_payload(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'generic',
                'url': 'https://example.com/webhook',
                'message': 'Torrent {name} matched',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'message': 'Torrent Example.Torrent.1080p matched'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_generic_body_override_is_not_templated(self, mock_post, mock_api, sample_torrent):
        """body: is a manual escape hatch -- sent as-is, literal {name} stays literal."""
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'generic',
                'url': 'https://example.com/webhook',
                'body': {'custom_field': 'literal {name} not substituted', 'priority': 5},
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'custom_field': 'literal {name} not substituted', 'priority': 5},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_unknown_service_fails_without_http_call(self, mock_post, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'pushover',
                'url': 'https://example.com',
                'message': 'hi',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_post.assert_not_called()


class TestNotifyTemplating:
    """Message templating, including the tags cleanup."""

    @patch('qbt_rules.engine.requests.post')
    def test_tags_are_cleaned_up_not_raw_csv(self, mock_post, mock_api):
        """info.tags is qBittorrent's raw comma-separated string ('hd,new') --
        the template should see a friendly ', '-joined list instead."""
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'hash': 'h1', 'name': 'Test.Torrent', 'tags': 'hd,new', 'ratio': 1.0}

        action = {
            'type': 'notify',
            'params': {
                'service': 'generic',
                'url': 'https://example.com/webhook',
                'message': 'Tags: {tags}',
            },
        }
        success, skipped = executor.execute(torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'message': 'Tags: hd, new'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_empty_tags_render_as_empty_string(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'generic',
                'url': 'https://example.com/webhook',
                'message': 'Tags: [{tags}]',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'message': 'Tags: []'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_missing_template_field_skips_without_crashing(self, mock_post, mock_api, sample_torrent, caplog):
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
                'message': 'Torrent {nonexistent_field} matched',
            },
        }
        with caplog.at_level(logging.WARNING):
            success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_post.assert_not_called()
        assert "unknown field" in caplog.text

    @patch('qbt_rules.engine.requests.post')
    def test_no_message_and_not_generic_body_fails(self, mock_post, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_post.assert_not_called()


class TestNotifyConfigDefaults:
    """Falling back to notifications_config when params omit url/service."""

    @patch('qbt_rules.engine.requests.post')
    def test_uses_default_webhook_url_when_params_omit_url(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(
            mock_api, dry_run=False,
            notifications_config={'webhook_url': 'https://example.com/default', 'service': 'generic'}
        )

        action = {'type': 'notify', 'params': {'message': 'Torrent {name} matched'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_post.assert_called_once_with(
            'https://example.com/default',
            timeout=10,
            json={'message': 'Torrent Example.Torrent.1080p matched'},
        )

    @patch('qbt_rules.engine.requests.post')
    def test_params_url_overrides_default(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(
            mock_api, dry_run=False,
            notifications_config={'webhook_url': 'https://example.com/default', 'service': 'generic'}
        )

        action = {
            'type': 'notify',
            'params': {'url': 'https://example.com/override', 'message': 'hi'},
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        assert mock_post.call_args[0][0] == 'https://example.com/override'

    @patch('qbt_rules.engine.requests.post')
    def test_no_url_anywhere_fails_without_http_call(self, mock_post, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False)  # no notifications_config at all

        action = {'type': 'notify', 'params': {'message': 'hi'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_post.assert_not_called()


class TestNotifyDryRun:
    """Dry-run mode never makes an HTTP call."""

    @patch('qbt_rules.engine.requests.post')
    def test_dry_run_does_not_call_requests(self, mock_post, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=True)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
                'message': 'Torrent {name} matched',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        assert skipped is True
        mock_post.assert_not_called()


class TestNotifyHttpFailure:
    """Network/HTTP errors are caught and don't crash the rule."""

    @patch('qbt_rules.engine.requests.post')
    def test_connection_error_returns_false(self, mock_post, mock_api, sample_torrent):
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
                'message': 'hi',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False

    @patch('qbt_rules.engine.requests.post')
    def test_http_error_status_returns_false(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response(status_code=404)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {
            'type': 'notify',
            'params': {
                'service': 'discord',
                'url': 'https://discord.com/api/webhooks/x/y',
                'message': 'hi',
            },
        }
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False


class TestNotifyChainedAfterDelete:
    """notify placed after delete_torrent in the same rule still sees the
    pre-deletion torrent data (verified via ActionExecutor directly; the
    full RulesEngine-level chaining behavior is covered in
    tests/integration/test_rule_execution.py)."""

    @patch('qbt_rules.engine.requests.post')
    def test_notify_after_delete_uses_last_known_torrent_data(self, mock_post, mock_api, sample_torrent):
        mock_post.return_value = _mock_response()
        mock_api.torrents_data = {sample_torrent['hash']: dict(sample_torrent)}
        executor = ActionExecutor(mock_api, dry_run=False)

        delete_action = {'type': 'delete_torrent', 'params': {'delete_files': True}}
        delete_success, _ = executor.execute(sample_torrent, delete_action)
        assert delete_success is True
        assert sample_torrent['hash'] not in mock_api.torrents_data  # really deleted

        # torrent dict itself is untouched (ActionExecutor never mutates it --
        # that refetch/update happens one layer up, in RulesEngine.run())
        notify_action = {
            'type': 'notify',
            'params': {
                'service': 'generic',
                'url': 'https://example.com/webhook',
                'message': 'Deleted {name}',
            },
        }
        notify_success, _ = executor.execute(sample_torrent, notify_action)

        assert notify_success is True
        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'message': 'Deleted Example.Torrent.1080p'},
        )
