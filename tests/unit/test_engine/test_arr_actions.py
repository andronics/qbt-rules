"""Tests for the arr_blocklist_and_search action in engine.py
(ActionExecutor._execute_arr_blocklist_and_search)."""

import logging
from unittest.mock import Mock, patch

import pytest
import requests

from qbt_rules.engine import ActionExecutor


SONARR_CONFIG = {
    'sonarr': {'url': 'http://sonarr:8989', 'api_key': 'sonarr-key'},
    'radarr': {'url': 'http://radarr:7878', 'api_key': 'radarr-key'},
}


def _mock_response(json_data=None, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status_code} Error")
    else:
        response.raise_for_status.return_value = None
    return response


def _queue_page(records, total_records=None):
    return _mock_response({
        'records': records,
        'totalRecords': total_records if total_records is not None else len(records),
    })


class TestArrBlocklistAndSearchSonarr:
    """Sonarr blocklist + EpisodeSearch flow."""

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_single_episode_match_blocklists_and_searches(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent
    ):
        mock_get.return_value = _queue_page([
            {'id': 42, 'downloadId': sample_torrent['hash'].upper(), 'episodeId': 100},
        ])
        mock_delete.return_value = _mock_response()
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_get.assert_called_once_with(
            'http://sonarr:8989/api/v3/queue',
            params={'apikey': 'sonarr-key', 'page': 1, 'pageSize': 250},
            timeout=10,
        )
        mock_delete.assert_called_once_with(
            'http://sonarr:8989/api/v3/queue/42',
            params={'apikey': 'sonarr-key', 'removeFromClient': 'false', 'blocklist': 'true'},
            timeout=10,
        )
        mock_post.assert_called_once_with(
            'http://sonarr:8989/api/v3/command',
            params={'apikey': 'sonarr-key'},
            json={'name': 'EpisodeSearch', 'episodeIds': [100]},
            timeout=10,
        )

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_season_pack_multiple_records_blocklists_all_and_searches_all_episodes(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent
    ):
        """A multi-episode download can produce multiple queue records
        sharing the same downloadId -- all must be blocklisted, and the
        search should cover every episode."""
        h = sample_torrent['hash'].upper()
        mock_get.return_value = _queue_page([
            {'id': 1, 'downloadId': h, 'episodeId': 100},
            {'id': 2, 'downloadId': h, 'episodeId': 101},
            {'id': 3, 'downloadId': 'SOMEOTHERHASH', 'episodeId': 999},
        ])
        mock_delete.return_value = _mock_response()
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        assert mock_delete.call_count == 2
        deleted_ids = {c.args[0] for c in mock_delete.call_args_list}
        assert deleted_ids == {
            'http://sonarr:8989/api/v3/queue/1',
            'http://sonarr:8989/api/v3/queue/2',
        }
        mock_post.assert_called_once_with(
            'http://sonarr:8989/api/v3/command',
            params={'apikey': 'sonarr-key'},
            json={'name': 'EpisodeSearch', 'episodeIds': [100, 101]},
            timeout=10,
        )

    @patch('qbt_rules.engine.requests.get')
    def test_pagination_across_multiple_pages(self, mock_get, mock_api, sample_torrent):
        h = sample_torrent['hash'].upper()
        page1_records = [{'id': i, 'downloadId': 'OTHER', 'episodeId': i} for i in range(250)]
        page2 = _queue_page([{'id': 250, 'downloadId': h, 'episodeId': 999}], total_records=251)
        page1 = _queue_page(page1_records, total_records=251)
        mock_get.side_effect = [page1, page2]

        with patch('qbt_rules.engine.requests.delete', return_value=_mock_response()), \
             patch('qbt_rules.engine.requests.post', return_value=_mock_response()):
            executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)
            action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
            success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[0].kwargs['params']['page'] == 1
        assert mock_get.call_args_list[1].kwargs['params']['page'] == 2


class TestArrBlocklistAndSearchRadarr:
    """Radarr blocklist + MoviesSearch flow."""

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_movie_match_blocklists_and_searches(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent
    ):
        mock_get.return_value = _queue_page([
            {'id': 7, 'downloadId': sample_torrent['hash'].upper(), 'movieId': 55},
        ])
        mock_delete.return_value = _mock_response()
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'radarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_delete.assert_called_once_with(
            'http://radarr:7878/api/v3/queue/7',
            params={'apikey': 'radarr-key', 'removeFromClient': 'false', 'blocklist': 'true'},
            timeout=10,
        )
        mock_post.assert_called_once_with(
            'http://radarr:7878/api/v3/command',
            params={'apikey': 'radarr-key'},
            json={'name': 'MoviesSearch', 'movieIds': [55]},
            timeout=10,
        )


