"""Keys beside a `$ref` (design record 0006, step 1)

A `$ref` mapping stands alone: the resolver replaces the whole mapping with the
referenced block, so anything beside it is dropped. In 0.11.x the validator
reports that as an error (so `qbt-rules validate` fails and the editor will not
save), and loading still works but logs one warning per affected rule.

One case per position the record names, per sibling kind: conditions (a rule's
`conditions`, a group inside it, a `refs.conditions` block; siblings a group key
or a field condition) and actions (an item of a rule's `actions`, a
`refs.actions` block; siblings `params:` or `type:`).
"""

import copy
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from qbt_rules.config_loader import load_config
from qbt_rules.resolver import RuleResolver
from qbt_rules.rules_validation import validate_rules_text

SEEDED = {"field": "info.ratio", "operator": ">=", "value": 1}
OLD = {"field": "info.seeding_time", "operator": ">=", "value": 604800}
GROUP = {"any": [OLD]}  # sibling kind: a group key
LEAF = dict(OLD)  # sibling kind: a field condition
PARAMS = {"params": {"delete_files": True}}  # beside a ref to delete_files: false
TYPE = {"type": "stop"}

REFS: dict[str, Any] = {
    "conditions": {"seeded": {"all": [SEEDED]}},
    "actions": {"remove": [{"type": "delete_torrent", "params": {"delete_files": False}}]},
}
COND_REF = {"$ref": "conditions.seeded"}
ACT_REF = {"$ref": "actions.remove"}
STOP = [{"type": "stop"}]


