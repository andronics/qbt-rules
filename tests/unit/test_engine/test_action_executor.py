"""Comprehensive tests for ActionExecutor class in engine.py."""

import pytest
from unittest.mock import Mock, patch, call
from qbt_rules.engine import ActionExecutor


# ============================================================================
# Initialization
# ============================================================================

class TestActionExecutorInit:
    """Test initialization."""

    def test_init_normal_mode(self, mock_api):
        """Initialize in normal mode."""
        executor = ActionExecutor(mock_api, dry_run=False)
        assert executor.api == mock_api
        assert executor.dry_run is False

    def test_init_dry_run_mode(self, mock_api):
        """Initialize in dry run mode."""
        executor = ActionExecutor(mock_api, dry_run=True)
        assert executor.dry_run is True


# ============================================================================
# Idempotency Checks
# ============================================================================

class TestIdempotencyChecks:
    """Test _should_skip_idempotent() method."""

    def test_stop_already_paused(self, mock_api):
        """stop: skip if already paused."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'state': 'pausedDL'}
        assert executor._should_skip_idempotent(torrent, 'stop', {}) is True

    def test_stop_not_paused(self, mock_api):
        """stop: don't skip if not paused."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'state': 'downloading'}
        assert executor._should_skip_idempotent(torrent, 'stop', {}) is False

    def test_start_already_running(self, mock_api):
        """start: skip if already running."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'state': 'downloading'}
        assert executor._should_skip_idempotent(torrent, 'start', {}) is True

    def test_start_paused(self, mock_api):
        """start: don't skip if paused."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'state': 'pausedDL'}
        assert executor._should_skip_idempotent(torrent, 'start', {}) is False

    def test_set_category_already_set(self, mock_api):
        """set_category: skip if already set."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'category': 'movies'}
        assert executor._should_skip_idempotent(torrent, 'set_category', {'category': 'movies'}) is True

    def test_set_category_different(self, mock_api):
        """set_category: don't skip if different."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'category': 'movies'}
        assert executor._should_skip_idempotent(torrent, 'set_category', {'category': 'tv'}) is False

    def test_add_tag_already_has_tags(self, mock_api):
        """add_tag: skip if tags already present."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'tags': 'hd,new'}
        assert executor._should_skip_idempotent(torrent, 'add_tag', {'tags': ['hd']}) is True

    def test_add_tag_missing_tags(self, mock_api):
        """add_tag: don't skip if tags missing."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'tags': 'hd'}
        assert executor._should_skip_idempotent(torrent, 'add_tag', {'tags': ['new']}) is False

    def test_remove_tag_tags_not_present(self, mock_api):
        """remove_tag: skip if tags not present."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'tags': 'hd,new'}
        assert executor._should_skip_idempotent(torrent, 'remove_tag', {'tags': ['old']}) is True

    def test_remove_tag_tags_present(self, mock_api):
        """remove_tag: don't skip if tags present."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'tags': 'hd,new,old'}
        assert executor._should_skip_idempotent(torrent, 'remove_tag', {'tags': ['old']}) is False


# ============================================================================
# Action Execution - Control Actions
# ============================================================================

class TestControlActions:
    """Test control actions (stop, start, force_start, recheck, reannounce)."""

    def test_stop_action(self, mock_api, sample_torrent):
        """Execute stop action."""
        mock_api.stop_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'stop'})

        assert success is True
        assert skipped is False
        mock_api.stop_torrents.assert_called_once_with([sample_torrent['hash']])

    def test_start_action(self, mock_api, paused_torrent):
        """Execute start action."""
        mock_api.start_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(paused_torrent, {'type': 'start'})

        assert success is True
        mock_api.start_torrents.assert_called_once_with([paused_torrent['hash']])

    def test_force_start_action(self, mock_api, sample_torrent):
        """Execute force_start action."""
        mock_api.force_start_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'force_start'})

        assert success is True
        mock_api.force_start_torrents.assert_called_once_with([sample_torrent['hash']])

    def test_recheck_action(self, mock_api, sample_torrent):
        """Execute recheck action."""
        mock_api.recheck_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'recheck'})

        assert success is True
        mock_api.recheck_torrents.assert_called_once_with([sample_torrent['hash']])

    def test_reannounce_action(self, mock_api, sample_torrent):
        """Execute reannounce action."""
        mock_api.reannounce_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'reannounce'})

        assert success is True
        mock_api.reannounce_torrents.assert_called_once_with([sample_torrent['hash']])