class TestArrBlocklistAndSearchNoMatch:
    """No queue match is a non-fatal skip, not an error."""

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_no_match_returns_success_without_delete_or_search(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent, caplog
    ):
        mock_get.return_value = _queue_page([{'id': 1, 'downloadId': 'UNRELATED', 'episodeId': 1}])
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        with caplog.at_level(logging.WARNING):
            success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_delete.assert_not_called()
        mock_post.assert_not_called()
        assert "not found in sonarr's queue" in caplog.text

    @patch('qbt_rules.engine.requests.get')
    def test_empty_queue_returns_success(self, mock_get, mock_api, sample_torrent):
        mock_get.return_value = _queue_page([])
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True


class TestArrBlocklistAndSearchRemoveFromClient:
    """remove_from_client param overrides the default False."""

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_remove_from_client_true_is_passed_through(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent
    ):
        mock_get.return_value = _queue_page([
            {'id': 42, 'downloadId': sample_torrent['hash'].upper(), 'episodeId': 100},
        ])
        mock_delete.return_value = _mock_response()
        mock_post.return_value = _mock_response()
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {
            'type': 'arr_blocklist_and_search',
            'params': {'service': 'sonarr', 'remove_from_client': True},
        }
        executor.execute(sample_torrent, action)

        assert mock_delete.call_args.kwargs['params']['removeFromClient'] == 'true'


class TestArrBlocklistAndSearchConfigErrors:
    """Missing/invalid service or integration config fails without an HTTP call."""

    @patch('qbt_rules.engine.requests.get')
    def test_missing_service_param_fails(self, mock_get, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)
        action = {'type': 'arr_blocklist_and_search', 'params': {}}

        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_get.assert_not_called()

    @patch('qbt_rules.engine.requests.get')
    def test_unknown_service_param_fails(self, mock_get, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)
        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'overseerr'}}

        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_get.assert_not_called()

    @patch('qbt_rules.engine.requests.get')
    def test_no_integrations_config_at_all_fails(self, mock_get, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=False)  # no integrations_config

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_get.assert_not_called()

    @patch('qbt_rules.engine.requests.get')
    def test_configured_service_missing_api_key_fails(self, mock_get, mock_api, sample_torrent):
        executor = ActionExecutor(
            mock_api, dry_run=False,
            integrations_config={'sonarr': {'url': 'http://sonarr:8989', 'api_key': None}}
        )

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False
        mock_get.assert_not_called()


class TestArrBlocklistAndSearchHttpFailure:
    """Network/HTTP errors at each stage are caught and don't crash the rule."""

    @patch('qbt_rules.engine.requests.get')
    def test_queue_lookup_failure_returns_false(self, mock_get, mock_api, sample_torrent):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False

    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_blocklist_delete_failure_returns_false(self, mock_get, mock_delete, mock_api, sample_torrent):
        mock_get.return_value = _queue_page([
            {'id': 42, 'downloadId': sample_torrent['hash'].upper(), 'episodeId': 100},
        ])
        mock_delete.return_value = _mock_response(status_code=500)
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False

    @patch('qbt_rules.engine.requests.post')
    @patch('qbt_rules.engine.requests.delete')
    @patch('qbt_rules.engine.requests.get')
    def test_search_command_failure_returns_false(
        self, mock_get, mock_delete, mock_post, mock_api, sample_torrent
    ):
        mock_get.return_value = _queue_page([
            {'id': 42, 'downloadId': sample_torrent['hash'].upper(), 'episodeId': 100},
        ])
        mock_delete.return_value = _mock_response()
        mock_post.return_value = _mock_response(status_code=500)
        executor = ActionExecutor(mock_api, dry_run=False, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is False


class TestArrBlocklistAndSearchDryRun:
    """Dry-run mode never makes an HTTP call."""

    @patch('qbt_rules.engine.requests.get')
    def test_dry_run_does_not_call_requests(self, mock_get, mock_api, sample_torrent):
        executor = ActionExecutor(mock_api, dry_run=True, integrations_config=SONARR_CONFIG)

        action = {'type': 'arr_blocklist_and_search', 'params': {'service': 'sonarr'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        assert skipped is True
        mock_get.assert_not_called()
