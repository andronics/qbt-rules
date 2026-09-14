"""Integration tests for complete rule execution scenarios."""

import pytest
from unittest.mock import Mock, patch
from qbt_rules.engine import RulesEngine


# ============================================================================
# Real-World Rule Scenarios (20 tests)
# ============================================================================

class TestAutoCategorizationRules:
    """Test auto-categorization rule scenarios."""

    def test_categorize_hd_movies(self, mock_api, mock_config):
        """Auto-categorize HD movies by name pattern."""
        rule = {
            'name': 'Auto-categorize HD movies',
            'enabled': True,
            'stop_on_match': True,
            'conditions': {
                'all': [
                    {'field': 'info.name', 'operator': 'matches', 'value': r'(?i).*(1080p|2160p|4k).*'},
                ]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'Movies-HD'}},
                {'type': 'add_tag', 'params': {'tags': ['movies', 'hd']}},
            ]
        }

        torrent1 = {'hash': 'h1', 'name': 'Movie.1080p.BluRay', 'size': 5000000000, 'state': 'downloading', 'tags': '', 'category': '', 'ratio': 0.1}
        torrent2 = {'hash': 'h2', 'name': 'Regular.Movie', 'size': 1000000000, 'state': 'downloading', 'tags': '', 'category': '', 'ratio': 0.1}

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {torrent1['hash']: torrent1, torrent2['hash']: torrent2}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported')

        # Only HD torrent should match
        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['set_category']) == 1
        assert mock_api.calls['set_category'][0]['category'] == 'Movies-HD'

    def test_categorize_tv_shows(self, mock_api, mock_config):
        """Auto-categorize TV shows by pattern."""
        rule = {
            'name': 'Categorize TV shows',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.name', 'operator': 'matches', 'value': r'(?i).*[Ss]\d{2}[Ee]\d{2}.*'},
                ]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'TV-Shows'}},
            ]
        }

        torrent = {'hash': 'h1', 'name': 'Show.S01E05.720p', 'state': 'downloading', 'tags': '', 'category': '', 'ratio': 0}

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {torrent['hash']: torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported')

        assert engine.stats.rules_matched == 1
        assert mock_api.calls['set_category'][0]['category'] == 'TV-Shows'


class TestCleanupRules:
    """Test cleanup rule scenarios."""

    def test_delete_old_seeded_torrents(self, mock_api, mock_config, old_seeded_torrent):
        """Delete torrents that are old and well-seeded."""
        rule = {
            'name': 'Delete old seeded torrents',
            'enabled': True,
            'context': 'weekly-cleanup',
            'conditions': {
                'all': [
                    {'field': 'info.state', 'operator': 'in', 'value': ['uploading', 'pausedUP', 'stalledUP']},
                    {'field': 'info.completion_on', 'operator': 'older_than', 'value': '30 days'},
                    {'field': 'info.ratio', 'operator': '>=', 'value': 2.0},
                ]
            },
            'actions': [
                {'type': 'delete_torrent', 'params': {'keep_files': False}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {old_seeded_torrent['hash']: old_seeded_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['delete']) == 1
        assert mock_api.calls['delete'][0]['delete_files'] is True

    @patch('qbt_rules.engine.requests.post')
    def test_notify_after_delete_uses_correct_torrent_via_real_engine_loop(
        self, mock_post, mock_api, mock_config, old_seeded_torrent
    ):
        """
        Chaining regression test through the REAL RulesEngine.run() action
        loop (not a mocked shortcut): after delete_torrent removes the
        torrent, get_torrent(hash) genuinely returns None (MockQBittorrentAPI
        now implements it), so the engine sets torrent['_deleted']=True and
        leaves every other key untouched -- the following notify action in
        the same rule must still render the correct torrent name.
        """
        mock_response = Mock(status_code=200)
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        rule = {
            'name': 'Delete and notify',
            'enabled': True,
            'context': 'weekly-cleanup',
            'conditions': {
                'all': [
                    {'field': 'info.ratio', 'operator': '>=', 'value': 2.0},
                ]
            },
            'actions': [
                {'type': 'delete_torrent', 'params': {'delete_files': True}},
                {'type': 'notify', 'params': {
                    'service': 'generic',
                    'url': 'https://example.com/webhook',
                    'message': 'Deleted {name}',
                }},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {old_seeded_torrent['hash']: old_seeded_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['delete']) == 1
        assert old_seeded_torrent['hash'] not in mock_api.torrents_data  # really deleted

        mock_post.assert_called_once_with(
            'https://example.com/webhook',
            timeout=10,
            json={'message': f"Deleted {old_seeded_torrent['name']}"},
        )

    def test_delete_old_seeded_torrents_canonical_param(self, mock_api, mock_config, old_seeded_torrent):
        """Same as above, using the canonical delete_files param instead of deprecated keep_files."""
        rule = {
            'name': 'Delete old seeded torrents',
            'enabled': True,
            'context': 'weekly-cleanup',
            'conditions': {
                'all': [
                    {'field': 'info.state', 'operator': 'in', 'value': ['uploading', 'pausedUP', 'stalledUP']},
                    {'field': 'info.completion_on', 'operator': 'older_than', 'value': '30 days'},
                    {'field': 'info.ratio', 'operator': '>=', 'value': 2.0},
                ]
            },
            'actions': [
                {'type': 'delete_torrent', 'params': {'delete_files': True}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {old_seeded_torrent['hash']: old_seeded_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['delete']) == 1
        assert mock_api.calls['delete'][0]['delete_files'] is True

    def test_tag_ready_to_delete(self, mock_api, mock_config, old_seeded_torrent):
        """Tag torrents ready for deletion."""
        rule = {
            'name': 'Tag for deletion',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.ratio', 'operator': '>=', 'value': 3.0},
                    {'field': 'info.completion_on', 'operator': 'older_than', 'value': '60 days'},
                ]
            },
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['ready-to-delete']}},
                {'type': 'stop'},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {old_seeded_torrent['hash']: old_seeded_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['add_tags']) == 1
        assert len(mock_api.calls['stop']) == 1


class TestSeedingManagementRules:
    """Test seeding management scenarios."""

    def test_force_seed_underseed_content(self, mock_api, mock_config):
        """Force start torrents with low seed count."""
        rule = {
            'name': 'Force seed underseeded',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.num_complete', 'operator': '<=', 'value': 2},
                    {'field': 'info.state', 'operator': 'in', 'value': ['pausedUP', 'stalledUP']},
                ]
            },
            'actions': [
                {'type': 'force_start'},
                {'type': 'add_tag', 'params': {'tags': ['force-seed']}},
            ]
        }

        torrent = {
            'hash': 'h1',
            'name': 'Rare.Torrent',
            'state': 'pausedUP',
            'num_complete': 1,
            'num_seeds': 1,
            'tags': '',
            'ratio': 2.0,
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {torrent['hash']: torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['force_start']) == 1

    def test_stop_high_ratio_torrents(self, mock_api, mock_config, seeding_torrent):
        """Stop torrents that have reached target ratio."""
        rule = {
            'name': 'Stop high ratio',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.ratio', 'operator': '>=', 'value': 5.0},
                    {'field': 'info.state', 'operator': 'in', 'value': ['uploading', 'forcedUP']},
                ]
            },
            'actions': [
                {'type': 'stop'},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {seeding_torrent['hash']: seeding_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['stop']) == 1


class TestSizeBasedRules:
    """Test size-based rule scenarios."""

    def test_pause_large_downloads(self, mock_api, mock_config, large_torrent):
        """Pause very large downloads."""
        rule = {
            'name': 'Pause very large downloads',
            'enabled': True,
            'context': 'torrent-imported',
            'conditions': {
                'all': [
                    {'field': 'info.size', 'operator': 'larger_than', 'value': '50 GB'},
                    {'field': 'info.state', 'operator': 'in', 'value': ['downloading', 'metaDL']},
                ]
            },
            'actions': [
                {'type': 'stop'},
                {'type': 'add_tag', 'params': {'tags': ['large-download']}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {large_torrent['hash']: large_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['stop']) == 1

    def test_priority_small_files(self, mock_api, mock_config, small_torrent):
        """Give priority to small files."""
        rule = {
            'name': 'Priority for small files',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.size', 'operator': 'smaller_than', 'value': '100 MB'},
                ]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'small'}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {small_torrent['hash']: small_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 1


class TestSpeedLimitRules:
    """Test speed limit rule scenarios."""

    def test_limit_upload_speed_during_day(self, mock_api, mock_config, seeding_torrent):
        """Limit upload speed for seeding torrents."""
        rule = {
            'name': 'Limit upload speed',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.state', 'operator': 'in', 'value': ['uploading', 'forcedUP']},
                ]
            },
            'actions': [
                {'type': 'set_upload_limit', 'params': {'limit': 1048576}},  # 1 MB/s
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {seeding_torrent['hash']: seeding_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1
        assert len(mock_api.calls['set_upload_limit']) == 1
        assert mock_api.calls['set_upload_limit'][0]['limit'] == 1048576

    def test_limit_download_speed_large_files(self, mock_api, mock_config, large_torrent):
        """Limit download speed for large files."""
        rule = {
            'name': 'Limit large downloads',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.size', 'operator': 'larger_than', 'value': '20 GB'},
                    {'field': 'info.state', 'operator': '==', 'value': 'downloading'},
                ]
            },
            'actions': [
                {'type': 'set_download_limit', 'params': {'limit': 2097152}},  # 2 MB/s
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {large_torrent['hash']: large_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='weekly-cleanup')

        assert engine.stats.rules_matched == 1


class TestComplexConditionRules:
    """Test rules with complex condition logic."""

    def test_nested_any_all_conditions(self, mock_api, mock_config, seeding_torrent, old_seeded_torrent):
        """Complex rule with nested any/all conditions."""
        rule = {
            'name': 'Complex cleanup rule',
            'enabled': True,
            'conditions': {
                'all': [
                    {'field': 'info.state', 'operator': 'in', 'value': ['uploading', 'stalledUP', 'pausedUP']},
                    {
                        'any': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': 5.0},
                            {'field': 'info.completion_on', 'operator': 'older_than', 'value': '90 days'},
                        ]
                    }
                ]
            },
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['cleanup-candidate']}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {
            seeding_torrent['hash']: seeding_torrent,  # ratio 5.0 - matches
            old_seeded_torrent['hash']: old_seeded_torrent,  # old - matches
        }

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both should match
        assert engine.stats.rules_matched == 2

    def test_none_condition_logic(self, mock_api, mock_config, sample_torrent):
        """Rule with none (NOT) condition logic."""
        rule = {
            'name': 'Not paused torrents',
            'enabled': True,
            'conditions': {
                'none': [
                    {'field': 'info.state', 'operator': 'contains', 'value': 'paused'},
                ]
            },
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['active']}},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.rules_matched == 1


class TestMultipleActionRules:
    """Test rules with multiple actions."""

    def test_multiple_actions_executed_in_order(self, mock_api, mock_config, sample_torrent):
        """Multiple actions are executed in order."""
        rule = {
            'name': 'Multi-action rule',
            'enabled': True,
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'processed'}},
                {'type': 'add_tag', 'params': {'tags': ['step1']}},
                {'type': 'add_tag', 'params': {'tags': ['step2']}},
                {'type': 'reannounce'},
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        assert engine.stats.actions_executed == 4

    def test_action_failure_continues_to_next_action(self, mock_api, mock_config, sample_torrent):
        """If one action fails, continue with next actions."""
        mock_api.set_category = Mock(return_value=False)  # This will fail

        rule = {
            'name': 'Multi-action with failure',
            'enabled': True,
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'test'}},  # Fails
                {'type': 'add_tag', 'params': {'tags': ['still-runs']}},  # Should still execute
            ]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # First action fails, second succeeds
        assert engine.stats.errors == 1
        assert engine.stats.actions_executed == 1


class TestContextFiltering:
    """Test trigger-based rule filtering."""

    def test_on_added_context_filtering(self, mock_api, mock_config, sample_torrent):
        """Rules filter by trigger."""
        rule1 = {
            'name': 'On added rule',
            'enabled': True,
            'context': 'torrent-imported',
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]
            },
            'actions': [{'type': 'add_tag', 'params': {'tags': ['on-added']}}]
        }
        rule2 = {
            'name': 'Scheduled rule',
            'enabled': True,
            'context': 'weekly-cleanup',
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 0}]
            },
            'actions': [{'type': 'add_tag', 'params': {'tags': ['weekly-cleanup']}}]
        }

        mock_config.get_rules = Mock(return_value=[rule1, rule2])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='torrent-imported')

        # Only torrent-imported rule should match
        assert engine.stats.rules_matched == 1
        assert mock_api.calls['add_tags'][0]['tags'][0] == 'on-added'

    def test_multiple_context_values(self, mock_api, mock_config, sample_torrent):
        """Rule can match multiple triggers."""
        rule = {
            'name': 'Multi-trigger rule',
            'enabled': True,
            'context': ['torrent-imported', 'download-finished'],
            'conditions': {
                'all': [{'field': 'info.name', 'operator': 'contains', 'value': 'Example'}]
            },
            'actions': [{'type': 'add_tag', 'params': {'tags': ['processed']}}]
        }

        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {sample_torrent['hash']: sample_torrent}

        engine = RulesEngine(mock_api, mock_config)

        # Should match torrent-imported
        engine.run(context='torrent-imported')
        assert engine.stats.rules_matched == 1

        # Reset stats and test download-finished
        engine.stats.rules_matched = 0
        engine.run(context='download-finished')
        assert engine.stats.rules_matched == 1


