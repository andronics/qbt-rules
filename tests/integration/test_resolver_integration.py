"""Integration tests for resolver with Config and Engine"""

import pytest
from pathlib import Path
import tempfile
import yaml

from qbt_rules.config import Config


class TestResolverConfigIntegration:
    """Test resolver integration with Config class"""

    def test_config_loads_and_resolves_rules_with_refs(self, tmp_path):
        """Should load config and resolve rules with refs block"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create rules.yml with refs
        rules_content = {
            'refs': {
                'vars': {
                    'min_ratio': 1.5,
                    'cleanup_age': '30 days',
                },
                'conditions': {
                    'well-seeded': {
                        'all': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'},
                            {'field': 'info.completion_on', 'operator': 'older_than', 'value': '${vars.cleanup_age}'}
                        ]
                    }
                },
                'actions': {
                    'safe-delete': [
                        {'type': 'add_tag', 'params': {'tags': ['pending-delete']}},
                        {'type': 'stop'}
                    ]
                }
            },
            'rules': [
                {
                    'name': 'Cleanup well-seeded torrents',
                    'enabled': True,
                    'conditions': [
                        {'$ref': 'conditions.well-seeded'}
                    ],
                    'actions': [
                        {'$ref': 'actions.safe-delete'}
                    ]
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get resolved rules
        rules = config.get_rules()

        # Verify resolution
        assert len(rules) == 1
        rule = rules[0]

        # Check refs were expanded
        assert '$ref' not in str(rule)
        assert 'all' in rule['conditions'][0]

        # Check variables were substituted
        assert rule['conditions'][0]['all'][0]['value'] == 1.5
        assert rule['conditions'][0]['all'][1]['value'] == '30 days'

        # Check actions were expanded -- the 2-item action sequence is spliced
        # into the parent list rather than nested as a single list element
        assert rule['actions'][0]['type'] == 'add_tag'
        assert rule['actions'][1]['type'] == 'stop'
        assert len(rule['actions']) == 2

    def test_config_handles_rules_without_refs(self, tmp_path):
        """Should handle rules without refs block (backward compatibility)"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create rules.yml WITHOUT refs
        rules_content = {
            'rules': [
                {
                    'name': 'Simple rule',
                    'enabled': True,
                    'conditions': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': 1.0}
                    ],
                    'actions': [
                        {'type': 'add_tag', 'params': {'tags': ['test']}}
                    ]
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get rules
        rules = config.get_rules()

        # Verify no changes
        assert len(rules) == 1
        assert rules[0]['conditions'][0]['value'] == 1.0

    def test_config_caches_resolved_rules(self, tmp_path):
        """Should cache resolved rules and reuse them"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create rules.yml with refs
        rules_content = {
            'refs': {
                'vars': {'min_ratio': 1.5},
                'conditions': {
                    'test': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}]}
                }
            },
            'rules': [
                {
                    'name': 'Test rule',
                    'enabled': True,
                    'conditions': [{'$ref': 'conditions.test'}],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get rules twice
        rules1 = config.get_rules()
        rules2 = config.get_rules()

        # Should return same cached object
        assert rules1 is rules2

    def test_config_invalidates_cache_on_reload(self, tmp_path):
        """Should invalidate cache when rules file is reloaded"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create initial rules.yml
        rules_file = config_dir / 'rules.yml'
        rules_content = {
            'refs': {'vars': {'min_ratio': 1.0}},
            'rules': [
                {
                    'name': 'Test',
                    'enabled': True,
                    'conditions': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}],
                    'actions': []
                }
            ]
        }
        with open(rules_file, 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get rules and verify
        rules1 = config.get_rules()
        assert rules1[0]['conditions'][0]['value'] == 1.0

        # Modify rules.yml
        import time
        time.sleep(0.01)  # Ensure mtime changes
        rules_content['refs']['vars']['min_ratio'] = 2.0
        with open(rules_file, 'w') as f:
            yaml.dump(rules_content, f)

        # Force reload by touching the file
        rules_file.touch()

        # Get rules again - should reload and re-resolve
        rules2 = config.get_rules()
        assert rules2[0]['conditions'][0]['value'] == 2.0

    def test_config_get_rules_raw_vs_resolved(self, tmp_path):
        """Should support getting raw vs resolved rules"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create rules.yml with refs
        rules_content = {
            'refs': {
                'vars': {'min_ratio': 1.5},
                'conditions': {
                    'test': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}]}
                }
            },
            'rules': [
                {
                    'name': 'Test rule',
                    'enabled': True,
                    'conditions': [{'$ref': 'conditions.test'}],
                    'actions': []
                }
            ]
        }
        with open(config_dir / 'rules.yml', 'w') as f:
            yaml.dump(rules_content, f)

        # Load config
        config = Config(config_dir=config_dir)

        # Get raw rules
        raw_rules = config.get_rules(resolved=False)
        assert '$ref' in str(raw_rules[0]['conditions'][0])

        # Get resolved rules
        resolved_rules = config.get_rules(resolved=True)
        assert '$ref' not in str(resolved_rules[0])
        assert resolved_rules[0]['conditions'][0]['all'][0]['value'] == 1.5

    def test_complex_multi_rule_resolution(self, tmp_path):
        """Should resolve multiple complex rules with shared refs"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create config.yml
        config_content = {
            'qbittorrent': {
                'host': 'http://localhost:8080',
                'username': 'admin',
                'password': 'adminpass'
            }
        }
        with open(config_dir / 'config.yml', 'w') as f:
            yaml.dump(config_content, f)

        # Create complex rules.yml
        rules_content = {
            'refs': {
                'vars': {
                    'min_ratio': 1.0,
                    'high_ratio': 2.5,
                    'cleanup_age': '30 days',
                    'protected_categories': ['keep', 'seedbox'],
                },
                'conditions': {
                    'private-tracker': {
                        'any': [
                            {'field': 'trackers.url', 'operator': 'contains', 'value': '.private'},
                            {'field': 'trackers.url', 'operator': 'contains', 'value': 'privatehd.to'}
                        ]
                    },
                    'well-seeded': {
                        'all': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'},
                            {'field': 'info.completion_on', 'operator': 'older_than', 'value': '${vars.cleanup_age}'}
                        ]
                    },
                    'protected': {
                        'any': [
                            {'field': 'info.category', 'operator': 'in', 'value': '${vars.protected_categories}'}
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
                    ]
                }
            },
            'rules': [
                {
                    'name': 'Cleanup well-seeded private torrents',
                    'enabled': True,
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
                    'name': 'Force seed private under ratio',
                    'enabled': True,
                    'conditions': [
                        {'$ref': 'conditions.private-tracker'},
                        {'all': [
                            {'field': 'info.ratio', 'operator': '<', 'value': '${vars.min_ratio}'}
                        ]}
                    ],
                    'actions': [
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
        rules = config.get_rules()

        # Verify both rules resolved correctly
        assert len(rules) == 2

        # Rule 1: Cleanup
        rule1 = rules[0]
        assert rule1['name'] == 'Cleanup well-seeded private torrents'
        assert 'any' in rule1['conditions'][0]  # private-tracker expanded
        assert 'all' in rule1['conditions'][1]  # well-seeded expanded
        assert rule1['conditions'][1]['all'][0]['value'] == 1.0  # Variable substituted
        assert rule1['conditions'][1]['all'][1]['value'] == '30 days'
        assert 'none' in rule1['conditions'][2]
        assert rule1['conditions'][2]['none'][0]['any'][0]['value'] == ['keep', 'seedbox']
        # actions.safe-delete (2 items) is spliced into the parent list
        assert rule1['actions'] == [
            {'type': 'add_tag', 'params': {'tags': ['pending-delete']}},
            {'type': 'stop'},
        ]

        # Rule 2: Force seed
        rule2 = rules[1]
        assert rule2['name'] == 'Force seed private under ratio'
        assert 'any' in rule2['conditions'][0]
        assert rule2['conditions'][1]['all'][0]['value'] == 1.0  # Variable substituted
        # actions.force-seed (2 items) is spliced into the parent list
        assert rule2['actions'] == [
            {'type': 'force_start'},
            {'type': 'add_tag', 'params': {'tags': ['force-seeding']}},
        ]
