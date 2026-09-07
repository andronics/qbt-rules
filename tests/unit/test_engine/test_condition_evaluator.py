"""Comprehensive tests for ConditionEvaluator class in engine.py."""

import pytest
import re
from unittest.mock import Mock, MagicMock, patch
from qbt_rules.engine import ConditionEvaluator
from qbt_rules.errors import FieldError, OperatorError


# ============================================================================
# Initialization and Cache Management
# ============================================================================

class TestConditionEvaluatorInit:
    """Test initialization and cache management."""

    def test_init(self, mock_api):
        """Initialize evaluator with API."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator.api == mock_api
        assert evaluator.trackers_cache == {}
        assert evaluator.files_cache == {}

    def test_caches_start_empty(self, mock_api):
        """All caches start empty."""
        evaluator = ConditionEvaluator(mock_api)
        assert len(evaluator.trackers_cache) == 0
        assert len(evaluator.files_cache) == 0
        assert len(evaluator.peers_cache) == 0
        assert evaluator.transfer_info is None

    def test_clear_caches(self, mock_api):
        """Clear caches resets all state."""
        evaluator = ConditionEvaluator(mock_api)

        # Populate caches
        evaluator.trackers_cache['hash1'] = [{'url': 'test'}]
        evaluator.files_cache['hash2'] = [{'name': 'test'}]
        evaluator.transfer_info = {'speed': 1000}

        # Clear
        evaluator.clear_caches()

        assert evaluator.trackers_cache == {}
        assert evaluator.files_cache == {}
        assert evaluator.transfer_info is None


# ============================================================================
# Context Evaluation
# ============================================================================

class TestContextEvaluation:
    """Test _evaluate_context() method."""

    def test_context_matches_string(self, mock_api):
        """String context matches exactly."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._evaluate_context('adhoc-run', 'adhoc-run') is True
        assert evaluator._evaluate_context('weekly-cleanup', 'adhoc-run') is False

    def test_context_matches_list(self, mock_api):
        """Context matches if in list."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._evaluate_context('adhoc-run', ['adhoc-run', 'weekly-cleanup']) is True
        assert evaluator._evaluate_context('torrent-imported', ['adhoc-run', 'weekly-cleanup']) is False

    def test_context_agnostic_mode_returns_false(self, mock_api):
        """Context-agnostic mode (None) returns False."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._evaluate_context(None, 'adhoc-run') is False
        assert evaluator._evaluate_context(None, ['adhoc-run', 'weekly-cleanup']) is False

    def test_evaluate_with_matching_trigger(self, mock_api, sample_torrent):
        """evaluate() succeeds with matching context."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
        }
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run', required_context='adhoc-run')
        assert result is True

    def test_evaluate_with_non_matching_trigger(self, mock_api, sample_torrent):
        """evaluate() fails with non-matching context."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
        }
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run', required_context='weekly-cleanup')
        assert result is False

    def test_evaluate_context_agnostic_mode_skips_rules_with_context(self, mock_api, sample_torrent):
        """Context-agnostic mode skips rules WITH context conditions."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
        }
        result = evaluator.evaluate(sample_torrent, conditions, current_context=None, required_context='adhoc-run')
        assert result is False

    def test_evaluate_context_agnostic_mode_allows_rules_without_trigger(self, mock_api, sample_torrent):
        """Context-agnostic mode allows rules WITHOUT context requirements."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
        }
        # Rules without context requirements execute regardless of runtime context
        result = evaluator.evaluate(sample_torrent, conditions, current_context=None, required_context=None)
        assert result is True  # Rule without context executes even when runtime context is None

    def test_evaluate_no_context_condition_with_context_set(self, mock_api, sample_torrent):
        """Rules without context condition match when context is set."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
        }
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run', required_context=None)
        assert result is True


# ============================================================================
# Logical Groups - all/any/none
# ============================================================================

class TestLogicalGroups:
    """Test logical condition groups."""

    # _evaluate_all() - AND logic
    def test_all_with_all_conditions_true(self, mock_api, sample_torrent):
        """all: all conditions true returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'all': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
            {'field': 'info.state', 'operator': '==', 'value': 'uploading'},
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_all_with_one_condition_false(self, mock_api, sample_torrent):
        """all: one false condition returns False."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'all': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
            {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_all_empty_list(self, mock_api, sample_torrent):
        """all: empty list returns True (vacuous truth)."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'all': []}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_all_single_condition(self, mock_api, sample_torrent):
        """all: single condition works."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'all': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    # _evaluate_any() - OR logic
    def test_any_with_one_condition_true(self, mock_api, sample_torrent):
        """any: one true condition returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'any': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 10.0},  # False
            {'field': 'info.state', 'operator': '==', 'value': 'uploading'},  # True
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_any_with_all_conditions_false(self, mock_api, sample_torrent):
        """any: all false returns False."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'any': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 10.0},  # False
            {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_any_empty_list(self, mock_api, sample_torrent):
        """any: empty list returns False."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'any': []}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_any_all_conditions_true(self, mock_api, sample_torrent):
        """any: all true returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'any': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
            {'field': 'info.state', 'operator': '==', 'value': 'uploading'},
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    # _evaluate_none() - NOT logic
    def test_none_with_all_conditions_false(self, mock_api, sample_torrent):
        """none: all false returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'none': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 10.0},  # False
            {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_none_with_one_condition_true(self, mock_api, sample_torrent):
        """none: one true returns False."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'none': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_none_empty_list(self, mock_api, sample_torrent):
        """none: empty list returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {'none': []}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    # Bare list conditions (no 'all'/'any'/'none' wrapper) - implicit AND
    #
    # Regression coverage: before this was fixed, a bare list didn't match
    # 'all' in conditions / 'any' in conditions / 'none' in conditions (list
    # membership checks against a list of dicts, always False), so evaluate()
    # fell through to `return True` unconditionally -- every rule written in
    # this style (as advanced-rules-example.yml is, throughout) matched every
    # torrent regardless of its conditions.
    def test_bare_list_all_conditions_true(self, mock_api, sample_torrent):
        """Bare list: all entries true returns True."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
            {'field': 'info.state', 'operator': '==', 'value': 'uploading'},
        ]
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_bare_list_one_condition_false(self, mock_api, sample_torrent):
        """Bare list: one false entry returns False (must behave as AND, not vacuous True)."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            {'field': 'info.ratio', 'operator': '>=', 'value': 999.0},  # False
        ]
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_bare_list_with_nested_logical_group(self, mock_api, sample_torrent):
        """Bare list entries can themselves be nested all/any/none groups."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            {'none': [
                {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
            ]},
        ]
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_bare_list_empty(self, mock_api, sample_torrent):
        """Bare list: empty list returns True (vacuous truth, matches 'all': [])."""
        evaluator = ConditionEvaluator(mock_api)
        result = evaluator.evaluate(sample_torrent, [], current_context='adhoc-run')
        assert result is True

    def test_combined_logical_groups(self, mock_api, sample_torrent):
        """Combined all/any/none groups."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [
                {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            ],
            'any': [
                {'field': 'info.state', 'operator': '==', 'value': 'uploading'},  # True
                {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
            ],
            'none': [
                {'field': 'info.ratio', 'operator': '<', 'value': 0.5},  # False
            ]
        }
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_nested_all_operator(self, mock_api, sample_torrent):
        """Nested 'all' operator inside a condition (covers line 153)."""
        evaluator = ConditionEvaluator(mock_api)
        # Top-level 'any' containing a nested 'all'
        conditions = {'any': [
            {'all': [  # Nested all operator
                {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
                {'field': 'info.state', 'operator': '==', 'value': 'uploading'},  # True
            ]},
            {'field': 'info.ratio', 'operator': '<', 'value': 0.1},  # False
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_nested_any_operator(self, mock_api, sample_torrent):
        """Nested 'any' operator inside a condition (covers line 155)."""
        evaluator = ConditionEvaluator(mock_api)
        # Top-level 'all' containing a nested 'any'
        conditions = {'all': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            {'any': [  # Nested any operator
                {'field': 'info.state', 'operator': '==', 'value': 'uploading'},  # True
                {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
            ]}
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True

    def test_nested_none_operator(self, mock_api, sample_torrent):
        """Nested 'none' operator inside a condition (covers line 157)."""
        evaluator = ConditionEvaluator(mock_api)
        # Top-level 'all' containing a nested 'none'
        conditions = {'all': [
            {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},  # True
            {'none': [  # Nested none operator
                {'field': 'info.state', 'operator': '==', 'value': 'downloading'},  # False
                {'field': 'info.ratio', 'operator': '<', 'value': 0.5},  # False
            ]}
        ]}
        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is True


# ============================================================================
# Field Access - info.*
# ============================================================================

class TestFieldAccessInfo:
    """Test info.* field access."""

    def test_info_name(self, mock_api, sample_torrent):
        """Access info.name field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.name')
        assert value == sample_torrent['name']

    def test_info_size(self, mock_api, sample_torrent):
        """Access info.size field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.size')
        assert value == sample_torrent['size']

    def test_info_ratio(self, mock_api, sample_torrent):
        """Access info.ratio field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.ratio')
        assert value == 2.0

    def test_info_state(self, mock_api, sample_torrent):
        """Access info.state field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.state')
        assert value == 'uploading'

    def test_info_tags_parsed(self, mock_api):
        """info.tags returns parsed list."""
        evaluator = ConditionEvaluator(mock_api)
        torrent = {'hash': 'test', 'tags': 'tag1,tag2,tag3'}
        value = evaluator._get_field_value(torrent, 'info.tags')
        assert value == ['tag1', 'tag2', 'tag3']

    def test_info_tags_empty(self, mock_api):
        """info.tags with empty tags."""
        evaluator = ConditionEvaluator(mock_api)
        torrent = {'hash': 'test', 'tags': ''}
        value = evaluator._get_field_value(torrent, 'info.tags')
        assert value == []

    def test_info_missing_field(self, mock_api, sample_torrent):
        """Missing info field returns None."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.nonexistent')
        assert value is None

    def test_info_category(self, mock_api, sample_torrent):
        """Access info.category field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.category')
        assert value == sample_torrent.get('category', '')

    def test_info_num_seeds(self, mock_api, sample_torrent):
        """Access info.num_seeds field."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.num_seeds')
        assert value == 5

    def test_info_completion_on(self, mock_api, sample_torrent):
        """Access info.completion_on timestamp."""
        evaluator = ConditionEvaluator(mock_api)
        value = evaluator._get_field_value(sample_torrent, 'info.completion_on')
        assert value == 1700010000


# ============================================================================
# Field Access - Collections (trackers, files, peers)
# ============================================================================

class TestFieldAccessCollections:
    """Test collection field access with lazy loading."""

    def test_trackers_url(self, mock_api, sample_torrent, mock_trackers):
        """Access trackers.url returns list of URLs."""
        mock_api.get_trackers = Mock(return_value=mock_trackers)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'trackers.url')

        assert isinstance(value, list)
        assert len(value) == 2  # Filtered to HTTP only
        assert 'tracker1.example.com' in value[0]

    def test_trackers_cached(self, mock_api, sample_torrent, mock_trackers):
        """Trackers are cached after first call."""
        mock_api.get_trackers = Mock(return_value=mock_trackers)
        evaluator = ConditionEvaluator(mock_api)

        # First call
        evaluator._get_field_value(sample_torrent, 'trackers.url')
        # Second call
        evaluator._get_field_value(sample_torrent, 'trackers.status')

        # API should be called only once
        mock_api.get_trackers.assert_called_once()

    def test_trackers_filters_special_entries(self, mock_api, sample_torrent):
        """Trackers filters out DHT/PeX/LSD."""
        mock_trackers = [
            {'url': 'http://real-tracker.com', 'status': 2},
            {'url': '** [DHT] **', 'status': 0},
            {'url': '** [PeX] **', 'status': 0},
        ]
        mock_api.get_trackers = Mock(return_value=mock_trackers)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'trackers.url')

        assert len(value) == 1
        assert 'real-tracker.com' in value[0]

    def test_files_name(self, mock_api, sample_torrent, mock_files):
        """Access files.name returns list of filenames."""
        mock_api.get_files = Mock(return_value=mock_files)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'files.name')

        assert isinstance(value, list)
        assert len(value) == 3
        assert 'Movie.1080p.mkv' in value

    def test_files_size(self, mock_api, sample_torrent, mock_files):
        """Access files.size returns list of sizes."""
        mock_api.get_files = Mock(return_value=mock_files)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'files.size')

        assert isinstance(value, list)
        assert 2147483648 in value

    def test_files_cached(self, mock_api, sample_torrent, mock_files):
        """Files are cached after first call."""
        mock_api.get_files = Mock(return_value=mock_files)
        evaluator = ConditionEvaluator(mock_api)

        evaluator._get_field_value(sample_torrent, 'files.name')
        evaluator._get_field_value(sample_torrent, 'files.size')

        mock_api.get_files.assert_called_once()

    def test_peers_ip(self, mock_api, sample_torrent, mock_peers):
        """Access peers.ip returns list of IPs."""
        mock_api.get_peers = Mock(return_value=list(mock_peers.values()))
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'peers.ip')

        assert isinstance(value, list)
        assert '192.168.1.100' in value

    def test_peers_client(self, mock_api, sample_torrent, mock_peers):
        """Access peers.client returns list of clients."""
        mock_api.get_peers = Mock(return_value=list(mock_peers.values()))
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'peers.client')

        assert isinstance(value, list)
        assert any('qBittorrent' in str(c) for c in value)

    def test_webseeds_url(self, mock_api, sample_torrent, mock_webseeds):
        """Access webseeds.url returns list of URLs."""
        mock_api.get_webseeds = Mock(return_value=mock_webseeds)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'webseeds.url')

        assert isinstance(value, list)
        assert len(value) == 2

    def test_properties_save_path(self, mock_api, sample_torrent, mock_properties):
        """Access properties.save_path."""
        mock_api.get_properties = Mock(return_value=mock_properties)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'properties.save_path')

        assert value == '/downloads/torrents/'

    def test_properties_cached(self, mock_api, sample_torrent, mock_properties):
        """Properties are cached."""
        mock_api.get_properties = Mock(return_value=mock_properties)
        evaluator = ConditionEvaluator(mock_api)

        evaluator._get_field_value(sample_torrent, 'properties.save_path')
        evaluator._get_field_value(sample_torrent, 'properties.comment')

        mock_api.get_properties.assert_called_once()

    def test_collection_empty_list(self, mock_api, sample_torrent):
        """Empty collection returns empty list."""
        mock_api.get_files = Mock(return_value=[])
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'files.name')

        assert value == []


# ============================================================================
# Field Access - Global Context (transfer, app)
# ============================================================================

class TestFieldAccessGlobal:
    """Test global context field access."""

    def test_transfer_dl_speed(self, mock_api, sample_torrent, mock_transfer_info):
        """Access transfer.dl_info_speed."""
        mock_api.get_transfer_info = Mock(return_value=mock_transfer_info)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'transfer.dl_info_speed')

        assert value == 2097152

    def test_transfer_cached_across_torrents(self, mock_api, sample_torrent, mock_transfer_info):
        """Transfer info cached across torrents."""
        mock_api.get_transfer_info = Mock(return_value=mock_transfer_info)
        evaluator = ConditionEvaluator(mock_api)

        evaluator._get_field_value(sample_torrent, 'transfer.dl_info_speed')
        evaluator._get_field_value(sample_torrent, 'transfer.up_info_speed')

        mock_api.get_transfer_info.assert_called_once()

    def test_app_preferences(self, mock_api, sample_torrent, mock_app_preferences):
        """Access app.* preferences."""
        mock_api.get_app_preferences = Mock(return_value=mock_app_preferences)
        evaluator = ConditionEvaluator(mock_api)

        value = evaluator._get_field_value(sample_torrent, 'app.save_path')

        assert value == '/downloads/'

    def test_app_preferences_cached(self, mock_api, sample_torrent, mock_app_preferences):
        """App preferences cached."""
        mock_api.get_app_preferences = Mock(return_value=mock_app_preferences)
        evaluator = ConditionEvaluator(mock_api)

        evaluator._get_field_value(sample_torrent, 'app.save_path')
        evaluator._get_field_value(sample_torrent, 'app.locale')

        mock_api.get_app_preferences.assert_called_once()


# ============================================================================
# Field Access - Error Handling
# ============================================================================

class TestFieldAccessErrors:
    """Test field access error handling."""

    def test_field_without_dot_raises_error(self, mock_api, sample_torrent):
        """Field without dot notation raises FieldError."""
        evaluator = ConditionEvaluator(mock_api)

        with pytest.raises(FieldError) as exc_info:
            evaluator._get_field_value(sample_torrent, 'invalidfield')

        assert "dot notation" in str(exc_info.value).lower()

    def test_unknown_endpoint_raises_error(self, mock_api, sample_torrent):
        """Unknown API endpoint raises FieldError."""
        evaluator = ConditionEvaluator(mock_api)

        with pytest.raises(FieldError) as exc_info:
            evaluator._get_field_value(sample_torrent, 'unknown.field')

        assert "unknown" in str(exc_info.value).lower()

    def test_empty_field_raises_error(self, mock_api, sample_torrent):
        """Empty field raises FieldError."""
        evaluator = ConditionEvaluator(mock_api)

        with pytest.raises(FieldError):
            evaluator._get_field_value(sample_torrent, '.')


# ============================================================================
# Operator Tests - Comparison
# ============================================================================

class TestOperators:
    """Test all comparison operators."""

    # Equality operators
    def test_operator_equals(self, mock_api):
        """Operator == works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('test', '==', 'test', 'field') is True
        assert evaluator._apply_operator('test', '==', 'other', 'field') is False

    def test_operator_not_equals(self, mock_api):
        """Operator != works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('test', '!=', 'other', 'field') is True
        assert evaluator._apply_operator('test', '!=', 'test', 'field') is False

    # String operators
    def test_operator_contains(self, mock_api):
        """Operator contains works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('hello world', 'contains', 'world', 'field') is True
        assert evaluator._apply_operator('hello world', 'contains', 'test', 'field') is False

    def test_operator_not_contains(self, mock_api):
        """Operator not_contains works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('hello world', 'not_contains', 'test', 'field') is True
        assert evaluator._apply_operator('hello world', 'not_contains', 'world', 'field') is False

    def test_operator_matches_regex(self, mock_api):
        """Operator matches works with regex."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('test123', 'matches', r'\d+', 'field') is True
        assert evaluator._apply_operator('testABC', 'matches', r'\d+', 'field') is False

    # List operators
    def test_operator_in_list(self, mock_api):
        """Operator in works with list."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('apple', 'in', ['apple', 'banana'], 'field') is True
        assert evaluator._apply_operator('cherry', 'in', ['apple', 'banana'], 'field') is False

    def test_operator_in_single_value(self, mock_api):
        """Operator in works with single value."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('test', 'in', 'test', 'field') is True
        assert evaluator._apply_operator('test', 'in', 'other', 'field') is False

    def test_operator_not_in_list(self, mock_api):
        """Operator not_in works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('cherry', 'not_in', ['apple', 'banana'], 'field') is True
        assert evaluator._apply_operator('apple', 'not_in', ['apple', 'banana'], 'field') is False

    def test_operator_not_in_single_value(self, mock_api):
        """Operator not_in with single value (non-list) works (covers line 306)."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator('cherry', 'not_in', 'apple', 'field') is True
        assert evaluator._apply_operator('apple', 'not_in', 'apple', 'field') is False

    def test_empty_collection_with_inequality_operators(self, mock_api, sample_torrent):
        """Empty collection [] with !=, not_in, not_contains returns True (covers line 281)."""
        mock_api.get_files = Mock(return_value=[])
        evaluator = ConditionEvaluator(mock_api)

        # Test with empty collection from files field
        condition_ne = {
            'field': 'files.name',
            'operator': '!=',
            'value': 'test.txt'
        }
        assert evaluator._evaluate_condition(sample_torrent, condition_ne) is True

        condition_not_in = {
            'field': 'files.name',
            'operator': 'not_in',
            'value': ['test.txt', 'other.txt']
        }
        assert evaluator._evaluate_condition(sample_torrent, condition_not_in) is True

        condition_not_contains = {
            'field': 'files.name',
            'operator': 'not_contains',
            'value': 'test'
        }
        assert evaluator._evaluate_condition(sample_torrent, condition_not_contains) is True

    # Numeric operators
    def test_operator_greater_than(self, mock_api):
        """Operator > works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(5, '>', 3, 'field') is True
        assert evaluator._apply_operator(3, '>', 5, 'field') is False
        assert evaluator._apply_operator(5, '>', 5, 'field') is False

    def test_operator_less_than(self, mock_api):
        """Operator < works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(3, '<', 5, 'field') is True
        assert evaluator._apply_operator(5, '<', 3, 'field') is False

    def test_operator_greater_or_equal(self, mock_api):
        """Operator >= works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(5, '>=', 5, 'field') is True
        assert evaluator._apply_operator(6, '>=', 5, 'field') is True
        assert evaluator._apply_operator(4, '>=', 5, 'field') is False

    def test_operator_less_or_equal(self, mock_api):
        """Operator <= works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(5, '<=', 5, 'field') is True
        assert evaluator._apply_operator(4, '<=', 5, 'field') is True
        assert evaluator._apply_operator(6, '<=', 5, 'field') is False

    # Size operators
    def test_operator_smaller_than(self, mock_api):
        """Operator smaller_than works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(500000000, 'smaller_than', '1GB', 'field') is True
        assert evaluator._apply_operator(2000000000, 'smaller_than', '1GB', 'field') is False

    def test_operator_larger_than(self, mock_api):
        """Operator larger_than works."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(2000000000, 'larger_than', '1GB', 'field') is True
        assert evaluator._apply_operator(500000000, 'larger_than', '1GB', 'field') is False

    # Time operators
    @patch('qbt_rules.utils.time.time', return_value=1700000000)
    def test_operator_older_than(self, mock_time, mock_api):
        """Operator older_than works."""
        evaluator = ConditionEvaluator(mock_api)
        old_timestamp = 1700000000 - 7776000  # 90 days ago
        assert evaluator._apply_operator(old_timestamp, 'older_than', '30 days', 'field') is True

        recent_timestamp = 1700000000 - 86400  # 1 day ago
        assert evaluator._apply_operator(recent_timestamp, 'older_than', '30 days', 'field') is False

    @patch('qbt_rules.utils.time.time', return_value=1700000000)
    def test_operator_newer_than(self, mock_time, mock_api):
        """Operator newer_than works."""
        evaluator = ConditionEvaluator(mock_api)
        recent_timestamp = 1700000000 - 86400  # 1 day ago
        assert evaluator._apply_operator(recent_timestamp, 'newer_than', '30 days', 'field') is True

        old_timestamp = 1700000000 - 7776000  # 90 days ago
        assert evaluator._apply_operator(old_timestamp, 'newer_than', '30 days', 'field') is False

    # Unknown operator
    def test_unknown_operator_raises_error(self, mock_api):
        """Unknown operator raises OperatorError."""
        evaluator = ConditionEvaluator(mock_api)

        with pytest.raises(OperatorError) as exc_info:
            evaluator._apply_operator('value', 'unknown_op', 'expected', 'field')

        assert 'unknown_op' in str(exc_info.value)

    # None/missing values
    def test_none_value_with_equals(self, mock_api):
        """None value with == returns False."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(None, '==', 'test', 'field') is False

    def test_none_value_with_not_equals(self, mock_api):
        """None value with != returns True."""
        evaluator = ConditionEvaluator(mock_api)
        assert evaluator._apply_operator(None, '!=', 'test', 'field') is True

    # List values (collections)
    def test_list_value_any_match(self, mock_api):
        """List values return True if ANY item matches."""
        evaluator = ConditionEvaluator(mock_api)
        values = ['apple', 'banana', 'cherry']
        assert evaluator._apply_operator(values, '==', 'banana', 'field') is True

    def test_list_value_no_match(self, mock_api):
        """List values return False if NO items match."""
        evaluator = ConditionEvaluator(mock_api)
        values = ['apple', 'banana', 'cherry']
        assert evaluator._apply_operator(values, '==', 'grape', 'field') is False


# ============================================================================
# Error Handling
# ============================================================================

class TestEvaluationErrorHandling:
    """Test error handling during evaluation."""

    def test_evaluation_error_returns_false(self, mock_api, sample_torrent):
        """Evaluation errors return False instead of raising."""
        evaluator = ConditionEvaluator(mock_api)
        conditions = {
            'all': [
                {'field': 'invalid_field', 'operator': '==', 'value': 'test'}
            ]
        }

        result = evaluator.evaluate(sample_torrent, conditions, current_context='adhoc-run')
        assert result is False

    def test_numeric_comparison_non_numeric_values(self, mock_api):
        """Numeric operators with non-numeric values return False."""
        evaluator = ConditionEvaluator(mock_api)
        result = evaluator._apply_operator('not_a_number', '>', 5, 'field')
        assert result is False