class TestIdempotencyInIntegration:
    """Test idempotency in real scenarios."""

    def test_idempotent_actions_skipped_on_rerun(self, mock_api, mock_config):
        """Idempotent actions are skipped on second run."""
        rule = {
            'name': 'Categorize rule',
            'enabled': True,
            'conditions': {
                'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]
            },
            'actions': [
                {'type': 'set_category', 'params': {'category': 'processed'}},
            ]
        }

        torrent = {'hash': 'h1', 'name': 'Test', 'ratio': 2.0, 'category': '', 'tags': '', 'state': 'uploading'}
        mock_config.get_rules = Mock(return_value=[rule])
        mock_api.torrents_data = {torrent['hash']: torrent}

        engine = RulesEngine(mock_api, mock_config)

        # First run - executes
        engine.run(context='adhoc-run')
        assert engine.stats.actions_executed == 1
        assert engine.stats.actions_skipped == 0

        # Simulate category being set
        mock_api.torrents_data['h1']['category'] = 'processed'

        # Second run - skipped
        engine.stats = type(engine.stats)()  # Reset stats
        engine.run(context='adhoc-run')
        assert engine.stats.actions_executed == 0
        assert engine.stats.actions_skipped == 1


class TestRealWorldCompleteScenario:
    """Test complete real-world automation scenario."""

    def test_complete_automation_workflow(self, mock_api, mock_config):
        """Complete automation workflow with multiple rules and torrents."""
        # Define rules
        rules = [
            {
                'name': 'Auto-categorize new downloads',
                'enabled': True,
                'stop_on_match': False,
                'context': 'torrent-imported',
                'conditions': {
                    'all': [{'field': 'info.name', 'operator': 'matches', 'value': r'(?i).*1080p.*'}]
                },
                'actions': [
                    {'type': 'set_category', 'params': {'category': 'HD'}},
                    {'type': 'add_tag', 'params': {'tags': ['new', 'hd']}},
                ]
            },
            {
                'name': 'Cleanup old torrents',
                'enabled': True,
                'stop_on_match': True,
                'context': 'weekly-cleanup',
                'conditions': {
                    'all': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': 3.0},
                        {'field': 'info.completion_on', 'operator': 'older_than', 'value': '60 days'},
                    ]
                },
                'actions': [
                    {'type': 'add_tag', 'params': {'tags': ['old']}},
                    {'type': 'delete_torrent', 'params': {'keep_files': True}},
                ]
            },
        ]

        # Define torrents
        torrents = {
            'new_hd': {'hash': 'h1', 'name': 'New.Movie.1080p', 'state': 'downloading', 'ratio': 0, 'completion_on': -1, 'category': '', 'tags': ''},
            'old': {'hash': 'h2', 'name': 'Old.File', 'state': 'uploading', 'ratio': 4.0, 'completion_on': 1600000000, 'category': '', 'tags': ''},
        }

        mock_config.get_rules = Mock(return_value=rules)
        mock_api.torrents_data = torrents

        engine = RulesEngine(mock_api, mock_config)

        # Simulate torrent-imported trigger for new torrent
        engine.run(context='torrent-imported', torrent_hash='h1')
        assert engine.stats.rules_matched == 1

        # Reset and simulate weekly-cleanup trigger
        engine.stats = type(engine.stats)()
        engine.run(context='weekly-cleanup')
        assert engine.stats.rules_matched == 1  # Old torrent matches cleanup rule


