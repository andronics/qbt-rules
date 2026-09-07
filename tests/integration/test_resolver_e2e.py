"""End-to-end tests simulating real-world resolver usage"""

import pytest
import tempfile
import yaml
from pathlib import Path

from qbt_rules.config import Config
from qbt_rules.engine import RulesEngine


class TestResolverRealWorldScenarios:
    """Test real-world usage scenarios with actual Config and Engine"""

    def test_complete_workflow_with_resolver(self, tmp_path):
        """Test complete workflow: Config → Resolver → Engine"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create realistic config
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create realistic rules with resolver
        rules_content = {
            'refs': {
                'vars': {
                    'min_ratio': 1.5,
                    'high_ratio': 3.0,
                    'cleanup_age': '30 days',
                    'protected_categories': ['keep', 'seedbox', 'long-term'],
                    'hd_pattern': '(?i).*(1080p|2160p|4k).*',
                },
                'conditions': {
                    'private-tracker': {
                        'any': [
                            {'field': 'trackers.url', 'operator': 'contains', 'value': 'privatehd.to'},
                            {'field': 'trackers.url', 'operator': 'contains', 'value': 'torrentleech.org'},
                            {'field': 'trackers.url', 'operator': 'contains', 'value': 'iptorrents.com'}
                        ]
                    },
                    'well-seeded': {
                        'all': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'},
                            {'field': 'info.completion_on', 'operator': 'older_than', 'value': '${vars.cleanup_age}'}
                        ]
                    },
                    'highly-seeded': {
                        'all': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.high_ratio}'},
                            {'field': 'info.seeding_time', 'operator': '>', 'value': 604800}
                        ]
                    },
                    'hd-content': {
                        'all': [
                            {'field': 'info.name', 'operator': 'matches', 'value': '${vars.hd_pattern}'}
                        ]
                    },
                    'protected': {
                        'any': [
                            {'field': 'info.category', 'operator': 'in', 'value': '${vars.protected_categories}'},
                            {'field': 'info.tags', 'operator': 'contains', 'value': 'keep'}
                        ]
                    },
                    'no-activity': {
                        'all': [
                            {'field': 'info.num_leechs', 'operator': '==', 'value': 0},
                            {'field': 'info.num_seeds', 'operator': '<=', 'value': 2}
                        ]
                    }
                },
                'actions': {
                    'safe-delete': [
                        {'type': 'add_tag', 'params': {'tags': ['pending-delete']}},
                        {'type': 'stop'}
                    ],
                    'force-seed': [
                        {'type': 'force_start'},
                        {'type': 'add_tag', 'params': {'tags': ['force-seeding']}}
                    ],
                    'tag-hd-content': [
                        {'type': 'add_tag', 'params': {'tags': ['hd', 'quality']}},
                        {'type': 'set_category', 'params': {'category': 'hd-content'}}
                    ],
                    'pause-low-activity': [
                        {'type': 'stop'},
                        {'type': 'add_tag', 'params': {'tags': ['paused-low-activity']}}
                    ]
                }
            },
            'rules': [
                {
                    'name': 'Cleanup well-seeded private tracker torrents',
                    'enabled': True,
                    'priority': 50,
                    'context': 'weekly-cleanup',
                    'conditions': [
                        {'$ref': 'conditions.private-tracker'},
                        {'$ref': 'conditions.well-seeded'},
                        {'none': [{'$ref': 'conditions.protected'}]}
                    ],
                    'actions': [
                        {'$ref': 'actions.safe-delete'}
                    ]
                },
                {
                    'name': 'Force seed private tracker under ratio',
                    'enabled': True,
                    'priority': 100,
                    'context': 'download-finished',
                    'conditions': [
                        {'$ref': 'conditions.private-tracker'},
                        {'all': [
                            {'field': 'info.ratio', 'operator': '<', 'value': '${vars.min_ratio}'}
                        ]}
                    ],
                    'actions': [
                        {'$ref': 'actions.force-seed'}
                    ]
                },
                {
                    'name': 'Tag HD content from private trackers',
                    'enabled': True,
                    'priority': 75,
                    'context': 'torrent-imported',
                    'conditions': [
                        {'$ref': 'conditions.private-tracker'},
                        {'$ref': 'conditions.hd-content'}
                    ],
                    'actions': [
                        {'$ref': 'actions.tag-hd-content'}
                    ]
                },
                {
                    'name': 'Pause highly seeded torrents with no activity',
                    'enabled': True,
                    'priority': 25,
                    'conditions': [
                        {'$ref': 'conditions.highly-seeded'},
                        {'$ref': 'conditions.no-activity'},
                        {'none': [{'$ref': 'conditions.protected'}]}
                    ],
                    'actions': [
                        {'$ref': 'actions.pause-low-activity'}
                    ]
                },
                {
                    'name': 'Mixed rule with refs and inline conditions',
                    'enabled': True,
                    'priority': 60,
                    'conditions': [
                        {'$ref': 'conditions.private-tracker'},
                        {'all': [
                            {'field': 'info.size', 'operator': '>', 'value': 10737418240},
                            {'field': 'info.state', 'operator': '==', 'value': 'uploading'}
                        ]},
                        {'$ref': 'conditions.hd-content'}
                    ],
                    'actions': [
                        {'type': 'add_tag', 'params': {'tags': ['large-hd-upload']}},
                        {'$ref': 'actions.force-seed'}
                    ]
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get resolved rules
        resolved_rules = config.get_rules(resolved=True)

        # Verify all 5 rules resolved
        assert len(resolved_rules) == 5

        # Verify Rule 1: Cleanup well-seeded
        rule1 = resolved_rules[0]
        assert rule1['name'] == 'Cleanup well-seeded private tracker torrents'
        assert rule1['priority'] == 50
        # Verify ref expansion
        assert 'any' in rule1['conditions'][0]  # private-tracker expanded
        assert len(rule1['conditions'][0]['any']) == 3
        assert 'all' in rule1['conditions'][1]  # well-seeded expanded
        assert 'none' in rule1['conditions'][2]
        # Verify variable substitution
        assert rule1['conditions'][1]['all'][0]['value'] == 1.5  # min_ratio
        assert rule1['conditions'][1]['all'][1]['value'] == '30 days'  # cleanup_age
        assert rule1['conditions'][2]['none'][0]['any'][0]['value'] == ['keep', 'seedbox', 'long-term']
        # Verify action expansion -- actions.safe-delete (2 items) is spliced
        # into the parent actions list, not nested as a single list element
        assert rule1['actions'][0]['type'] == 'add_tag'
        assert rule1['actions'][1]['type'] == 'stop'
        assert len(rule1['actions']) == 2

        # Verify Rule 2: Force seed under ratio
        rule2 = resolved_rules[1]
        assert rule2['name'] == 'Force seed private tracker under ratio'
        assert rule2['conditions'][1]['all'][0]['value'] == 1.5  # Variable substituted
        assert rule2['actions'][0]['type'] == 'force_start'

        # Verify Rule 3: Tag HD content
        rule3 = resolved_rules[2]
        assert rule3['name'] == 'Tag HD content from private trackers'
        # Verify pattern substitution
        assert '1080p' in rule3['conditions'][1]['all'][0]['value']
        assert rule3['actions'][1]['params']['category'] == 'hd-content'

        # Verify Rule 4: Pause highly seeded
        rule4 = resolved_rules[3]
        assert rule4['conditions'][0]['all'][0]['value'] == 3.0  # high_ratio

        # Verify Rule 5: Mixed rule
        rule5 = resolved_rules[4]
        assert rule5['name'] == 'Mixed rule with refs and inline conditions'
        # Has both expanded refs and inline conditions
        assert 'any' in rule5['conditions'][0]  # Expanded ref
        assert 'all' in rule5['conditions'][1]  # Inline condition
        assert rule5['conditions'][1]['all'][0]['value'] == 10737418240  # Inline value
        # Has both expanded action and inline action -- the ref's 2 items are
        # spliced in after the inline action, not nested as a single list
        assert rule5['actions'][0]['type'] == 'add_tag'  # Inline
        assert rule5['actions'][1]['type'] == 'force_start'  # Expanded ref, item 1
        assert rule5['actions'][2]['type'] == 'add_tag'  # Expanded ref, item 2
        assert len(rule5['actions']) == 3

        # Verify raw rules still have $ref and ${vars.*}
        raw_rules = config.get_rules(resolved=False)
        assert '$ref' in str(raw_rules[0])
        assert '${vars.min_ratio}' in str(raw_rules[1])

    def test_resolver_with_multiple_variable_types(self, tmp_path):
        """Test all variable types in realistic scenario"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        rules_content = {
            'refs': {
                'vars': {
                    # Different types
                    'ratio_float': 1.5,
                    'ratio_int': 2,
                    'size_bytes': 10737418240,
                    'age_string': '30 days',
                    'category_list': ['movies', 'tv', 'music'],
                    'enabled_bool': True,
                    'disabled_bool': False,
                    'null_value': None,
                    'empty_string': '',
                    'pattern': '(?i).*(s\\d{2}e\\d{2}).*',
                    'config_dict': {'timeout': 30, 'retries': 3}
                }
            },
            'rules': [
                {
                    'name': 'Test all types',
                    'enabled': True,
                    'conditions': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.ratio_float}'},
                        {'field': 'info.ratio', 'operator': '<', 'value': '${vars.ratio_int}'},
                        {'field': 'info.size', 'operator': '>', 'value': '${vars.size_bytes}'},
                        {'field': 'info.added_on', 'operator': 'older_than', 'value': '${vars.age_string}'},
                        {'field': 'info.category', 'operator': 'in', 'value': '${vars.category_list}'},
                        {'field': 'info.name', 'operator': 'matches', 'value': '${vars.pattern}'},
                    ],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        config = Config(config_dir=config_dir)
        resolved = config.get_rules()[0]

        # Verify types are preserved
        assert resolved['conditions'][0]['value'] == 1.5
        assert type(resolved['conditions'][0]['value']) == float

        assert resolved['conditions'][1]['value'] == 2
        assert type(resolved['conditions'][1]['value']) == int

        assert resolved['conditions'][2]['value'] == 10737418240
        assert type(resolved['conditions'][2]['value']) == int

        assert resolved['conditions'][3]['value'] == '30 days'
        assert type(resolved['conditions'][3]['value']) == str

        assert resolved['conditions'][4]['value'] == ['movies', 'tv', 'music']
        assert type(resolved['conditions'][4]['value']) == list

        assert '(?i)' in resolved['conditions'][5]['value']

    def test_resolver_caching_behavior(self, tmp_path):
        """Test that resolved rules are cached correctly"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        rules_file = config_dir / 'rules.yml'
        rules_content = {
            'refs': {
                'vars': {'ratio': 1.0}
            },
            'rules': [
                {
                    'name': 'Test',
                    'enabled': True,
                    'conditions': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.ratio}'}
                    ],
                    'actions': []
                }
            ]
        }
        with open(rules_file, 'w') as f:
            yaml.dump(rules_content, f)

        config = Config(config_dir=config_dir)

        # First call - should resolve and cache
        rules1 = config.get_rules()
        assert rules1[0]['conditions'][0]['value'] == 1.0

        # Second call - should return cached
        rules2 = config.get_rules()
        assert rules2 is rules1  # Same object

        # Modify file
        import time
        time.sleep(0.01)
        rules_content['refs']['vars']['ratio'] = 2.0
        with open(rules_file, 'w') as f:
            yaml.dump(rules_content, f)
        rules_file.touch()  # Force mtime update

        # Third call - should reload and re-resolve
        rules3 = config.get_rules()
        assert rules3[0]['conditions'][0]['value'] == 2.0
        assert rules3 is not rules1  # Different object

    def test_error_handling_in_real_scenario(self, tmp_path):
        """Test error handling with realistic mistakes"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Test 1: Unknown variable
        rules_content = {
            'refs': {
                'vars': {'ratio': 1.0}
            },
            'rules': [
                {
                    'name': 'Test',
                    'enabled': True,
                    'conditions': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.missing_var}'}
                    ],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        config = Config(config_dir=config_dir)
        from qbt_rules.errors import UnknownVariableError
        with pytest.raises(UnknownVariableError) as exc_info:
            config.get_rules()
        assert 'missing_var' in str(exc_info.value)
        assert 'ratio' in str(exc_info.value)  # Shows available vars

        # Test 2: Unknown reference
        rules_content = {
            'refs': {
                'conditions': {
                    'existing': {'all': []}
                }
            },
            'rules': [
                {
                    'name': 'Test',
                    'enabled': True,
                    'conditions': [
                        {'$ref': 'conditions.nonexistent'}
                    ],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        config = Config(config_dir=config_dir)
        from qbt_rules.errors import UnknownRefError
        with pytest.raises(UnknownRefError) as exc_info:
            config.get_rules()
        assert 'nonexistent' in str(exc_info.value)
        assert 'existing' in str(exc_info.value)  # Shows available refs

        # Test 3: Invalid ref format
        rules_content = {
            'refs': {
                'conditions': {'test': {}}
            },
            'rules': [
                {
                    'name': 'Test',
                    'enabled': True,
                    'conditions': [
                        {'$ref': 'test'}  # Missing group prefix
                    ],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        config = Config(config_dir=config_dir)
        from qbt_rules.errors import InvalidRefError
        with pytest.raises(InvalidRefError) as exc_info:
            config.get_rules()
        assert 'group.name' in str(exc_info.value)