# ============================================================================
# Action Execution - Delete Action
# ============================================================================

class TestDeleteAction:
    """Test delete_torrent action."""

    def test_delete_keep_files(self, mock_api, sample_torrent):
        """Delete torrent but keep files."""
        mock_api.delete_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'delete_torrent', 'params': {'keep_files': True}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.delete_torrents.assert_called_once_with(
            [sample_torrent['hash']],
            delete_files=False
        )

    def test_delete_with_files(self, mock_api, sample_torrent):
        """Delete torrent and files."""
        mock_api.delete_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'delete_torrent', 'params': {'keep_files': False}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.delete_torrents.assert_called_once_with(
            [sample_torrent['hash']],
            delete_files=True
        )

    def test_delete_default_behavior(self, mock_api, sample_torrent):
        """Delete torrent with default params (delete files)."""
        mock_api.delete_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'delete_torrent', 'params': {}}
        success, skipped = executor.execute(sample_torrent, action)

        # Default keep_files=False means delete_files=True
        mock_api.delete_torrents.assert_called_once_with(
            [sample_torrent['hash']],
            delete_files=True
        )


# ============================================================================
# Action Execution - Category and Tags
# ============================================================================

class TestCategoryAndTagActions:
    """Test category and tag actions."""

    def test_set_category(self, mock_api, sample_torrent):
        """Set category action."""
        mock_api.set_category = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_category', 'params': {'category': 'movies'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_category.assert_called_once_with([sample_torrent['hash']], 'movies')

    def test_add_tag(self, mock_api, sample_torrent):
        """Add tag action."""
        mock_api.add_tags = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'add_tag', 'params': {'tags': ['hd', 'new']}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.add_tags.assert_called_once_with([sample_torrent['hash']], ['hd', 'new'])

    def test_remove_tag(self, mock_api):
        """Remove tag action."""
        mock_api.remove_tags = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        torrent = {'hash': 'test123', 'name': 'Test', 'tags': 'hd,new,old'}
        action = {'type': 'remove_tag', 'params': {'tags': ['old']}}
        success, skipped = executor.execute(torrent, action)

        assert success is True
        mock_api.remove_tags.assert_called_once_with(['test123'], ['old'])

    def test_set_tags_replaces_existing(self, mock_api):
        """set_tags removes old and sets new tags."""
        mock_api.remove_tags = Mock(return_value=True)
        mock_api.add_tags = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        torrent = {'hash': 'test123', 'name': 'Test', 'tags': 'old1,old2'}
        action = {'type': 'set_tags', 'params': {'tags': ['new1', 'new2']}}
        success, skipped = executor.execute(torrent, action)

        assert success is True
        mock_api.remove_tags.assert_called_once_with(['test123'], ['old1', 'old2'])
        mock_api.add_tags.assert_called_once_with(['test123'], ['new1', 'new2'])

    def test_set_tags_empty_existing(self, mock_api):
        """set_tags with no existing tags."""
        mock_api.remove_tags = Mock(return_value=True)
        mock_api.add_tags = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        torrent = {'hash': 'test123', 'name': 'Test', 'tags': ''}
        action = {'type': 'set_tags', 'params': {'tags': ['new']}}
        success, skipped = executor.execute(torrent, action)

        # Should not call remove_tags since no existing tags
        mock_api.remove_tags.assert_not_called()
        mock_api.add_tags.assert_called_once_with(['test123'], ['new'])

    def test_set_category_empty(self, mock_api):
        """Set empty category (uncategorize)."""
        mock_api.set_category = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        # Use torrent with existing category
        torrent = {'hash': 'test123', 'name': 'Test', 'category': 'movies', 'tags': '', 'state': 'uploading'}
        action = {'type': 'set_category', 'params': {'category': ''}}
        success, skipped = executor.execute(torrent, action)

        mock_api.set_category.assert_called_once_with(['test123'], '')


# ============================================================================
# Action Execution - Speed Limits
# ============================================================================

