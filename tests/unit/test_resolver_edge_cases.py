"""Comprehensive edge case and stress tests for RuleResolver"""

import pytest

from qbt_rules.resolver import RuleResolver
from qbt_rules.errors import (
    InvalidRefError,
    UnknownRefError,
    InvalidVariableError,
    UnknownVariableError,
    CircularRefError,
    RefTypeMismatchError,
)


class TestVariableEdgeCases:
    """Test edge cases in variable substitution"""

    def test_variable_with_none_value(self):
        """Should handle None variable values"""
        refs = {'vars': {'null_value': None}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.category', 'operator': '==', 'value': '${vars.null_value}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] is None

    def test_variable_with_empty_string(self):
        """Should handle empty string variable values"""
        refs = {'vars': {'empty': ''}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.category', 'operator': '==', 'value': '${vars.empty}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == ''

    def test_variable_with_zero(self):
        """Should handle zero values (not falsy confusion)"""
        refs = {'vars': {'zero': 0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '==', 'value': '${vars.zero}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == 0
        assert type(resolved['conditions'][0]['value']) == int

    def test_variable_with_negative_number(self):
        """Should handle negative numbers"""
        refs = {'vars': {'negative': -5.5}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>', 'value': '${vars.negative}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == -5.5

    def test_variable_with_boolean_true(self):
        """Should handle boolean True"""
        refs = {'vars': {'enabled': True}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.enabled', 'operator': '==', 'value': '${vars.enabled}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] is True
        assert type(resolved['conditions'][0]['value']) == bool

    def test_variable_with_boolean_false(self):
        """Should handle boolean False"""
        refs = {'vars': {'disabled': False}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.disabled', 'operator': '==', 'value': '${vars.disabled}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] is False

    def test_variable_with_empty_list(self):
        """Should handle empty lists"""
        refs = {'vars': {'empty_list': []}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.tags', 'operator': 'in', 'value': '${vars.empty_list}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == []

    def test_variable_with_nested_list(self):
        """Should handle nested lists"""
        refs = {'vars': {'nested': [['a', 'b'], ['c', 'd']]}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.data', 'operator': '==', 'value': '${vars.nested}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == [['a', 'b'], ['c', 'd']]

    def test_variable_with_dict(self):
        """Should handle dictionary values"""
        refs = {'vars': {'config': {'key': 'value', 'nested': {'deep': 'data'}}}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.metadata', 'operator': '==', 'value': '${vars.config}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == {'key': 'value', 'nested': {'deep': 'data'}}

    def test_variable_with_special_characters_in_value(self):
        """Should handle special characters in string values"""
        refs = {'vars': {'special': 'test@#$%^&*()[]{}|\\/<>?'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.name', 'operator': '==', 'value': '${vars.special}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == 'test@#$%^&*()[]{}|\\/<>?'

    def test_variable_with_unicode(self):
        """Should handle Unicode characters"""
        refs = {'vars': {'unicode': '日本語 🎌 émojis 中文'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.name', 'operator': '==', 'value': '${vars.unicode}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == '日本語 🎌 émojis 中文'

    def test_variable_with_multiline_string(self):
        """Should handle multiline strings"""
        refs = {'vars': {'multiline': 'line1\nline2\nline3'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'field': 'info.description', 'operator': '==', 'value': '${vars.multiline}'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['value'] == 'line1\nline2\nline3'

    def test_variable_in_nested_structure(self):
        """Should substitute variables in deeply nested structures"""
        refs = {'vars': {'ratio': 1.5}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'all': [
                    {'any': [
                        {'none': [
                            {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.ratio}'}
                        ]}
                    ]}
                ]}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['all'][0]['any'][0]['none'][0]['value'] == 1.5

    def test_multiple_variables_same_condition(self):
        """Should handle multiple variables in same condition"""
        refs = {'vars': {'min': 1.0, 'max': 5.0}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'all': [
                    {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min}'},
                    {'field': 'info.ratio', 'operator': '<=', 'value': '${vars.max}'}
                ]}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0]['all'][0]['value'] == 1.0
        assert resolved['conditions'][0]['all'][1]['value'] == 5.0

    def test_variable_in_action_params(self):
        """Should substitute variables in action parameters"""
        refs = {'vars': {'tag_name': 'auto-tagged', 'category': 'movies'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['${vars.tag_name}']}},
                {'type': 'set_category', 'params': {'category': '${vars.category}'}}
            ]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'][0]['params']['tags'][0] == 'auto-tagged'
        assert resolved['actions'][1]['params']['category'] == 'movies'

    def test_partial_variable_substitution_in_string(self):
        """Should handle partial substitution when variable doesn't exist in middle of string"""
        refs = {'vars': {'existing': 'value'}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['prefix-${vars.missing}-suffix']}}
            ]
        }

        with pytest.raises(UnknownVariableError) as exc_info:
            resolver.resolve_rule(rule)
        assert 'missing' in str(exc_info.value)


class TestReferenceEdgeCases:
    """Test edge cases in reference expansion"""

    def test_ref_with_empty_condition_block(self):
        """Should handle references to empty condition blocks"""
        refs = {
            'conditions': {
                'empty': {}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.empty'}],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0] == {}

    def test_ref_with_empty_action_list(self):
        """Should handle references to empty action lists (spliced -> contributes
        zero actions, not a nested empty-list placeholder that would crash the
        engine's executor when it tries to treat it as an action dict)"""
        refs = {
            'actions': {
                'empty': []
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [],
            'actions': [{'$ref': 'actions.empty'}]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'] == []

    def test_ref_with_hyphenated_name(self):
        """Should handle references with hyphens in names"""
        refs = {
            'conditions': {
                'private-tracker-hd': {
                    'all': [{'field': 'info.name', 'operator': 'matches', 'value': '1080p'}]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.private-tracker-hd'}],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert 'all' in resolved['conditions'][0]

    def test_ref_with_underscored_name(self):
        """Should handle references with underscores in names"""
        refs = {
            'conditions': {
                'private_tracker': {
                    'all': [{'field': 'trackers.url', 'operator': 'contains', 'value': 'private'}]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.private_tracker'}],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert 'all' in resolved['conditions'][0]

    def test_multiple_refs_same_rule(self):
        """Should handle multiple references in same rule"""
        refs = {
            'conditions': {
                'cond1': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
                'cond2': {'all': [{'field': 'info.category', 'operator': '==', 'value': 'movies'}]},
                'cond3': {'all': [{'field': 'info.state', 'operator': '==', 'value': 'uploading'}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'$ref': 'conditions.cond1'},
                {'$ref': 'conditions.cond2'},
                {'$ref': 'conditions.cond3'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert len(resolved['conditions']) == 3
        assert all('all' in cond for cond in resolved['conditions'])

    def test_ref_mixed_with_inline_conditions(self):
        """Should handle mix of refs and inline conditions"""
        refs = {
            'conditions': {
                'private': {'all': [{'field': 'trackers.url', 'operator': 'contains', 'value': 'private'}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'$ref': 'conditions.private'},
                {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
                {'$ref': 'conditions.private'}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        assert len(resolved['conditions']) == 3
        assert resolved['conditions'][0] == resolved['conditions'][2]

    def test_deeply_nested_refs(self):
        """Should handle refs within nested structures"""
        refs = {
            'conditions': {
                'ratio-check': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [
                {'any': [
                    {'all': [
                        {'$ref': 'conditions.ratio-check'},
                        {'none': [
                            {'$ref': 'conditions.ratio-check'}
                        ]}
                    ]}
                ]}
            ],
            'actions': []
        }

        resolved = resolver.resolve_rule(rule)
        # Verify expansion happened at all levels
        assert 'any' in resolved['conditions'][0]
        assert 'all' in resolved['conditions'][0]['any'][0]
        assert 'all' in resolved['conditions'][0]['any'][0]['all'][0]

    def test_ref_to_condition_with_variables(self):
        """Should expand ref and then substitute variables"""
        refs = {
            'vars': {'min_ratio': 2.0},
            'conditions': {
                'well-seeded': {
                    'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}]
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
        # Ref expanded AND variable substituted
        assert resolved['conditions'][0]['all'][0]['value'] == 2.0

    def test_invalid_ref_format_no_dot(self):
        """Should reject ref path without dot separator"""
        refs = {'conditions': {'test': {}}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'test'}],  # Missing 'conditions.'
            'actions': []
        }

        with pytest.raises(InvalidRefError) as exc_info:
            resolver.resolve_rule(rule)
        assert 'group.name' in str(exc_info.value)

    def test_invalid_ref_format_multiple_dots(self):
        """Should handle ref names with dots (splits on first dot only)"""
        refs = {
            'conditions': {
                'test.extra': {}  # Name can contain dots
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.test.extra'}],
            'actions': []
        }

        # Should work - 'test.extra' is a valid condition name
        resolved = resolver.resolve_rule(rule)
        assert resolved['conditions'][0] == {}

        # But if the name doesn't exist, should raise UnknownRefError
        with pytest.raises(UnknownRefError):
            rule2 = {
                'name': 'test2',
                'conditions': [{'$ref': 'conditions.nonexistent.name'}],
                'actions': []
            }
            resolver.resolve_rule(rule2)

    def test_ref_with_non_string_value(self):
        """Should reject non-string ref values"""
        refs = {'conditions': {'test': {}}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 123}],  # Number instead of string
            'actions': []
        }

        with pytest.raises(InvalidRefError):
            resolver.resolve_rule(rule)


class TestCircularReferenceDetection:
    """Test circular reference detection"""

    def test_circular_ref_through_nested_structure(self):
        """Should detect circular ref through complex nesting"""
        refs = {
            'conditions': {
                'loop1': {
                    'all': [
                        {'$ref': 'conditions.loop2'}
                    ]
                },
                'loop2': {
                    'any': [
                        {'$ref': 'conditions.loop1'}
                    ]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.loop1'}],
            'actions': []
        }

        with pytest.raises(CircularRefError) as exc_info:
            resolver.resolve_rule(rule)
        assert 'loop' in str(exc_info.value).lower()

    def test_three_way_circular_ref(self):
        """Should detect circular ref through 3+ references"""
        refs = {
            'conditions': {
                'a': {'all': [{'$ref': 'conditions.b'}]},
                'b': {'all': [{'$ref': 'conditions.c'}]},
                'c': {'all': [{'$ref': 'conditions.a'}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test',
            'conditions': [{'$ref': 'conditions.a'}],
            'actions': []
        }

        with pytest.raises(CircularRefError):
            resolver.resolve_rule(rule)


class TestRefTypeValidation:
    """Test ref type validation in different contexts"""

    def test_action_ref_in_conditions_raises_error(self):
        """Should reject actions.* ref used in conditions block"""
        refs = {
            'conditions': {
                'good-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            },
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [{'$ref': 'actions.my-action'}],  # WRONG: action ref in conditions
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error = exc_info.value
        # Verify error message contains key information
        assert 'actions.my-action' in str(error)
        assert 'conditions' in str(error).lower()
        assert "rules['test-rule'].conditions" in str(error)

    def test_condition_ref_in_actions_raises_error(self):
        """Should reject conditions.* ref used in actions block"""
        refs = {
            'conditions': {
                'my-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            },
            'actions': {
                'good-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [{'$ref': 'conditions.my-condition'}]  # WRONG: condition ref in actions
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error = exc_info.value
        assert 'conditions.my-condition' in str(error)
        assert 'actions' in str(error).lower()
        assert "rules['test-rule'].actions" in str(error)

    def test_correct_condition_ref_in_conditions_works(self):
        """Should allow conditions.* ref in conditions block"""
        refs = {
            'conditions': {
                'my-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [{'$ref': 'conditions.my-condition'}],
            'actions': []
        }

        # Should not raise
        resolved = resolver.resolve_rule(rule)
        assert 'all' in resolved['conditions'][0]
        assert resolved['conditions'][0]['all'][0]['value'] == 1.0

    def test_correct_action_ref_in_actions_works(self):
        """Should allow actions.* ref in actions block"""
        refs = {
            'actions': {
                'my-action': [{'type': 'stop'}, {'type': 'pause'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [{'$ref': 'actions.my-action'}]
        }

        # Should not raise, and should splice the 2-item action sequence into
        # the parent list rather than nesting it as a single list element
        resolved = resolver.resolve_rule(rule)
        assert resolved['actions'] == [{'type': 'stop'}, {'type': 'pause'}]
        assert len(resolved['actions']) == 2

    def test_nested_wrong_ref_caught(self):
        """Should catch wrong ref type even when nested in logical operators"""
        refs = {
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [
                {'all': [
                    {'any': [
                        {'$ref': 'actions.my-action'}  # Nested wrong ref
                    ]}
                ]}
            ],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error = exc_info.value
        assert 'actions.my-action' in str(error)

    def test_deeply_nested_wrong_ref_caught(self):
        """Should catch wrong ref type at any nesting depth"""
        refs = {
            'conditions': {
                'my-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['test']}},
                [
                    {'type': 'stop'},
                    [
                        {'$ref': 'conditions.my-condition'}  # Deeply nested wrong ref
                    ]
                ]
            ]
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error = exc_info.value
        assert 'conditions.my-condition' in str(error)

    def test_error_shows_available_refs_of_correct_type(self):
        """Error message should list available refs of the correct type"""
        refs = {
            'conditions': {
                'ratio-check': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
                'category-check': {'all': [{'field': 'info.category', 'operator': '==', 'value': 'movies'}]},
                'tracker-check': {'all': [{'field': 'trackers.url', 'operator': 'contains', 'value': 'private'}]}
            },
            'actions': {
                'wrong-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [{'$ref': 'actions.wrong-action'}],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error_msg = str(exc_info.value)
        # Should show available conditions
        assert 'ratio-check' in error_msg
        assert 'category-check' in error_msg
        assert 'tracker-check' in error_msg

    def test_error_shows_correct_location_path(self):
        """Error message should show precise location of the invalid ref"""
        refs = {
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'my-test-rule',
            'conditions': [{'$ref': 'actions.my-action'}],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error_msg = str(exc_info.value)
        # Should show the exact location
        assert "rules['my-test-rule'].conditions" in error_msg

    def test_error_shows_expected_vs_actual_groups(self):
        """Error message should clearly show expected vs actual ref groups"""
        refs = {
            'conditions': {
                'my-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [{'$ref': 'conditions.my-condition'}]
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error_msg = str(exc_info.value)
        # Should show both expected and actual
        assert 'actions.*' in error_msg.lower() or 'actions' in error_msg.lower()
        assert 'conditions.*' in error_msg.lower() or 'conditions' in error_msg.lower()

    def test_multiple_wrong_refs_first_one_caught(self):
        """When multiple wrong refs exist, should catch the first one encountered"""
        refs = {
            'actions': {
                'action1': [{'type': 'stop'}],
                'action2': [{'type': 'pause'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [
                {'$ref': 'actions.action1'},  # First wrong ref
                {'$ref': 'actions.action2'}   # Second wrong ref
            ],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        # Should mention the first wrong ref
        assert 'actions.action1' in str(exc_info.value)

    def test_mixed_correct_and_wrong_refs(self):
        """Should allow correct refs but reject wrong ones"""
        refs = {
            'conditions': {
                'good-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            },
            'actions': {
                'wrong-in-conditions': [{'type': 'stop'}],
                'good-action': [{'type': 'pause'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        # First verify correct usage works
        good_rule = {
            'name': 'good-rule',
            'conditions': [{'$ref': 'conditions.good-condition'}],
            'actions': [{'$ref': 'actions.good-action'}]
        }
        resolved = resolver.resolve_rule(good_rule)
        assert 'all' in resolved['conditions'][0]
        assert resolved['actions'] == [{'type': 'pause'}]

        # Now verify wrong ref is caught
        bad_rule = {
            'name': 'bad-rule',
            'conditions': [
                {'$ref': 'conditions.good-condition'},  # OK
                {'$ref': 'actions.wrong-in-conditions'}  # ERROR
            ],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError):
            resolver.resolve_rule(bad_rule)

    def test_ref_in_other_fields_no_validation(self):
        """Refs in non-conditions/actions fields should not be type-validated"""
        refs = {
            'conditions': {
                'my-condition': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]}
            },
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        # Custom field with any ref type should work
        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [],
            'custom_metadata': {
                'condition_ref': {'$ref': 'conditions.my-condition'},
                'action_ref': {'$ref': 'actions.my-action'}
            }
        }

        # Should not raise - custom fields don't have type restrictions
        resolved = resolver.resolve_rule(rule)
        assert 'all' in resolved['custom_metadata']['condition_ref']
        assert isinstance(resolved['custom_metadata']['action_ref'], list)

    def test_transitive_wrong_ref_caught(self):
        """Should catch wrong ref type even when it comes through another ref"""
        refs = {
            'conditions': {
                'has-wrong-ref': {
                    'all': [
                        {'$ref': 'actions.my-action'}  # Wrong ref inside condition definition
                    ]
                }
            },
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [{'$ref': 'conditions.has-wrong-ref'}],
            'actions': []
        }

        # Should catch the nested wrong ref
        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'actions.my-action' in str(exc_info.value)

    def test_no_available_refs_message(self):
        """Error message should handle case when no refs of correct type are defined"""
        refs = {
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
            # No conditions defined
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [{'$ref': 'actions.my-action'}],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error_msg = str(exc_info.value)
        # Should indicate no conditions are available
        assert 'none defined' in error_msg.lower() or '(none' in error_msg.lower()

    def test_path_tracking_through_nested_structures(self):
        """Path tracking should be accurate through complex nested structures"""
        refs = {
            'actions': {
                'my-action': [{'type': 'stop'}]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'complex-rule',
            'conditions': [
                {'all': [
                    {'any': [
                        {'none': [
                            {'$ref': 'actions.my-action'}  # Deep in nesting
                        ]}
                    ]}
                ]}
            ],
            'actions': []
        }

        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        error_msg = str(exc_info.value)
        # Should still show it's in the conditions block
        assert "rules['complex-rule'].conditions" in error_msg

    def test_wrong_ref_with_variables_in_same_rule(self):
        """Should catch type errors even when variables are also being resolved"""
        refs = {
            'vars': {'min_ratio': 1.0},
            'conditions': {
                'my-condition': {
                    'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'}]
                }
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'test-rule',
            'conditions': [],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['test']}},
                {'$ref': 'conditions.my-condition'}  # Wrong type
            ]
        }

        # Should catch the type error before variable substitution
        with pytest.raises(RefTypeMismatchError) as exc_info:
            resolver.resolve_rule(rule)

        assert 'conditions.my-condition' in str(exc_info.value)


class TestComplexScenarios:
    """Test complex real-world scenarios"""

    def test_massive_rule_with_many_refs_and_vars(self):
        """Should handle rule with many references and variables"""
        refs = {
            'vars': {
                'min_ratio': 1.0,
                'max_ratio': 5.0,
                'age': '30 days',
                'categories': ['movies', 'tv', 'music'],
                'tags': ['hd', '4k', 'remux']
            },
            'conditions': {
                'ratio-range': {
                    'all': [
                        {'field': 'info.ratio', 'operator': '>=', 'value': '${vars.min_ratio}'},
                        {'field': 'info.ratio', 'operator': '<=', 'value': '${vars.max_ratio}'}
                    ]
                },
                'category-check': {
                    'any': [
                        {'field': 'info.category', 'operator': 'in', 'value': '${vars.categories}'}
                    ]
                },
                'tag-check': {
                    'any': [
                        {'field': 'info.tags', 'operator': 'in', 'value': '${vars.tags}'}
                    ]
                }
            },
            'actions': {
                'cleanup': [
                    {'type': 'add_tag', 'params': {'tags': ['pending-delete']}},
                    {'type': 'stop'},
                    {'type': 'set_category', 'params': {'category': 'cleanup'}}
                ]
            }
        }
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'complex',
            'enabled': True,
            'conditions': [
                {'$ref': 'conditions.ratio-range'},
                {'$ref': 'conditions.category-check'},
                {'none': [{'$ref': 'conditions.tag-check'}]}
            ],
            'actions': [
                {'$ref': 'actions.cleanup'}
            ]
        }

        resolved = resolver.resolve_rule(rule)

        # Verify all refs expanded
        assert 'all' in resolved['conditions'][0]
        assert 'any' in resolved['conditions'][1]
        assert 'none' in resolved['conditions'][2]
        # actions.cleanup is a 3-item action sequence -- spliced into the
        # parent list rather than nested as a single list element
        assert resolved['actions'] == refs['actions']['cleanup']
        assert all(isinstance(a, dict) for a in resolved['actions'])

        # Verify all vars substituted
        assert resolved['conditions'][0]['all'][0]['value'] == 1.0
        assert resolved['conditions'][0]['all'][1]['value'] == 5.0
        assert resolved['conditions'][1]['any'][0]['value'] == ['movies', 'tv', 'music']

    def test_rule_with_no_refs_or_vars(self):
        """Should pass through rules without any refs or vars unchanged"""
        resolver = RuleResolver(refs={})

        rule = {
            'name': 'plain',
            'enabled': True,
            'priority': 50,
            'context': 'manual',
            'conditions': [
                {'all': [
                    {'field': 'info.ratio', 'operator': '>=', 'value': 1.0},
                    {'field': 'info.state', 'operator': '==', 'value': 'uploading'}
                ]},
                {'none': [
                    {'field': 'info.category', 'operator': 'in', 'value': ['keep', 'archive']}
                ]}
            ],
            'actions': [
                {'type': 'add_tag', 'params': {'tags': ['auto']}},
                {'type': 'stop'}
            ]
        }

        resolved = resolver.resolve_rule(rule)

        # Should be identical
        assert resolved == rule

    def test_rule_with_all_field_types(self):
        """Should handle all possible rule fields"""
        refs = {'vars': {'priority': 75}}
        resolver = RuleResolver(refs=refs)

        rule = {
            'name': 'complete',
            'enabled': True,
            'priority': '${vars.priority}',
            'context': 'weekly-cleanup',
            'stop_on_match': True,
            'description': 'Test rule with all fields',
            'conditions': [
                {'field': 'info.ratio', 'operator': '>=', 'value': 1.0}
            ],
            'actions': [
                {'type': 'stop'}
            ]
        }

        resolved = resolver.resolve_rule(rule)

        # Verify variable substitution in non-standard location
        assert resolved['priority'] == 75
        assert resolved['enabled'] is True
        assert resolved['stop_on_match'] is True

    def test_empty_refs_block(self):
        """Should handle completely empty refs block"""
        resolver = RuleResolver(refs={})

        rule = {
            'name': 'test',
            'conditions': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}],
            'actions': [{'type': 'stop'}]
        }

        resolved = resolver.resolve_rule(rule)
        assert resolved == rule

    def test_performance_with_100_rules(self):
        """Should handle large number of rules efficiently"""
        refs = {
            'vars': {'ratio': 1.0},
            'conditions': {
                'test': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': '${vars.ratio}'}]}
            }
        }
        resolver = RuleResolver(refs=refs)

        # Create 100 similar rules
        rules = []
        for i in range(100):
            rule = {
                'name': f'rule-{i}',
                'conditions': [{'$ref': 'conditions.test'}],
                'actions': [{'type': 'add_tag', 'params': {'tags': [f'tag-{i}']}}]
            }
            rules.append(rule)

        # Resolve all (should complete quickly)
        resolved_rules = [resolver.resolve_rule(r) for r in rules]

        # Verify all resolved correctly
        assert len(resolved_rules) == 100
        assert all(r['conditions'][0]['all'][0]['value'] == 1.0 for r in resolved_rules)
