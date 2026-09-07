"""Unit tests for RuleResolver"""

import pytest

from qbt_rules.resolver import RuleResolver
from qbt_rules.errors import (
    InvalidRefError,
    UnknownRefError,
    InvalidVariableError,
    UnknownVariableError,
    CircularRefError,
)


class TestRuleResolverInit:
    """Test resolver initialization"""

    def test_init_empty_refs(self):
        """Should handle empty refs block"""
        resolver = RuleResolver(refs={})
        assert resolver.vars == {}
        assert resolver.conditions == {}
        assert resolver.actions == {}

    def test_init_with_vars(self):
        """Should extract vars from refs"""
        refs = {
            'vars': {
                'min_ratio': 1.0,
                'cleanup_age': '30 days',
            }
        }
        resolver = RuleResolver(refs=refs)
        assert resolver.vars == {'min_ratio': 1.0, 'cleanup_age': '30 days'}

    def test_init_with_conditions(self):
        """Should extract conditions from refs"""
        refs = {
            'conditions': {
                'private-tracker': {
                    'any': [
                        {'field': 'trackers.url', 'operator': 'contains', 'value': 'private'}
                    ]
                }
            }
        }
        resolver = RuleResolver(refs=refs)
        assert 'private-tracker' in resolver.conditions

    def test_init_with_actions(self):
        """Should extract actions from refs"""
        refs = {
            'actions': {
                'safe-delete': [
                    {'type': 'add_tag', 'params': {'tags': ['pending-delete']}}
                ]
            }
        }
        resolver = RuleResolver(refs=refs)
        assert 'safe-delete' in resolver.actions

    def test_init_with_instance_overrides(self):
        """Should apply instance variable overrides"""
        refs = {
            'vars': {
                'min_ratio': 1.0,
                'cleanup_age': '30 days',
            }
        }
        instances = {
            'seedbox': {
                'refs': {
                    'vars': {
                        'min_ratio': 2.0,
                    }
                }
            }
        }
        resolver = RuleResolver(refs=refs, instance_id='seedbox', instances=instances)
        assert resolver.vars['min_ratio'] == 2.0
        assert resolver.vars['cleanup_age'] == '30 days'