class TestSpeedLimitActions:
    """Test speed limit actions."""

    def test_set_upload_limit(self, mock_api, sample_torrent):
        """Set upload limit action."""
        mock_api.set_upload_limit = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_upload_limit', 'params': {'limit': 1048576}}  # 1 MB/s
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_upload_limit.assert_called_once_with([sample_torrent['hash']], 1048576)

    def test_set_download_limit(self, mock_api, sample_torrent):
        """Set download limit action."""
        mock_api.set_download_limit = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_download_limit', 'params': {'limit': 2097152}}  # 2 MB/s
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_download_limit.assert_called_once_with([sample_torrent['hash']], 2097152)


class TestPriorityActions:
    """Test torrent priority actions (increase_priority/decrease_priority/
    set_top_priority/set_bottom_priority). The API client methods for all
    four already existed in api.py, but weren't wired into the action
    dispatch -- using them from a rule fell through to the 'Unknown action
    type' branch (logged error, returned False), silently never doing
    anything. Found while verifying advanced-rules-example.yml Rule 9,
    which uses increase_priority as part of its process-hd-content action
    sequence."""

    def test_increase_priority(self, mock_api, sample_torrent):
        """Increase priority action."""
        mock_api.increase_priority = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'increase_priority'}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.increase_priority.assert_called_once_with([sample_torrent['hash']])

    def test_decrease_priority(self, mock_api, sample_torrent):
        """Decrease priority action."""
        mock_api.decrease_priority = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'decrease_priority'}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.decrease_priority.assert_called_once_with([sample_torrent['hash']])

    def test_set_top_priority(self, mock_api, sample_torrent):
        """Set top priority action."""
        mock_api.set_top_priority = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_top_priority'}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_top_priority.assert_called_once_with([sample_torrent['hash']])

    def test_set_bottom_priority(self, mock_api, sample_torrent):
        """Set bottom priority action."""
        mock_api.set_bottom_priority = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_bottom_priority'}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_bottom_priority.assert_called_once_with([sample_torrent['hash']])


# ============================================================================
# Dry Run Mode
# ============================================================================

class TestDryRunMode:
    """Test dry run mode behavior."""

    def test_dry_run_stop(self, mock_api, sample_torrent):
        """Dry run mode doesn't execute stop."""
        mock_api.stop_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=True)

        success, skipped = executor.execute(sample_torrent, {'type': 'stop'})

        assert success is True
        assert skipped is True  # Dry run actions are considered "skipped" (not executed)
        mock_api.stop_torrents.assert_not_called()

    def test_dry_run_delete(self, mock_api, sample_torrent):
        """Dry run mode doesn't execute delete."""
        mock_api.delete_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=True)

        action = {'type': 'delete_torrent', 'params': {'keep_files': True}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.delete_torrents.assert_not_called()

    def test_dry_run_set_category(self, mock_api, sample_torrent):
        """Dry run mode doesn't execute set_category."""
        mock_api.set_category = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=True)

        action = {'type': 'set_category', 'params': {'category': 'test'}}
        success, skipped = executor.execute(sample_torrent, action)

        assert success is True
        mock_api.set_category.assert_not_called()

    def test_dry_run_still_checks_idempotency(self, mock_api):
        """Dry run mode still checks idempotency."""
        executor = ActionExecutor(mock_api, dry_run=True)

        # Torrent already paused
        torrent = {'hash': 'test', 'name': 'Test', 'state': 'pausedDL'}
        success, skipped = executor.execute(torrent, {'type': 'stop'})

        # Should skip due to idempotency, even in dry run
        assert success is True
        assert skipped is True

    def test_dry_run_logs_actions(self, mock_api, sample_torrent):
        """Dry run mode logs what would happen."""
        executor = ActionExecutor(mock_api, dry_run=True)

        with patch('qbt_rules.engine.logger.info') as mock_log:
            executor.execute(sample_torrent, {'type': 'stop'})
            # Should log the dry run action
            mock_log.assert_called()


# ============================================================================
# Idempotency Skip Behavior
# ============================================================================

