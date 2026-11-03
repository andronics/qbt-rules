"""Rule files the project publishes, for the tests that check they stay valid."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The complete example rules.yml lives on the wiki page (it was advanced-rules-example.yml)
ADVANCED_EXAMPLE_PAGE = REPO / "docs" / "wiki" / "Advanced-Rules-Example.md"

# The example rules.yml in contrib/ (nothing is copied into place on first start)
EXAMPLE_RULES = REPO / "contrib" / "rules.example.yml"


def advanced_rules_example() -> str:
    """The wiki page's YAML block: the example rules.yml, as users copy it."""
    text = ADVANCED_EXAMPLE_PAGE.read_text(encoding="utf-8")
    match = re.search(r"^```yaml\n(.*?)^```$", text, re.S | re.M)
    if match is None:
        raise AssertionError(f"{ADVANCED_EXAMPLE_PAGE}: no ```yaml block")
    return match.group(1)