class TestRuleChainingWithCacheUpdates:
    """Test that later rules see changes made by earlier rules in the same execution."""

    def test_tag_based_rule_chaining(self, mock_api, mock_config):
        """Later rules should see tags added by earlier rules in the same execution."""
        # Rule 1: Tag large torrents
        # Rule 2: Stop torrents with 'large' tag (should see tag from Rule 1)
        rules = [
            {
                'name': 'Tag large torrents',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.size', 'operator': 'larger_than', 'value': '10 GB'}
                    ]
                },
                'actions': [
                    {'type': 'add_tag', 'params': {'tags': ['large']}}
                ]
            },
            {
                'name': 'Stop large torrents',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.tags', 'operator': 'contains', 'value': 'large'}
                    ]
                },
                'actions': [
                    {'type': 'stop'}
                ]
            }
        ]

        # Torrent starts without 'large' tag
        torrent = {
            'hash': 'h1',
            'name': 'Big.File',
            'size': 15000000000,  # 15 GB
            'tags': '',  # No tags initially
            'state': 'downloading',
            'ratio': 0.0,
            'category': ''
        }

        mock_config.get_rules = Mock(return_value=rules)
        mock_api.torrents_data = {torrent['hash']: torrent}

        # Mock get_torrent to return updated torrent with tag after Rule 1
        def get_torrent_side_effect(hash):
            if hash == 'h1':
                # Return updated torrent with tag
                return {
                    'hash': 'h1',
                    'name': 'Big.File',
                    'size': 15000000000,
                    'tags': 'large',  # Tag added by Rule 1
                    'state': 'downloading',
                    'ratio': 0.0,
                    'category': ''
                }
            return None

        mock_api.get_torrent = Mock(side_effect=get_torrent_side_effect)

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Both rules should match
        assert engine.stats.rules_matched == 2, "Both Rule 1 (size check) and Rule 2 (tag check) should match"

        # Rule 1 should have added the tag
        assert len(mock_api.calls['add_tags']) == 1
        assert 'large' in mock_api.calls['add_tags'][0]['tags']

        # Rule 2 should have stopped the torrent (because it saw the tag)
        assert len(mock_api.calls['stop']) == 1

        # Cache should have been updated (get_torrent called after Rule 1 action)
        assert mock_api.get_torrent.called

    def test_multiple_tag_additions_in_sequence(self, mock_api, mock_config):
        """Multiple rules can add tags and later rules see all accumulated tags."""
        rules = [
            {
                'name': 'Tag by tracker',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'trackers.url', 'operator': 'contains', 'value': 'private-tracker.com'}
                    ]
                },
                'actions': [
                    {'type': 'add_tag', 'params': {'tags': ['private']}}
                ]
            },
            {
                'name': 'Tag by size',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.size', 'operator': 'larger_than', 'value': '5 GB'}
                    ]
                },
                'actions': [
                    {'type': 'add_tag', 'params': {'tags': ['large']}}
                ]
            },
            {
                'name': 'Force start private large torrents',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.tags', 'operator': 'contains', 'value': 'private'},
                        {'field': 'info.tags', 'operator': 'contains', 'value': 'large'}
                    ]
                },
                'actions': [
                    {'type': 'force_start'}
                ]
            }
        ]

        torrent = {
            'hash': 'h1',
            'name': 'Big.Private.File',
            'size': 10000000000,  # 10 GB
            'tags': '',
            'state': 'paused',
            'ratio': 0.0,
            'category': ''
        }

        trackers = [
            {'url': 'http://private-tracker.com/announce', 'status': 2}
        ]

        mock_config.get_rules = Mock(return_value=rules)
        mock_api.torrents_data = {torrent['hash']: torrent}
        mock_api.get_trackers = Mock(return_value=trackers)

        # Mock get_torrent to simulate tag accumulation
        call_count = [0]

        def get_torrent_accumulate_tags(hash):
            call_count[0] += 1
            if hash == 'h1':
                # First call: after 'private' tag added
                if call_count[0] == 1:
                    return {**torrent, 'tags': 'private'}
                # Second call: after 'large' tag added
                elif call_count[0] == 2:
                    return {**torrent, 'tags': 'private,large'}
            return None

        mock_api.get_torrent = Mock(side_effect=get_torrent_accumulate_tags)

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # All three rules should match
        assert engine.stats.rules_matched == 3

        # Tags should have been added by Rules 1 and 2
        assert len(mock_api.calls['add_tags']) == 2

        # Rule 3 should have force started (because both tags present)
        assert len(mock_api.calls['force_start']) == 1

    def test_deleted_torrent_skipped_by_later_rules(self, mock_api, mock_config):
        """If a rule deletes a torrent, later rules should skip it."""
        rules = [
            {
                'name': 'Delete bad torrents',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.name', 'operator': 'contains', 'value': 'malware'}
                    ]
                },
                'actions': [
                    {'type': 'delete_torrent', 'params': {'keep_files': False}}
                ]
            },
            {
                'name': 'Tag all torrents',
                'enabled': True,
                'conditions': {
                    'all': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': 0}
                    ]
                },
                'actions': [
                    {'type': 'add_tag', 'params': {'tags': ['processed']}}
                ]
            }
        ]

        torrent = {
            'hash': 'h1',
            'name': 'malware.exe',
            'size': 1000000,
            'tags': '',
            'state': 'downloading',
            'ratio': 0.5,
            'category': ''
        }

        mock_config.get_rules = Mock(return_value=rules)
        mock_api.torrents_data = {torrent['hash']: torrent}

        # Mock get_torrent to return None after deletion
        mock_api.get_torrent = Mock(return_value=None)

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context='adhoc-run')

        # Only Rule 1 should match (Rule 2 should skip deleted torrent)
        assert engine.stats.rules_matched == 1

        # Torrent should have been deleted
        assert len(mock_api.calls['delete']) == 1

        # Tag should NOT have been added (torrent was deleted)
        assert len(mock_api.calls.get('add_tags', [])) == 0