def _file(
    conditions: Any = None,
    actions: Any = None,
    cond_blocks: dict[str, Any] | None = None,
    act_blocks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = copy.deepcopy(REFS)
    refs["conditions"].update(cond_blocks or {})
    refs["actions"].update(act_blocks or {})
    rule = {
        "id": "r",
        "conditions": conditions if conditions is not None else [COND_REF],
        "actions": actions if actions is not None else [ACT_REF],
    }
    return {"refs": refs, "rules": [rule]}


def _with(ref: dict[str, Any], siblings: dict[str, Any]) -> dict[str, Any]:
    return {**ref, **copy.deepcopy(siblings)}


# (id, the file with siblings, the same file without them, validator path, resolver path, keys)
CASES = [
    pytest.param(
        _file(conditions=_with(COND_REF, GROUP)),
        _file(conditions=COND_REF),
        "rules[0].conditions",
        "rules['r'].conditions",
        ["any"],
        id="conditions-mapping-group",
    ),
    pytest.param(
        _file(conditions=_with(COND_REF, LEAF)),
        _file(conditions=COND_REF),
        "rules[0].conditions",
        "rules['r'].conditions",
        ["field", "operator", "value"],
        id="conditions-mapping-field",
    ),
    pytest.param(
        _file(conditions=[_with(COND_REF, GROUP)]),
        _file(conditions=[COND_REF]),
        "rules[0].conditions[0]",
        "rules['r'].conditions[0]",
        ["any"],
        id="conditions-list-group",
    ),
    pytest.param(
        _file(conditions=[_with(COND_REF, LEAF)]),
        _file(conditions=[COND_REF]),
        "rules[0].conditions[0]",
        "rules['r'].conditions[0]",
        ["field", "operator", "value"],
        id="conditions-list-field",
    ),
    pytest.param(
        _file(conditions={"all": [_with(COND_REF, GROUP)]}),
        _file(conditions={"all": [COND_REF]}),
        "rules[0].conditions.all[0]",
        "rules['r'].conditions.all[0]",
        ["any"],
        id="group-item-group",
    ),
    pytest.param(
        _file(conditions={"all": [_with(COND_REF, LEAF)]}),
        _file(conditions={"all": [COND_REF]}),
        "rules[0].conditions.all[0]",
        "rules['r'].conditions.all[0]",
        ["field", "operator", "value"],
        id="group-item-field",
    ),
    pytest.param(
        _file(conditions={"all": [{"any": [_with(COND_REF, {"none": [OLD]})]}]}),
        _file(conditions={"all": [{"any": [COND_REF]}]}),
        "rules[0].conditions.all[0].any[0]",
        "rules['r'].conditions.all[0].any[0]",
        ["none"],
        id="nested-group-item-group",
    ),
    pytest.param(
        _file(
            conditions=[{"$ref": "conditions.wide"}],
            cond_blocks={"wide": _with(COND_REF, GROUP)},
        ),
        _file(conditions=[{"$ref": "conditions.wide"}], cond_blocks={"wide": COND_REF}),
        "refs.conditions.wide",
        "rules['r'].conditions[0] (in conditions.wide)",
        ["any"],
        id="refs-conditions-block-group",
    ),
    pytest.param(
        _file(
            conditions=[{"$ref": "conditions.wide"}],
            cond_blocks={"wide": _with(COND_REF, LEAF)},
        ),
        _file(conditions=[{"$ref": "conditions.wide"}], cond_blocks={"wide": COND_REF}),
        "refs.conditions.wide",
        "rules['r'].conditions[0] (in conditions.wide)",
        ["field", "operator", "value"],
        id="refs-conditions-block-field",
    ),
    pytest.param(
        _file(
            conditions=[{"$ref": "conditions.wide"}],
            cond_blocks={"wide": {"all": [_with(COND_REF, LEAF)]}},
        ),
        _file(conditions=[{"$ref": "conditions.wide"}], cond_blocks={"wide": {"all": [COND_REF]}}),
        "refs.conditions.wide.all[0]",
        "rules['r'].conditions[0].all[0] (in conditions.wide)",
        ["field", "operator", "value"],
        id="refs-conditions-block-group-item-field",
    ),
    pytest.param(
        _file(actions=[_with(ACT_REF, PARAMS)]),
        _file(actions=[ACT_REF]),
        "rules[0].actions[0]",
        "rules['r'].actions[0]",
        ["params"],
        id="rule-action-params",
    ),
    pytest.param(
        _file(actions=[_with(ACT_REF, TYPE)]),
        _file(actions=[ACT_REF]),
        "rules[0].actions[0]",
        "rules['r'].actions[0]",
        ["type"],
        id="rule-action-type",
    ),
    pytest.param(
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": [_with(ACT_REF, PARAMS)]}),
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": [ACT_REF]}),
        "refs.actions.wrap[0]",
        "rules['r'].actions[0][0] (in actions.wrap)",
        ["params"],
        id="refs-actions-block-item-params",
    ),
    pytest.param(
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": [_with(ACT_REF, TYPE)]}),
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": [ACT_REF]}),
        "refs.actions.wrap[0]",
        "rules['r'].actions[0][0] (in actions.wrap)",
        ["type"],
        id="refs-actions-block-item-type",
    ),
    pytest.param(
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": _with(ACT_REF, PARAMS)}),
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": ACT_REF}),
        "refs.actions.wrap",
        "rules['r'].actions[0] (in actions.wrap)",
        ["params"],
        id="refs-actions-block-params",
    ),
    pytest.param(
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": _with(ACT_REF, TYPE)}),
        _file(actions=[{"$ref": "actions.wrap"}], act_blocks={"wrap": ACT_REF}),
        "refs.actions.wrap",
        "rules['r'].actions[0] (in actions.wrap)",
        ["type"],
        id="refs-actions-block-type",
    ),
]


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)


def _resolve(data: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    resolver = RuleResolver(refs=data["refs"], **kwargs)
    return [resolver.resolve_rule(rule) for rule in data["rules"]]


def _sibling_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "beside a $ref" in r.getMessage()
    ]


# -- the validator --------------------------------------------------------------------------------


