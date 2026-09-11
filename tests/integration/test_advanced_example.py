"""
End-to-end verification that advanced-rules-example.yml actually runs.

Loads the real, committed example file (not a re-typed copy) and drives
Rule 9 ("Special handling for private tracker HD TV shows") through the
real resolver and the real RulesEngine.run() path. This rule mixes
multiple $ref: actions.* entries with inline actions in one list -- the
exact shape that used to crash with `TypeError: list indices must be
integers or slices, not str` before the actions-ref splice fix (see
BUGS.md), and separately relies on `increase_priority`, an action type
that existed on the API client but was never wired into the dispatch
table until this was verified (see TODO.md history / BUGS.md).
"""

from pathlib import Path

import pytest
import yaml

from qbt_rules.engine import RulesEngine
from qbt_rules.resolver import RuleResolver

EXAMPLE_FILE = Path(__file__).parent.parent.parent / "advanced-rules-example.yml"


@pytest.fixture
def advanced_example_doc():
    return yaml.safe_load(EXAMPLE_FILE.read_text())


class TestAdvancedExampleRule9(object):
    """Rule 9: mixes $ref: actions.process-hd-content, $ref: actions.
    force-seed-private, and two inline actions in a single actions: list."""

    def test_rule9_matches_and_executes_without_error(
        self, advanced_example_doc, mock_api, mock_config
    ):
        refs = advanced_example_doc["refs"]
        rule9 = next(
            r for r in advanced_example_doc["rules"]
            if r["name"] == "Special handling for private tracker HD TV shows"
        )
        resolved = RuleResolver(refs=refs).resolve_rule(rule9)

        # Every action in the resolved rule must be a flat action dict --
        # regression guard against the splice bug nesting a list inside
        # the actions list.
        for action in resolved["actions"]:
            assert isinstance(action, dict)
            assert "type" in action

        torrent = {
            "hash": "h1",
            "name": "Some.Show.Name.S01E02.1080p.WEB-DL.x264",
            "size": 3 * 1024 ** 3,  # 3 GB, over the rule's 2 GB threshold
            "state": "downloading",
            "tags": "",
            "category": "",
            "ratio": 0.1,
        }
        mock_api.torrents_data = {torrent["hash"]: torrent}
        mock_api.trackers_data = {
            torrent["hash"]: [{"url": "https://privatehd.to/announce"}]
        }
        mock_config.get_rules.return_value = [resolved]

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context="torrent-imported")

        assert engine.stats.rules_matched == 1

        # actions.process-hd-content
        assert mock_api.calls["add_tags"][0]["tags"] == ["hd", "quality-content"]
        assert mock_api.calls["set_category"][0]["category"] == "hd-content"
        assert mock_api.calls["increase_priority"] == [["h1"]]

        # actions.force-seed-private
        assert mock_api.calls["force_start"] == [["h1"]]
        assert mock_api.calls["set_upload_limit"][0]["limit"] == -1
        assert mock_api.calls["add_tags"][1]["tags"] == ["force-seeding", "private-boost"]

        # inline actions
        assert mock_api.calls["add_tags"][2]["tags"] == ["premium-tv", "auto-managed"]
        assert mock_api.calls["set_category"][1]["category"] == "tv-premium"

    def test_rule9_does_not_match_public_tracker(
        self, advanced_example_doc, mock_api, mock_config
    ):
        """Sanity check the negative case: a torrent that fails the
        private-tracker condition shouldn't match at all."""
        refs = advanced_example_doc["refs"]
        rule9 = next(
            r for r in advanced_example_doc["rules"]
            if r["name"] == "Special handling for private tracker HD TV shows"
        )
        resolved = RuleResolver(refs=refs).resolve_rule(rule9)

        torrent = {
            "hash": "h2",
            "name": "Some.Show.Name.S01E02.1080p.WEB-DL.x264",
            "size": 3 * 1024 ** 3,
            "state": "downloading",
            "tags": "",
            "category": "",
            "ratio": 0.1,
        }
        mock_api.torrents_data = {torrent["hash"]: torrent}
        mock_api.trackers_data = {
            torrent["hash"]: [{"url": "https://public-tracker.example/announce"}]
        }
        mock_config.get_rules.return_value = [resolved]

        engine = RulesEngine(mock_api, mock_config)
        engine.run(context="torrent-imported")

        assert engine.stats.rules_matched == 0
        assert mock_api.calls["add_tags"] == []