class TestIdempotencySkipBehavior:
    """Test behavior when actions are skipped due to idempotency."""

    def test_idempotent_skip_returns_true(self, mock_api):
        """Idempotent skip returns success=True, skipped=True."""
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'hash': 'test', 'name': 'Test', 'state': 'pausedDL'}

        success, skipped = executor.execute(torrent, {'type': 'stop'})

        assert success is True
        assert skipped is True

    def test_idempotent_skip_no_api_call(self, mock_api):
        """Idempotent skip doesn't make API call."""
        mock_api.stop_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)
        torrent = {'hash': 'test', 'name': 'Test', 'state': 'pausedDL'}

        executor.execute(torrent, {'type': 'stop'})

        mock_api.stop_torrents.assert_not_called()

    def test_non_idempotent_action_never_skips(self, mock_api, sample_torrent):
        """Non-idempotent actions are never skipped."""
        mock_api.recheck_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        # Call twice - should execute both times
        executor.execute(sample_torrent, {'type': 'recheck'})
        executor.execute(sample_torrent, {'type': 'recheck'})

        assert mock_api.recheck_torrents.call_count == 2


# ============================================================================
# Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling during action execution."""

    def test_unknown_action_type(self, mock_api, sample_torrent):
        """Unknown action type returns failure."""
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'unknown_action'})

        assert success is False
        assert skipped is False

    def test_api_failure_returns_false(self, mock_api, sample_torrent):
        """API failure returns success=False."""
        mock_api.stop_torrents = Mock(return_value=False)
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'stop'})

        assert success is False
        assert skipped is False

    def test_api_exception_caught(self, mock_api, sample_torrent):
        """API exceptions are caught and logged."""
        mock_api.stop_torrents = Mock(side_effect=Exception("API Error"))
        executor = ActionExecutor(mock_api, dry_run=False)

        success, skipped = executor.execute(sample_torrent, {'type': 'stop'})

        assert success is False
        assert skipped is False

    def test_missing_params_handled(self, mock_api, sample_torrent):
        """Missing params dict is handled gracefully."""
        mock_api.set_category = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        # Action without params key
        success, skipped = executor.execute(sample_torrent, {'type': 'set_category'})

        # Should use empty params dict, resulting in empty category
        assert success is True
        mock_api.set_category.assert_called_once_with([sample_torrent['hash']], '')


# ============================================================================
# Integration Tests
# ============================================================================

class TestActionExecutorIntegration:
    """Integration tests combining multiple features."""

    def test_multiple_actions_same_torrent(self, mock_api, sample_torrent):
        """Execute multiple actions on same torrent."""
        mock_api.set_category = Mock(return_value=True)
        mock_api.add_tags = Mock(return_value=True)
        mock_api.stop_torrents = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        actions = [
            {'type': 'set_category', 'params': {'category': 'movies'}},
            {'type': 'add_tag', 'params': {'tags': ['hd']}},
            {'type': 'stop'},
        ]

        for action in actions:
            success, skipped = executor.execute(sample_torrent, action)
            assert success is True

        mock_api.set_category.assert_called_once()
        mock_api.add_tags.assert_called_once()
        mock_api.stop_torrents.assert_called_once()

    def test_action_with_empty_params(self, mock_api, sample_torrent):
        """Action with explicitly empty params dict."""
        mock_api.set_upload_limit = Mock(return_value=True)
        executor = ActionExecutor(mock_api, dry_run=False)

        action = {'type': 'set_upload_limit', 'params': {}}
        success, skipped = executor.execute(sample_torrent, action)

        # Should use default limit=-1
        assert success is True
        mock_api.set_upload_limit.assert_called_once_with([sample_torrent['hash']], -1)

    def test_dry_run_vs_normal_mode(self, mock_api, sample_torrent):
        """Compare dry run vs normal execution."""
        mock_api.stop_torrents = Mock(return_value=True)

        # Normal mode
        executor_normal = ActionExecutor(mock_api, dry_run=False)
        success1, skipped1 = executor_normal.execute(sample_torrent, {'type': 'stop'})

        # Dry run mode
        executor_dry = ActionExecutor(mock_api, dry_run=True)
        success2, skipped2 = executor_dry.execute(sample_torrent, {'type': 'stop'})

        # Both succeed
        assert success1 is True
        assert success2 is True

        # But only normal mode calls API
        assert mock_api.stop_torrents.call_count == 1
