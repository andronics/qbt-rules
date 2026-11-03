"""`python -m qbt_rules`: the same as the `qbt-rules` command.

TODO(4f): the Typer CLI in qbt_rules.cli takes over; until then the command is the
legacy argparse CLI (pyproject.toml's [project.scripts]).
"""

from qbt_rules.legacy_cli import main

main()
