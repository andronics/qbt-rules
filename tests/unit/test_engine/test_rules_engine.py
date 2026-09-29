"""Comprehensive tests for RulesEngine class in engine.py."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from qbt_rules.engine import RulesEngine, RuleStats


# ============================================================================
# Initialization
# ============================================================================

class TestRulesEngineInit:
    """Test initialization."""

    def test_init_normal_mode(self, mock_api, mock_config):
        """Initialize in normal mode."""
        engine = RulesEngine(mock_api, mock_config, dry_run=False)

        assert engine.api == mock_api
        assert engine.config == mock_config
        assert engine.dry_run is False
        assert engine.evaluator is not None
        assert engine.executor is not None

    def test_init_dry_run_mode(self, mock_api, mock_config):
        """Initialize in dry run mode."""
        engine = RulesEngine(mock_api, mock_config, dry_run=True)

        assert engine.dry_run is True
        assert engine.executor.dry_run is True

    def test_init_stats(self, mock_api, mock_config):
        """Stats start at zero."""
        engine = RulesEngine(mock_api, mock_config)

        assert engine.stats.total_torrents == 0
        assert engine.stats.processed == 0
        assert engine.stats.rules_matched == 0
        assert engine.stats.by_rule == {}


# ============================================================================
# Basic Execution
# ============================================================================

class TestBasicExecution:
    """Test basic rule execution."""

    def test_run_with_no_torrents(self, mock_api, mock_config):
        """Run with no torrents."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {}
        engine = RulesEngine(mock_api, mock_config)

        engine.run(context='adhoc-run')

        assert engine.stats.total_torrents == 0

    def test_run_with_single_torrent(self, mock_api, mock_config, sample_torrent, simple_rule):
        """Run with single torrent."""
        mock_config.get_rules = Mock(return_value=[simple_rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.total_torrents == 1

    def test_run_with_multiple_torrents(self, mock_api, mock_config, sample_torrent, downloading_torrent, simple_rule):
        """Run with multiple torrents."""
        mock_config.get_rules = Mock(return_value=[simple_rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,
            downloading_torrent['hash']: downloading_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.total_torrents == 2

    def test_run_with_no_rules(self, mock_api, mock_config, sample_torrent):
        """Run with torrents but no rules."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.total_torrents == 1
        assert engine.stats.rules_matched == 0

    def test_run_disabled_rule_skipped(self, mock_api, mock_config, sample_torrent):
        """Disabled rules are skipped."""
        disabled_rule = {
            'name': 'Disabled rule',
            'enabled': False,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]},
            'actions': [{'type': 'stop'}]
        }
        mock_config.get_rules = Mock(return_value=[disabled_rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 0


# ============================================================================
# Rule Matching
# ============================================================================

class TestRuleMatching:
    """Test rule matching behavior."""

    def test_matching_rule_executes_actions(self, mock_api, mock_config, sample_torrent):
        """Matching rule executes actions."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
            },
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 1
        assert engine.stats.actions_executed >= 1

    def test_non_matching_rule_skips_actions(self, mock_api, mock_config, sample_torrent):
        """Non-matching rule doesn't execute actions."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 10.0}]  # Won't match
            },
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 0
        assert engine.stats.actions_executed == 0

    def test_multiple_rules_all_evaluated(self, mock_api, mock_config, sample_torrent):
        """Multiple rules are all evaluated in order."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'uploading'}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both rules should match
        assert engine.stats.rules_matched == 2

    def test_multiple_torrents_each_evaluated(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """Each torrent is evaluated against rules."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,  # ratio 2.0 - matches
            downloading_torrent['hash']: downloading_torrent,  # ratio 0.0 - doesn't match
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Only one should match
        assert engine.stats.rules_matched == 1

    def test_same_torrent_matches_multiple_rules(self, mock_api, mock_config, sample_torrent):
        """Same torrent can match multiple rules."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 2.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both rules match same torrent
        assert engine.stats.rules_matched == 2


# ============================================================================
# stop_on_match Behavior
# ============================================================================

class TestStopOnMatch:
    """Test stop_on_match behavior."""

    def test_stop_on_match_prevents_later_rules(self, mock_api, mock_config, sample_torrent):
        """stop_on_match prevents later rules from processing torrent."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'stop_on_match': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Only first rule should match
        assert engine.stats.rules_matched == 1
        assert engine.stats.processed == 1

    def test_stop_on_match_false_allows_later_rules(self, mock_api, mock_config, sample_torrent):
        """stop_on_match=False allows later rules."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'stop_on_match': False,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both rules should match
        assert engine.stats.rules_matched == 2

    def test_stop_on_match_only_affects_matching_torrent(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """stop_on_match only affects the torrent that matched."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'stop_on_match': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'uploading'}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'downloading'}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,  # uploading - matches rule1
            downloading_torrent['hash']: downloading_torrent,  # downloading - matches rule2
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both rules should match different torrents
        assert engine.stats.rules_matched == 2

    def test_stop_on_match_non_matching_rule(self, mock_api, mock_config, sample_torrent):
        """stop_on_match on non-matching rule doesn't affect torrent."""
        rule1 = {
            'name': 'Rule 1',
            'enabled': True,
            'stop_on_match': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 10.0}]},  # Won't match
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        rule2 = {
            'name': 'Rule 2',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},  # Will match
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag2']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Only rule2 should match
        assert engine.stats.rules_matched == 1


# ============================================================================
# Single Torrent Mode
# ============================================================================

class TestSingleTorrentMode:
    """Test single torrent mode (webhook)."""

    def test_run_with_torrent_hash(self, mock_api, mock_config, sample_torrent, downloading_torrent, simple_rule):
        """Run with specific torrent hash."""
        mock_config.get_rules = Mock(return_value=[simple_rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,
            downloading_torrent['hash']: downloading_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported', torrent_hash=sample_torrent['hash'])

        # Should only process the one torrent
        assert engine.stats.total_torrents == 1

    def test_run_with_nonexistent_hash(self, mock_api, mock_config, sample_torrent, simple_rule):
        """Run with non-existent torrent hash."""
        mock_config.get_rules = Mock(return_value=[simple_rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported', torrent_hash='nonexistent')

        # Should find no torrents
        assert engine.stats.total_torrents == 0

    def test_single_torrent_mode_evaluates_rules(self, mock_api, mock_config, sample_torrent):
        """Single torrent mode still evaluates all rules."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='download-finished', torrent_hash=sample_torrent['hash'])

        assert engine.stats.rules_matched == 1

    def test_single_torrent_mode_stats_reflects_all_torrents(self, mock_api, mock_config, sample_torrent, downloading_torrent, simple_rule):
        """stats.* aggregates over ALL torrents, not just the one being evaluated in webhook mode."""
        mock_config.get_rules = Mock(return_value=[simple_rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,       # state: uploading
            downloading_torrent['hash']: downloading_torrent,  # state: downloading
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported', torrent_hash=sample_torrent['hash'])

        assert engine.stats.total_torrents == 1  # only the targeted torrent
        assert engine.evaluator.stats['total'] == 2  # but stats.* sees the whole fleet
        assert engine.evaluator.stats['state']['uploading'] == 1
        assert engine.evaluator.stats['state']['downloading'] == 1


# ============================================================================
# stats.* Aggregate Namespace
# ============================================================================

class TestStatsNamespace:
    """Test the stats.* aggregate-count snapshot computed once per run."""

    def test_stats_snapshot_counts_by_state_and_category(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """Counter over torrent state/category is built from the full torrent list."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,             # state=uploading, category=''
            downloading_torrent['hash']: downloading_torrent,   # state=downloading, category=movies
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.evaluator.stats['total'] == 2
        assert engine.evaluator.stats['state'] == {'uploading': 1, 'downloading': 1}
        # Torrents with an empty/falsy category are excluded from stats.category
        assert engine.evaluator.stats['category'] == {'movies': 1}

    def test_stats_snapshot_counts_tags(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """A torrent's tags are flattened (comma-separated, possibly multiple) into a single Counter."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,             # tags=''
            downloading_torrent['hash']: downloading_torrent,   # tags='hd,new'
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.evaluator.stats['tag'] == {'hd': 1, 'new': 1}

    def test_stats_snapshot_sums_speeds_and_seeds_peers(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """dlspeed/upspeed/seeds/leechs are fleet-wide sums of the matching per-torrent info.* fields."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {
            # dlspeed=0, upspeed=524288, num_seeds=5, num_leechs=2
            sample_torrent['hash']: sample_torrent,
            # dlspeed=2097152, upspeed=0, num_seeds=10, num_leechs=3
            downloading_torrent['hash']: downloading_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.evaluator.stats['dlspeed'] == 2097152
        assert engine.evaluator.stats['upspeed'] == 524288
        assert engine.evaluator.stats['seeds'] == 15
        assert engine.evaluator.stats['leechs'] == 5

    def test_stats_field_usable_in_condition(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """A rule condition can reference stats.state.<state> against the numeric operators."""
        rule = {
            'name': 'Cap check',
            'enabled': True,
            'conditions': {'all': [{'field': 'stats.state.downloading', 'operator': '<', 'value': 5}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['under-cap']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,
            downloading_torrent['hash']: downloading_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 2  # both torrents see the same run-wide snapshot

    def test_stats_tag_updates_live_within_a_run_for_quota_gating(
        self, mock_api, mock_config, sample_torrent, downloading_torrent, seeding_torrent
    ):
        """
        stats.tag.* must reflect actions taken earlier in the SAME run, not
        just the run's starting snapshot -- otherwise a quota condition like
        stats.tag.force-seeding < budget would admit every matching torrent
        in one pass instead of stopping once the budget is reached.
        """
        rule = {
            'id': 'quota-gate',
            'enabled': True,
            'conditions': {'all': [{'field': 'stats.tag.force-seeding', 'operator': '<', 'value': 2}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['force-seeding']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,
            downloading_torrent['hash']: downloading_torrent,
            seeding_torrent['hash']: seeding_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        tagged = [t for t in mock_api.torrents_data.values() if 'force-seeding' in t.get('tags', '')]
        assert len(tagged) == 2  # budget of 2 -- the third torrent must not be admitted this run
        assert engine.evaluator.stats['tag']['force-seeding'] == 2

    def test_stats_state_updates_live_within_a_run(self, mock_api, mock_config, downloading_torrent, seeding_torrent):
        """stats.state.* reflects a state-changing action (force_start) taken earlier in the same run."""
        rule = {
            'id': 'admit-until-cap',
            'enabled': True,
            'conditions': {'all': [{'field': 'stats.state.forceDL', 'operator': '<', 'value': 1}]},
            'actions': [{'type': 'force_start'}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            downloading_torrent['hash']: downloading_torrent,
            seeding_torrent['hash']: seeding_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert len(mock_api.calls['force_start']) == 1  # cap of 1 -- second torrent must not be admitted this run
        assert engine.evaluator.stats['state']['forceDL'] == 1

    def test_stats_no_additional_api_calls(self, mock_api, mock_config, sample_torrent):
        """Computing stats.* must not introduce extra qBittorrent API calls."""
        mock_config.get_rules = Mock(return_value=[])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}
        mock_api.get_torrents = Mock(wraps=mock_api.get_torrents)

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        mock_api.get_torrents.assert_called_once()


# ============================================================================
# Statistics Tracking
# ============================================================================

class TestStatisticsTracking:
    """Test statistics tracking."""

    def test_stats_actions_executed(self, mock_api, mock_config, sample_torrent):
        """Track actions executed."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['tag1']}},
                {'type': 'add_tag', 'params': {'tags': ['tag2']}},
            ]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.actions_executed == 2

    def test_stats_actions_skipped_idempotency(self, mock_api, mock_config):
        """Track actions skipped due to idempotency."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'pausedDL'}]},
            'actions': [{'type': 'stop'}]  # Already paused
        }
        torrent = {'hash': 'test', 'name': 'Test', 'state': 'pausedDL', 'ratio': 1.0}
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {torrent['hash']: torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.actions_skipped == 1
        assert engine.stats.actions_executed == 0

    def test_stats_errors_tracked(self, mock_api, mock_config, sample_torrent):
        """Track action errors."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'unknown_action'}]  # Will fail
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.errors == 1

    def test_stats_processed_count(self, mock_api, mock_config, sample_torrent, downloading_torrent):
        """Track processed count with stop_on_match."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'stop_on_match': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]},  # Matches all
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            sample_torrent['hash']: sample_torrent,
            downloading_torrent['hash']: downloading_torrent,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.processed == 2


# ============================================================================
# Per-Rule Breakdown (stats.by_rule)
# ============================================================================

class TestByRuleStats:
    """Test the per-rule breakdown recorded in RuleStats.by_rule."""

    def test_by_rule_keyed_by_id(self, mock_api, mock_config, sample_torrent):
        """A rule is tracked under its required 'id'."""
        rule = {
            'id': 'test-rule',
            'meta': {'description': 'Test rule'},
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.by_rule == {
            'test-rule': {'matched': 1, 'actions_executed': 1, 'actions_skipped': 0, 'errors': 0}
        }

    def test_by_rule_survives_meta_description_change(self, mock_api, mock_config, sample_torrent):
        """The by_rule key is the id, not meta.description -- so a future
        rename of the human-readable text doesn't orphan the rule's history."""
        rule = {
            'id': 'rule-abc123',
            'meta': {'description': 'Renamed human-readable text'},
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['tag1']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert 'rule-abc123' in engine.stats.by_rule
        assert 'Renamed human-readable text' not in engine.stats.by_rule
        assert engine.stats.by_rule['rule-abc123']['matched'] == 1

    def test_by_rule_tracks_skipped_and_errors_separately(self, mock_api, mock_config):
        """actions_skipped/errors are attributed to the rule that caused them."""
        skipped_rule = {
            'id': 'idempotent-rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'pausedDL'}]},
            'actions': [{'type': 'stop'}]  # Already paused -> skipped
        }
        error_rule = {
            'id': 'failing-rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]},
            'actions': [{'type': 'unknown_action'}]  # Will error
        }
        torrent = {'hash': 'test', 'name': 'Test', 'state': 'pausedDL', 'ratio': 1.0}
        mock_config.get_rules = Mock(return_value=[skipped_rule, error_rule])
        mock_api.torrents_data = {torrent['hash']: torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.by_rule['idempotent-rule']['actions_skipped'] == 1
        assert engine.stats.by_rule['idempotent-rule']['errors'] == 0
        assert engine.stats.by_rule['failing-rule']['errors'] == 1
        assert engine.stats.by_rule['failing-rule']['actions_skipped'] == 0

    def test_by_rule_only_includes_enabled_rules_that_ran(self, mock_api, mock_config, sample_torrent):
        """A disabled rule never appears in by_rule, same as it never affects the aggregate counters."""
        disabled_rule = {
            'id': 'disabled-rule',
            'enabled': False,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]},
            'actions': [{'type': 'stop'}]
        }
        mock_config.get_rules = Mock(return_value=[disabled_rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.by_rule == {}

    def test_by_rule_present_even_without_a_match(self, mock_api, mock_config, sample_torrent):
        """An enabled rule that ran but never matched still gets a zeroed entry --
        distinguishing 'ran, matched nothing' from 'didn't run at all'."""
        rule = {
            'id': 'never-matches',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 999}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['test']}}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.by_rule == {
            'never-matches': {'matched': 0, 'actions_executed': 0, 'actions_skipped': 0, 'errors': 0}
        }


# ============================================================================
# Error Handling
# ============================================================================

class TestErrorHandling:
    """Test error handling."""

    def test_fatal_error_during_execution(self, mock_api, mock_config):
        """Fatal errors are caught and raised."""
        mock_config.get_rules = Mock(side_effect=Exception("Fatal error"))

        engine = RulesEngine(mock_api, mock_config)

        with pytest.raises(Exception) as exc_info:
            engine.run(context='adhoc-run')

        assert "Fatal error" in str(exc_info.value)

    def test_summary_printed_even_on_error(self, mock_api, mock_config):
        """Summary is printed even if error occurs."""
        mock_config.get_rules = Mock(side_effect=Exception("Fatal error"))

        engine = RulesEngine(mock_api, mock_config)

        with pytest.raises(Exception):
            with patch('qbt_rules.engine.logger.info') as mock_log:
                engine.run(context='adhoc-run')

                # Summary should still be logged
                summary_calls = [call for call in mock_log.call_args_list if 'Summary' in str(call)]
                assert len(summary_calls) > 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestRulesEngineIntegration:
    """Integration tests for complete workflows."""

    def test_complete_workflow_multiple_rules_torrents(self, mock_api, mock_config):
        """Complete workflow with multiple rules and torrents."""
        rule1 = {
            'name': 'High ratio torrents',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 2.0}]},
            'actions': [{'type': 'add_tag', 'params': {'tags': ['high-ratio']}}]
        }
        rule2 = {
            'name': 'Downloading torrents',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'downloading'}]},
            'actions': [{'type': 'set_category', 'params': {'category': 'active'}}]
        }

        torrent1 = {'hash': 'h1', 'name': 'T1', 'ratio': 3.0, 'state': 'uploading', 'tags': '', 'category': ''}
        torrent2 = {'hash': 'h2', 'name': 'T2', 'ratio': 0.5, 'state': 'downloading', 'tags': '', 'category': ''}
        torrent3 = {'hash': 'h3', 'name': 'T3', 'ratio': 2.5, 'state': 'uploading', 'tags': '', 'category': ''}

        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {
            torrent1['hash']: torrent1,
            torrent2['hash']: torrent2,
            torrent3['hash']: torrent3,
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Verify execution
        assert engine.stats.total_torrents == 3
        assert engine.stats.rules_matched == 3  # T1->rule1, T2->rule2, T3->rule1
        assert engine.stats.actions_executed >= 3

    def test_dry_run_mode_integration(self, mock_api, mock_config, sample_torrent):
        """Dry run mode doesn't execute actions."""
        rule = {
            'name': 'Test rule',
            'enabled': True,
            'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
            'actions': [{'type': 'stop'}]
        }
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config, dry_run=True)
        engine.run(context='adhoc-run')

        # Should match but not execute
        assert engine.stats.rules_matched == 1
        assert engine.stats.actions_executed == 0  # Dry run doesn't execute
        assert mock_api.calls['stop'] == []  # No API calls made
