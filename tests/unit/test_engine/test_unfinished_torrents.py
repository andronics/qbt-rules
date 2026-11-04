"""An unfinished torrent must never match an age-based delete rule

Regression tests for production's "Delete Public Torrents After 3 Days or
2.0 Ratio" rule (id delete-public-aged-or-ratio), which deleted every new
public torrent, with its files, about a second after qBittorrent added it.

qBittorrent reports a torrent that has never completed with
``completion_on: -1`` (5.x: Utils::DateTime::toSecsSinceEpoch of an invalid
QDateTime) and ``ratio: 0``; older releases sent 0 or 4294967295 (the
unsigned -1). The rule is "public AND (completed long ago OR ratio >= 2)",
built from production's refs. Written as a group that holds both `all` and
`any`, its `any` (the age-or-ratio test) was never evaluated below the top
level, so "public" alone deleted the torrent.
"""

import time
from typing import Any
from unittest.mock import Mock

import pytest

from qbt_rules.engine import ConditionEvaluator, RulesEngine
from qbt_rules.resolver import RuleResolver

# Production's refs (rules.yml), as recorded when they were added
REFS: dict[str, Any] = {
    "vars": {"public_max_age": "3 days", "public_ratio": 2.0},
    "conditions": {
        "tagged-public": {
            "all": [{"field": "info.tags", "operator": "not_contains", "value": "private"}]
        },
        "is-complete": {
            "all": [
                {
                    "field": "info.completion_on",
                    "operator": "older_than",
                    "value": "${vars.public_max_age}",
                }
            ]
        },
        "public-ratio": {
            "all": [{"field": "info.ratio", "operator": ">=", "value": "${vars.public_ratio}"}]
        },
        "public-delete-candidate": {
            "all": [{"$ref": "conditions.tagged-public"}],
            "any": [{"$ref": "conditions.is-complete"}, {"$ref": "conditions.public-ratio"}],
        },
    },
}

PUBLIC_AND_AGED_OR_RATIO: dict[str, Any] = {
    "all": [{"$ref": "conditions.tagged-public"}],
    "any": [{"$ref": "conditions.is-complete"}, {"$ref": "conditions.public-ratio"}],
}

# The same logic in every shape a rules.yml can spell it
SHAPES: dict[str, Any] = {
    "top-level groups": PUBLIC_AND_AGED_OR_RATIO,
    "nested in all": {"all": [PUBLIC_AND_AGED_OR_RATIO]},
    "bare-list item": [PUBLIC_AND_AGED_OR_RATIO],
    "ref in all": {"all": [{"$ref": "conditions.public-delete-candidate"}]},
    "ref in bare list": [{"$ref": "conditions.public-delete-candidate"}],
    "top-level ref": {"$ref": "conditions.public-delete-candidate"},
}

# What qBittorrent sends for "never completed": -1 (5.x), 0 and the
# unsigned -1 (older releases), and no field at all
UNSET_COMPLETION = [-1, 0, 4294967295, None]


def _rule(conditions: Any) -> dict[str, Any]:
    return RuleResolver(REFS).resolve_rule(
        {
            "id": "delete-public-aged-or-ratio",
            "meta": {"description": "Delete Public Torrents After 3 Days or 2.0 Ratio"},
            "conditions": conditions,
            "actions": [
                {"type": "set_category", "params": {"category": "deleted"}},
                {"type": "delete_torrent", "params": {"delete_files": True}},
            ],
        }
    )


def _torrent(completion_on: int | None, ratio: float = 0.0) -> dict[str, Any]:
    now = int(time.time())
    torrent: dict[str, Any] = {
        "hash": "a" * 40,
        "name": "Fragile Things - Neil Gaiman - 2006 (Dark Fantasy) [Audiobook]",
        "state": "metaDL",
        "progress": 0.0,
        "tags": "",
        "category": "books",
        "ratio": ratio,
        "added_on": now - 1,
        "completion_on": completion_on,
        "seen_complete": -1,
    }
    if completion_on is None:
        del torrent["completion_on"]
    return torrent


@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES.keys())
@pytest.mark.parametrize("completion_on", UNSET_COMPLETION)
def test_just_added_public_torrent_is_not_deleted(
    mock_api: Any, mock_config: Mock, shape: Any, completion_on: int | None
) -> None:
    """The run qBittorrent's on-add hook starts never deletes the new torrent"""
    torrent = _torrent(completion_on)
    mock_config.get_rules = Mock(return_value=[_rule(shape)])
    mock_api.torrents_data = {torrent["hash"]: torrent}

    engine = RulesEngine(mock_api, mock_config)
    engine.run(context="added", torrent_hash=torrent["hash"])

    assert mock_api.calls["delete"] == []
    assert mock_api.calls["set_category"] == []
    assert engine.stats.rules_matched == 0


@pytest.mark.parametrize("shape", SHAPES.values(), ids=SHAPES.keys())
def test_public_torrent_completed_long_ago_still_matches(shape: Any) -> None:
    """The fix keeps the rule's intended matches"""
    evaluator = ConditionEvaluator(Mock())
    conditions = _rule(shape)["conditions"]
    four_days_ago = int(time.time()) - 4 * 86400

    assert evaluator.evaluate(_torrent(four_days_ago), conditions, "added")
    assert evaluator.evaluate(_torrent(-1, ratio=2.5), conditions, "added")
    # Completed an hour ago, low ratio: not yet
    assert not evaluator.evaluate(_torrent(int(time.time()) - 3600), conditions, "added")
    # Private: never
    private = _torrent(four_days_ago)
    private["tags"] = "private,iptorrent.com"
    assert not evaluator.evaluate(private, conditions, "added")


@pytest.mark.parametrize("completion_on", UNSET_COMPLETION)
@pytest.mark.parametrize("operator", ["older_than", "newer_than"])
def test_unset_completion_time_is_neither_older_nor_newer(
    completion_on: int | None, operator: str
) -> None:
    """An unset completion time satisfies no time comparison"""
    evaluator = ConditionEvaluator(Mock())
    condition = {"field": "info.completion_on", "operator": operator, "value": "3 days"}

    assert not evaluator.evaluate(_torrent(completion_on), {"all": [condition]})


def test_nested_group_honours_its_none() -> None:
    """A nested group's `none` counts as well as its `all`"""
    evaluator = ConditionEvaluator(Mock())
    nested = {
        "all": [{"field": "info.tags", "operator": "not_contains", "value": "private"}],
        "none": [{"field": "info.category", "operator": "==", "value": "books"}],
    }

    assert not evaluator.evaluate(_torrent(-1), {"all": [nested]})
    assert not evaluator.evaluate(_torrent(-1), [nested])
    other = _torrent(-1)
    other["category"] = "tv"
    assert evaluator.evaluate(other, {"all": [nested]})