class TestVariableSubstitution:
    """Test ${vars.*} variable substitution"""

    def test_substitute_scalar_value(self):
        """Should substitute scalar variable and preserve type"""
        refs = {'vars': {'min_ratio': 1.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == 1.0  # Float preserved

    def test_substitute_string_value(self):
        """Should substitute string variable"""
        refs = {'vars': {'cleanup_age': '30 days'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.added_on', 'operator': 'older_than', 'value': '${vars.cleanup_age}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == '30 days'

    def test_substitute_list_value(self):
        """Should substitute list variable and preserve type"""
        refs = {'vars': {'protected_categories': ['keep', 'archive']}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.category', 'operator': 'in', 'value': '${vars.protected_categories}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == ['keep', 'archive']

    def test_substitute_embedded_in_string(self):
        """Should interpolate variable when embedded in string"""
        refs = {'vars': {'min_ratio': 1.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['ratio-${vars.min_ratio}']}}
            ]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'][0]['params']['tags'][0] == 'ratio-1.0'

    def test_substitute_multiple_vars_in_string(self):
        """Should substitute multiple variables in single string"""
        refs = {'vars': {'min_ratio': 1.0, 'max_ratio': 2.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['${vars.min_ratio}-to-${vars.max_ratio}']}}
            ]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'][0]['params']['tags'][0] == '1.0-to-2.0'

    def test_unknown_variable_raises_error(self):
        """Should raise UnknownVariableError for undefined variable"""
        refs = {'vars': {'min_ratio': 1.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.unknown}'}
            ],
            'actions': []
        }

        with pytest.raises(UnknownVariableError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'unknown' in str(exc_info.value)

    def test_invalid_variable_path_raises_error(self):
        """Should raise InvalidVariableError for invalid path format"""
        refs = {'vars': {'min_ratio': 1.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': '${min_ratio}'}  # Missing 'vars.'
            ],
            'actions': []
        }

        with pytest.raises(InvalidVariableError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'vars.name' in str(exc_info.value)


class TestReferenceExpansion:
    """Test $ref: path reference expansion"""

    def test_expand_condition_ref(self):
        """Should expand condition reference"""
        refs = {
            'conditions': {
                'private-tracker': {
                    'any': [
                        {'field': 'trackers.url', 'operator': 'contains', 'value': 'private'}
                    ]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.private-tracker'}],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0] == refs['conditions']['private-tracker']

    def test_expand_action_ref(self):
        """Should expand and splice action reference (actions.* refs are lists;
        the ref's items become siblings in the parent actions list, not a
        single nested list -- otherwise the engine can't iterate them as
        individual action dicts)"""
        refs = {
            'actions': {
                'safe-delete': [
                    {'type': 'add_tag', 'params': {'tags': ['pending-delete']}},
                    {'type': 'stop'}
                ]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [{'$ref': 'actions.safe-delete'}]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'] == refs['actions']['safe-delete']
        assert all(isinstance(a, dict) for a in resolved['actions'])

    def test_expand_action_ref_mixed_with_inline_actions(self):
        """A ref mixed with inline actions in the same list should splice
        the ref's items in place, not nest them (regression test: this exact
        shape crashed the engine's ActionExecutor with
        `TypeError: list indices must be integers or slices, not str`,
        since it tried to treat the nested list as a single action dict)"""
        refs = {
            'actions': {
                'tag-private': [
                    {'type': 'add_tag', 'params': {'tags': ['private']}},
                ],
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'Tag iptorrent.com Trackers',
            'conditions': [],
            'actions': [
                {'$ref': 'actions.tag-private'},
                {'type': 'add_tag', 'params': {'tags': ['iptorrent.com']}},
            ],
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'] == [
            {'type': 'add_tag', 'params': {'tags': ['private']}},
            {'type': 'add_tag', 'params': {'tags': ['iptorrent.com']}},
        ]
        assert all(isinstance(a, dict) for a in resolved['actions'])

    def test_expand_action_ref_single_item_list(self):
        """A ref to a single-item action list must still be a flat dict at
        that position, not a 1-item list (regression: this shape also
        crashed the engine even with no inline actions mixed in)"""
        refs = {
            'actions': {
                'force-seed-private': [
                    {'type': 'force_start'},
                    {'type': 'set_upload_limit', 'params': {'limit': -1}},
                    {'type': 'add_tag', 'params': {'tags': ['force-seeding']}},
                ],
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'Force Seed Under-Ratio Private Torrents',
            'conditions': [],
            'actions': [{'$ref': 'actions.force-seed-private'}],
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'] == refs['actions']['force-seed-private']
        assert all(isinstance(a, dict) for a in resolved['actions'])

    def test_condition_ref_still_nests_as_single_item(self):
        """Sanity check that the splice behavior is specific to actions.*
        refs (which are lists) and doesn't affect conditions.* refs (which
        are dicts) -- a condition ref should still nest as exactly one item
        in the parent conditions list, unchanged from before this fix"""
        refs = {
            'conditions': {
                'under-seeded-private': {
                    'all': [{'field': 'info.ratio', 'operator': '<', 'value': 1.0}]
                },
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.under-seeded-private'}],
            'actions': [],
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'] == [refs['conditions']['under-seeded-private']]

    def test_literal_nested_list_not_flattened(self):
        """A literal nested list already present in the source YAML (not
        produced by a $ref) must not be flattened -- only $ref expansions
        that resolve to a list get spliced"""
        resolver = RuleResolver(refs={})

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [],
            'some_field': [[1, 2], [3, 4]],
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['some_field'] == [[1, 2], [3, 4]]

    def test_expand_nested_refs(self):
        """Should handle nested reference expansion"""
        refs = {
            'conditions': {
                'well-seeded': {
                    'all': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': 1.0}
                    ]
                },
                'protected': {
                    'any': [
                        {'field': 'info.category', 'operator': '==', 'value': 'keep'}
                    ]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'$ref': 'conditions.well-seeded'},
                {'none': [{'$ref': 'conditions.protected'}]}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0] == refs['conditions']['well-seeded']
        assert resolved['conditions'][1]['none'][0] == refs['conditions']['protected']

    def test_unknown_condition_ref_raises_error(self):
        """Should raise UnknownRefError for undefined condition"""
        refs = {'conditions': {'private-tracker': {}}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.unknown'}],
            'actions': []
        }

        with pytest.raises(UnknownRefError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'conditions.unknown' in str(exc_info.value)
        assert 'private-tracker' in str(exc_info.value)

    def test_unknown_action_ref_raises_error(self):
        """Should raise UnknownRefError for undefined action"""
        refs = {'actions': {'safe-delete': []}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [{'$ref': 'actions.unknown'}]
        }

        with pytest.raises(UnknownRefError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'actions.unknown' in str(exc_info.value)

    def test_invalid_ref_path_raises_error(self):
        """Should raise InvalidRefError for invalid path format"""
        refs = {'conditions': {'private-tracker': {}}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'private-tracker'}],  # Missing 'conditions.'
            'actions': []
        }

        with pytest.raises(InvalidRefError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'group.name' in str(exc_info.value)

    def test_unknown_group_raises_error(self):
        """Should raise InvalidRefError for unknown group"""
        refs = {}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'unknown.something'}],
            'actions': []
        }

        with pytest.raises(InvalidRefError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'Unknown group' in str(exc_info.value)


class TestCircularReferences:
    """Test circular reference detection"""

    def test_circular_ref_direct(self):
        """Should detect direct circular reference"""
        # Note: This scenario is prevented by the resolver design
        # (conditions/actions can't self-reference since they're data structures)
        # But we test the protection mechanism
        refs = {
            'conditions': {
                'loop': {'$ref': 'conditions.loop'}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.loop'}],
            'actions': []
        }

        with pytest.raises(CircularRefError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'conditions.loop' in str(exc_info.value)


class TestResolutionPipeline:
    """Test two-phase resolution: refs then vars"""

    def test_refs_expanded_before_vars(self):
        """Should expand refs first, then substitute variables"""
        refs = {
            'vars': {'min_ratio': 1.0},
            'conditions': {
                'well-seeded': {
                    'all': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}
                    ]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.well-seeded'}],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        # Ref expanded and variable substituted
        assert resolved['conditions'][0]['all'][0]['value'] == 1.0

    def test_complex_rule_full_resolution(self):
        """Should fully resolve complex rule with multiple refs and vars"""
        refs = {
            'vars': {
                'min_ratio': 1.0,
                'cleanup_age': '30 days',
                'protected_categories': ['keep', 'archive'],
            },
            'conditions': {
                'private-tracker': {
                    'any': [
                        {'field': 'trackers.url', 'operator': 'contains', 'value': '.private'}
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
                ]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'Cleanup well-seeded private tracker torrents',
            'enabled': True,
            'conditions': [
                {'$ref': 'conditions.private-tracker'},
                {'$ref': 'conditions.well-seeded'},
                {'none': [{'$ref': 'conditions.protected'}]}
            ],
            'actions': [
                {'$ref': 'actions.safe-delete'}
            ]
        }

        resolved = resolver.resolve_rule(rule)

        # Check structure was expanded
        assert 'any' in resolved['conditions'][0]
        assert 'all' in resolved['conditions'][1]
        assert 'none' in resolved['conditions'][2]
        # actions.safe-delete is a 2-item action sequence -- spliced into the
        # parent list, not nested as a single list element
        assert resolved['actions'] == refs['actions']['safe-delete']
        assert all(isinstance(a, dict) for a in resolved['actions'])

        # Check variables were substituted
        assert resolved['conditions'][1]['all'][0]['value'] == 1.0
        assert resolved['conditions'][1]['all'][1]['value'] == '30 days'
        assert resolved['conditions'][2]['none'][0]['any'][0]['value'] == ['keep', 'archive']


class TestNoRefsBackwardCompatibility:
    """Test that rules without refs work unchanged"""

    def test_rule_without_refs(self):
        """Should handle rules with no refs or vars"""
        resolver = RuleResolver(refs={})

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': 1.0}
            ],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['test']}}
            ]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved == rule  # Should be identical

    def test_rule_with_static_values(self):
        """Should not modify rules with static values"""
        resolver = RuleResolver(refs={'vars': {'min_ratio': 2.0}})

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': 1.0}  # Static, not ${vars.*}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == 1.0  # Unchanged


class TestDeepCopy:
    """Test that resolver doesn't mutate original rules"""

    def test_original_rule_not_mutated(self):
        """Should not mutate original rule dictionary"""
        refs = {
            'vars': {'min_ratio': 2.0},
            'conditions': {
                'test': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        original = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.test'}],
            'actions': []
        }

        # Keep a reference to original structure
        original_conditions = original['conditions']

        # Resolve
        resolved = resolver.resolve_rule(original)

        # Original should be unchanged
        assert original['conditions'] == original_conditions
        assert '$ref' in original['conditions'][0]

        # Resolved should be different
        assert '$ref' not in resolved['conditions'][0]
