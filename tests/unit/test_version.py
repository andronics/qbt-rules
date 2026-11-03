import re

import qbt_rules


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+.*|0\+unknown", qbt_rules.__version__)