class TestValidator:
    @pytest.mark.parametrize(("bad", "good", "path", "_where", "keys"), CASES)
    def test_error_names_keys_path_and_fix(
        self, bad: dict[str, Any], good: dict[str, Any], path: str, _where: str, keys: list[str]
    ) -> None:
        result = validate_rules_text(_dump(bad))
        errors = [i for i in result["issues"] if i["severity"] == "error"]
        assert len(errors) == 1, errors
        error = errors[0]
        assert error["path"] == path
        assert error["line"] is not None
        message = error["message"]
        for key in keys:
            assert f"`{key}`" in message
        assert "beside `$ref`" in message
        assert "the reference replaces this whole mapping" in message
        assert not result["valid"]

    @pytest.mark.parametrize(("bad", "good", "_path", "_where", "_keys"), CASES)
    def test_without_the_siblings_is_valid(
        self, bad: dict[str, Any], good: dict[str, Any], _path: str, _where: str, _keys: Any
    ) -> None:
        result = validate_rules_text(_dump(good))
        assert result["valid"], result["issues"]

    def test_the_records_example_has_the_records_fix(self) -> None:
        text = _dump(_file(conditions={"all": [_with(COND_REF, GROUP)]}))
        [error] = [i for i in validate_rules_text(text)["issues"] if i["severity"] == "error"]
        assert error["message"] == (
            "`any` beside `$ref` is ignored: the reference replaces this whole mapping. "
            "Put the reference and the `any:` as separate items of an `all:` list."
        )

    def test_a_field_condition_gets_the_all_list_fix(self) -> None:
        text = _dump(_file(conditions=[_with(COND_REF, LEAF)]))
        [error] = [i for i in validate_rules_text(text)["issues"] if i["severity"] == "error"]
        assert error["message"].startswith("`field`, `operator` and `value` beside `$ref` are")
        assert "as separate items of an `all:` list" in error["message"]

    def test_an_action_gets_the_action_fix(self) -> None:
        text = _dump(_file(actions=[_with(ACT_REF, PARAMS)]))
        [error] = [i for i in validate_rules_text(text)["issues"] if i["severity"] == "error"]
        assert "Write the action out in full" in error["message"]

    def test_even_a_description_is_refused(self) -> None:
        # Resolved question 3 in the record: no key is allowed beside $ref
        text = _dump(_file(conditions=[_with(COND_REF, {"description": "public ones"})]))
        result = validate_rules_text(text)
        assert not result["valid"]
        assert "`description` beside `$ref` is ignored" in result["issues"][0]["message"]

    def test_the_validator_does_not_log_the_load_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            validate_rules_text(_dump(_file(conditions=[_with(COND_REF, GROUP)])))
        assert _sibling_warnings(caplog) == []


# -- the resolver ---------------------------------------------------------------------------------


class TestResolver:
    @pytest.mark.parametrize(("bad", "good", "_path", "where", "keys"), CASES)
    def test_keys_still_dropped_with_one_warning(
        self,
        bad: dict[str, Any],
        good: dict[str, Any],
        _path: str,
        where: str,
        keys: list[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING):
            resolved = _resolve(bad)
        # Loading is unchanged in 0.11.x: the siblings are dropped
        assert resolved == _resolve(good)
        [warning] = _sibling_warnings(caplog)
        assert "Rule 'r'" in warning
        assert f"{where}: {', '.join(keys)} beside $ref" in warning

    def test_one_warning_per_rule_listing_every_place(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        data = _file(
            conditions={"all": [_with(COND_REF, GROUP), _with(COND_REF, LEAF)]},
            actions=[_with(ACT_REF, PARAMS)],
        )
        with caplog.at_level(logging.WARNING):
            _resolve(data)
        [warning] = _sibling_warnings(caplog)
        assert "rules['r'].conditions.all[0]: any beside" in warning
        assert "rules['r'].conditions.all[1]: field, operator, value beside" in warning
        assert "rules['r'].actions[0]: params beside $ref actions.remove" in warning

    def test_no_warning_without_siblings(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _resolve(_file())
        assert _sibling_warnings(caplog) == []

    def test_warning_can_be_turned_off(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            _resolve(_file(conditions=[_with(COND_REF, GROUP)]), warn_ref_siblings=False)
        assert _sibling_warnings(caplog) == []


class TestLoading:
    def test_once_per_rule_per_load(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        data = _file(conditions=[_with(COND_REF, GROUP)])
        data["rules"].append({**copy.deepcopy(data["rules"][0]), "id": "s"})
        data["rules"].append({"id": "clean", "conditions": [COND_REF], "actions": STOP})
        state = tmp_path / "state"
        state.mkdir()
        (state / "rules.yml").write_text(_dump(data), encoding="utf-8")
        (tmp_path / "config.yaml").write_text("", encoding="utf-8")
        config = load_config(tmp_path / "config.yaml", environ={"QBT_RULES_STATE_DIR": str(state)})

        with caplog.at_level(logging.WARNING):
            rules = config.get_rules()
            config.get_rules()  # cached: the same load
        assert [r["id"] for r in rules] == ["r", "s", "clean"]
        warnings = _sibling_warnings(caplog)
        assert len(warnings) == 2
        assert "Rule 'r'" in warnings[0]
        assert "Rule 's'" in warnings[1]
