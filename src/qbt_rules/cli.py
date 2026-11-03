"""The `qbt-rules` command.

The wiki's CLI-Reference page is generated from this module (scripts/gen-wiki.py),
so command docstrings and option help are user documentation.

TODO(4f): The template skeleton, not installed as the command yet: `qbt-rules` is the
legacy argparse CLI (legacy_cli.py) until the Typer port (4f) lands here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from qbt_rules import __description__, __version__
from qbt_rules.config import CONFIG_ENV, SETTINGS, Config, ConfigError, load_config

app = typer.Typer(
    help=__description__,
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        envvar=CONFIG_ENV,
        help="Config file (default /etc/qbt-rules/config.yaml; missing is fine).",
        show_default=False,
    ),
]


def _load(path: Path | None) -> Config:
    try:
        return load_config(path)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(2) from e


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Print the effective configuration and where each value came from. Secrets are masked."""
    cfg = _load(config)
    for setting in SETTINGS:
        shown = "********" if setting.secret else cfg.values.get(setting.key)
        typer.echo(f"{setting.key} = {shown}  ({cfg.sources[setting.key]})")


@app.command()
def serve(config: ConfigOption = None) -> None:
    """Run the HTTP server."""
    import logging

    import uvicorn

    from qbt_rules.api import create_app

    cfg = _load(config)
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(cfg),
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
        proxy_headers=True,
    )


def main() -> None:
    app()
