"""The `qbt-rules` command.

The wiki's CLI-Reference page is generated from this module (scripts/gen-wiki.py),
so command docstrings and option help are user documentation.

Exit codes: 0 success; 1 failure (validation errors, a failed, cancelled or timed-out job,
the server unreachable or refusing the request); 2 bad usage or a configuration that can't
be loaded (an unknown command or option, a bad value, the 0.10.x flags-only form).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from interpose.secret import MASK

from qbt_rules import __description__, __version__, cli_ui
from qbt_rules.api_client import Client, ClientError, validate_torrent_hash
from qbt_rules.config import (
    CONFIG_ENV,
    PLACEHOLDER_SOURCE,
    SETTINGS,
    Config,
    ConfigError,
    load_config,
)

logger = logging.getLogger(__name__)

EXIT_FAILURE = 1
EXIT_USAGE = 2

app = typer.Typer(
    help=__description__,
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
jobs_app = typer.Typer(help="Jobs on the running server.", no_args_is_help=True)
rules_app = typer.Typer(help="The rules in rules.yml.", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
app.add_typer(rules_app, name="rules")

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
JsonOption = Annotated[
    bool, typer.Option("--json", help="Print JSON instead of a table, for scripts.")
]
JobIdArgument = Annotated[str, typer.Argument(metavar="JOB_ID", help="The job's ID.")]


class JobState(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


def _load(path: Path | None) -> Config:
    try:
        return load_config(path)
    except ConfigError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(EXIT_USAGE) from e


def _fail(message: str, code: int = EXIT_FAILURE) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code)


# -- the server and the configuration ----------------------------------------------------------


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Print the effective configuration and where each value came from. Secrets: set or unset."""
    cfg = _load(config)
    for setting in SETTINGS:
        if setting.is_section:
            continue  # the schedule, one line per item below
        shown = cfg.values.get(setting.key)
        if setting.secret:
            # Whether it is set, never its value (template-python v2.4.3). Set means set by
            # the user (the file, the variable or its _FILE): a default, even a non-empty one
            # like queue.redis_url's, is unset. The 0.10.x placeholder key counts as unset,
            # as the server treats it.
            source = cfg.sources[setting.key]
            unset = (
                not shown
                or source == "default"
                or source.startswith("default:")
                or PLACEHOLDER_SOURCE in source
            )
            shown = "(unset)" if unset else f"{MASK} (set)"
        typer.echo(f"{setting.key} = {shown}  ({cfg.sources[setting.key]})")
    for i, entry in enumerate(cfg.schedule):
        typer.echo(f"schedule[{i}] = {entry.cron} -> {entry.context}  ({cfg.sources['schedule']})")
    for problem in (*cfg.warnings, *cfg.problems):
        typer.echo(f"warning: {problem}", err=True)


@app.command()
def serve(config: ConfigOption = None) -> None:
    """Run the server until SIGTERM: the HTTP API and dashboard, the worker and the scheduler."""
    from qbt_rules import server
    from qbt_rules.log_setup import setup_logging

    cfg = _load(config)
    setup_logging(
        {
            "level": cfg.log_level,
            "file": cfg.log_file,
            "trace_mode": cfg.trace_mode,
            "max_bytes": cfg.log_max_bytes,
            "backup_count": cfg.log_backup_count,
        }
    )
    if cfg.metrics_enabled:
        logger.info("Metrics enabled: /metrics (needs the API key)")
    # What it starts without but can't fully work without (no API key): it starts anyway,
    # so /api/health can say what's missing
    for problem in cfg.problems:
        logger.error(f"Configuration: {problem}")
    # Deprecated spellings (the server.* aliases), each naming its replacement, and interpose's:
    # an unknown key or variable, a schedule variable past the end of the list
    for warning in cfg.warnings:
        logger.warning(f"Configuration: {warning}")
    try:
        server.serve(cfg)
    except ConfigError as e:
        _fail(str(e), EXIT_USAGE)


# -- rules -------------------------------------------------------------------------------------


@app.command()
def validate(
    rules_file: Annotated[
        Path | None,
        typer.Argument(
            help="The rules file to check (default: rules.file, rules.yml in the state directory).",
            show_default=False,
        ),
    ] = None,
    config: ConfigOption = None,
) -> None:
    """Check the settings and the rules without running anything. Exits 1 on any error.

    Each problem is printed as `FILE:LINE:COLUMN: SEVERITY: MESSAGE (PATH)`. The checks are
    the dashboard's rules editor's: YAML syntax, structure, `$ref` resolution, then operators,
    actions and their parameters. Warnings alone pass.
    """
    from qbt_rules.rules_validation import validate_rules_text

    cfg = _load(config)
    errors = 0

    def report(severity: str, message: str) -> None:
        nonlocal errors
        errors += severity == "error"
        typer.echo(f"{severity}: {message}")

    shown = cfg.config_file if cfg.config_file.is_file() else f"{cfg.config_file} (absent)"
    typer.echo(f"Settings: {shown}")
    if not cfg.qbt_host:
        report("error", "qbittorrent.host is not set")
    if not cfg.qbt_password:
        report(
            "warning",
            "qbittorrent.password is not set (fine if qBittorrent lets this host in without "
            "logging in)",
        )
    for problem in (*cfg.warnings, *cfg.problems):
        report("warning", problem)

    path = rules_file or cfg.rules_file
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
        report("warning", f"{path} does not exist: no rules (the rules editor creates it)")
    except OSError as e:
        text = None
        report("error", f"cannot read {path}: {e.strerror or e}")

    if text is not None and not text.strip():
        report("warning", f"{path} is empty: no rules")
    elif text is not None:
        result = validate_rules_text(
            text,
            notifications={
                "webhook_url": cfg.webhook_url.reveal() or None,
                "service": cfg.notify_service,
            },
        )
        for issue in result["issues"]:
            where = f"{path}:{issue['line']}:{issue['column']}" if issue["line"] else f"{path}"
            node = f" ({issue['path']})" if issue["path"] else ""
            typer.echo(f"{where}: {issue['severity']}: {issue['message']}{node}")
        errors += result["counts"]["error"]
        rules = len(result["summary"]["rules"])
        counts = result["counts"]
        typer.echo(
            f"Rules: {path}: {rules} rule(s), {counts['error']} error(s), "
            f"{counts['warning']} warning(s), {counts['info']} note(s)"
        )

    if errors:
        _fail(f"validation failed: {errors} error(s)")
    typer.echo("Valid.")


@rules_app.command("list")
def list_rules(json_output: JsonOption = False, config: ConfigOption = None) -> None:
    """List the rules in the order they run (file order), with their $refs resolved."""
    from qbt_rules.config_loader import Config as RulesConfig
    from qbt_rules.errors import QBittorrentError

    cfg = _load(config)
    try:
        rules = RulesConfig(cfg).get_rules()
    except QBittorrentError as e:
        _fail(f"{e}\nRun `qbt-rules validate` for every problem with line numbers.")

    if json_output:
        cli_ui.print_json(rules)
        return
    if not rules:
        cli_ui.print_message(f"No rules defined in {cfg.rules_file}")
        return
    rows = []
    for index, rule in enumerate(rules, 1):
        context = rule.get("context", "any")
        if isinstance(context, list):
            context = ",".join(context)
        rows.append(
            [
                index,
                "✓" if rule.get("enabled", True) else "✗",
                "✓" if rule.get("stop_on_match", False) else "-",
                context,
                rule.get("id", "unnamed"),
                (rule.get("meta") or {}).get("description", ""),
            ]
        )
    cli_ui.print_table(
        headers=["#", "Enabled", "Stop", "Context", "ID", "Description"],
        rows=rows,
        title=f"Rules ({len(rules)} total, execute in file order):",
    )


# -- the running server ------------------------------------------------------------------------


def _client(config: Path | None) -> Client:
    cfg = _load(config)
    # client.api_key falls back to server.api_key: right for `docker exec` into the server
    key = (cfg.client_api_key or cfg.api_key).reveal()
    if not key:
        _fail(
            "no API key to send: set client.api_key (QBT_RULES_CLIENT_API_KEY_FILE or "
            "QBT_RULES_CLIENT_API_KEY), or server.api_key, which it falls back to"
        )
    return Client(cfg.client_server_url, key)


@contextmanager
def _server_errors() -> Iterator[None]:
    """A ClientError becomes its message and exit code 1."""
    try:
        yield
    except ClientError as e:
        _fail(str(e))


def _hash(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_torrent_hash(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None


@app.command()
def execute(
    context: Annotated[
        str | None,
        typer.Option(
            "--context",
            metavar="CONTEXT",
            help="Run the rules for this context (any name your rules use). Without it, only "
            "rules with no context run.",
        ),
    ] = None,
    torrent_hash: Annotated[
        str | None,
        typer.Option(
            "--hash",
            metavar="HASH",
            help="Only this torrent (its 40-character info hash, qBittorrent's %I). Without "
            "it, every torrent.",
            callback=_hash,
        ),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait", help="Wait for the job to finish (up to 5 minutes); exit 1 if it fails."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Log what the rules would do and change nothing.")
    ] = False,
    json_output: JsonOption = False,
    config: ConfigOption = None,
) -> None:
    """Queue a job on the running server, for a context and one torrent or all of them.

    The server is `client.server_url`, and the key `client.api_key` (else `server.api_key`).
    qBittorrent's "Run external program" calls this with the torrent's hash:
    `qbt-rules execute --context torrent-imported --hash "%I"`
    """
    client = _client(config)
    with _server_errors():
        job = client.execute(context, torrent_hash, dry_run)
        if not json_output:
            cli_ui.print_message(f"✓ Job queued: {job['job_id']}")
            cli_ui.print_message(f"  Context: {context or 'none'}")
            cli_ui.print_message(f"  Hash: {torrent_hash or 'all torrents'}")
            if dry_run:
                cli_ui.print_message("  Dry run: yes")
            cli_ui.print_message(f"  Status: {job['status']}")
            cli_ui.print_message(f"  Queued at: {job['created_at']}")
        if wait:
            if not json_output:
                cli_ui.print_message(f"\nWaiting for job {job['job_id']} to finish...")
            job = client.wait(
                str(job["job_id"]),
                on_poll=(
                    (lambda status: None)
                    if json_output
                    else (lambda status: cli_ui.print_message(f"  Status: {status} (waiting...)"))
                ),
            )
    if json_output:
        cli_ui.print_json(job)
    elif wait:
        _print_outcome(job)
    if wait and job["status"] != "completed":
        raise typer.Exit(EXIT_FAILURE)


def _print_outcome(job: dict[str, Any]) -> None:
    if job["status"] == "completed":
        result = job.get("result") or {}
        cli_ui.print_message("✓ Job completed successfully")
        cli_ui.print_message(f"  Torrents processed: {result.get('torrents_processed', 0)}")
        cli_ui.print_message(f"  Rules matched: {result.get('rules_matched', 0)}")
        cli_ui.print_message(f"  Actions executed: {result.get('actions_executed', 0)}")
    elif job["status"] == "failed":
        typer.echo("✗ Job failed", err=True)
        typer.echo(f"  Error: {job.get('error') or 'Unknown error'}", err=True)
    else:
        typer.echo("Job was cancelled", err=True)


@jobs_app.command("list")
def list_jobs(
    status: Annotated[
        JobState | None,
        typer.Option(
            "--status",
            metavar="STATUS",
            help="Only jobs in this state: pending, processing, completed, failed or cancelled.",
        ),
    ] = None,
    context: Annotated[
        str | None,
        typer.Option("--context", metavar="CONTEXT", help="Only jobs with this context."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit", metavar="NUM", min=1, help="At most this many (the server caps it at 100)."
        ),
    ] = 20,
    json_output: JsonOption = False,
    config: ConfigOption = None,
) -> None:
    """List recent jobs, newest first."""
    client = _client(config)
    with _server_errors():
        data = client.jobs(status.value if status else None, context, limit)
    if json_output:
        cli_ui.print_json(data)
        return
    jobs = data["jobs"]
    if not jobs:
        cli_ui.print_message("No jobs found")
        return
    cli_ui.print_table(
        headers=["Job ID", "Status", "Context", "Created"],
        rows=[
            [job["job_id"], job["status"], job.get("context") or "none", job["created_at"]]
            for job in jobs
        ],
        title=f"Jobs (showing {len(jobs)} of {data['total']} total):",
    )


@jobs_app.command("status")
def job_status(
    job_id: JobIdArgument, json_output: JsonOption = False, config: ConfigOption = None
) -> None:
    """One job's state, timing and result."""
    client = _client(config)
    with _server_errors():
        job = client.job(job_id)
    if json_output:
        cli_ui.print_json(job)
        return
    cli_ui.print_kv_section(
        "Job Details:",
        [
            ("Job ID", job["job_id"]),
            ("Status", job["status"]),
            ("Context", job.get("context") or "none"),
            ("Hash", job.get("hash") or "all"),
            ("Dry run", "yes" if job.get("dry_run") else "no"),
            ("Created", job["created_at"]),
            ("Started", job.get("started_at") or "not started"),
            ("Completed", job.get("completed_at") or "not completed"),
        ],
    )
    if job.get("result"):
        cli_ui.print_kv_section("Result:", list(job["result"].items()), indent=2)
    if job.get("error"):
        cli_ui.print_message(f"\n  Error:\n    {job['error']}")


@jobs_app.command("cancel")
def cancel_job(
    job_id: JobIdArgument, json_output: JsonOption = False, config: ConfigOption = None
) -> None:
    """Cancel a job that hasn't started (pending). Exits 1 once it has."""
    client = _client(config)
    with _server_errors():
        body = client.cancel(job_id)
    if json_output:
        cli_ui.print_json(body)
    else:
        cli_ui.print_message(f"✓ Job cancelled: {job_id}")


@app.command()
def stats(json_output: JsonOption = False, config: ConfigOption = None) -> None:
    """The server's job counts, average run time, queue and worker."""
    client = _client(config)
    with _server_errors():
        s = client.stats()
    if json_output:
        cli_ui.print_json(s)
        return
    jobs, worker = s["jobs"], s["worker"]
    cli_ui.print_message("\nServer Statistics:")
    cli_ui.print_kv_section(
        "Jobs:",
        [(name.capitalize(), jobs[name]) for name in ("total", *JobState)],
        indent=2,
    )
    cli_ui.print_kv_section(
        "Performance:",
        [("Average execution time", s["performance"]["average_execution_time"] or "N/A")],
        indent=2,
    )
    cli_ui.print_kv_section(
        "Queue:", [("Backend", s["queue"]["backend"]), ("Depth", s["queue"]["depth"])], indent=2
    )
    cli_ui.print_kv_section(
        "Worker:",
        [
            ("Status", worker["status"]),
            ("Last job completed", worker.get("last_job_completed") or "never"),
        ],
        indent=2,
    )


# -- the 0.10.x flags-only form ----------------------------------------------------------------

# Flags that took a value, and the 0.11 setting each became (an environment variable)
_OLD_SETTING_FLAGS = {
    "--server-host": "QBT_RULES_LISTEN_HOST",
    "--server-port": "QBT_RULES_LISTEN_PORT",
    "--server-api-key": "QBT_RULES_SERVER_API_KEY_FILE",
    "--server-workers": None,
    "--client-server-url": "QBT_RULES_CLIENT_SERVER_URL",
    "--client-api-key": "QBT_RULES_CLIENT_API_KEY_FILE",
    "--queue-backend": "QBT_RULES_QUEUE_BACKEND",
    "--queue-sqlite-path": "QBT_RULES_QUEUE_SQLITE_PATH",
    "--queue-redis-url": "QBT_RULES_QUEUE_REDIS_URL",
    "--log-level": "QBT_RULES_LOGGING_LEVEL",
    "--config-dir": "QBT_RULES_CONFIG",
}
_OLD_SWITCHES = {"--trace": "QBT_RULES_LOGGING_TRACE_MODE=true (on the server)"}
_OLD_FLAGS = {
    "--serve",
    "--context",
    "--hash",
    "--wait",
    "--dry-run",
    "--list-jobs",
    "--job-status",
    "--cancel-job",
    "--stats",
    "--status-filter",
    "--limit",
    "--output",
    "--validate",
    "--list-rules",
    "--version",
    *_OLD_SETTING_FLAGS,
    *_OLD_SWITCHES,
}
_TAKES_VALUE = {
    "--context",
    "--hash",
    "--job-status",
    "--cancel-job",
    "--status-filter",
    "--limit",
    "--output",
    "--config",
    "-c",
    *_OLD_SETTING_FLAGS,
}


def old_style_hint(argv: list[str]) -> str | None:
    """The 0.11 command for a 0.10.x invocation (`qbt-rules --context X --hash Y`), or None.

    Only an invocation that starts with one of the removed flags gets an answer: the 0.10.x
    CLI had no subcommands, so anything else is left to the normal usage errors.
    """
    if not argv or argv[0].split("=", 1)[0] not in _OLD_FLAGS:
        return None
    flags: dict[str, str | bool] = {}
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        name, _, inline = arg.partition("=")
        if name in _TAKES_VALUE:
            flags[name] = inline or (rest.pop(0) if rest else "")
        else:
            flags[name] = True

    def opt(old: str, new: str | None = None) -> list[str]:
        value = flags.get(old)
        if value is None or value is False:
            return []
        if value is True:
            return [new or old]
        return [new or old, _quote(value)]

    config = opt("--config") or opt("-c", "--config")
    if "--serve" in flags:
        words = ["serve"]
    elif "--list-jobs" in flags:
        words = ["jobs", "list", *opt("--status-filter", "--status"), *opt("--limit")]
    elif "--job-status" in flags:
        words = ["jobs", "status", _quote(str(flags["--job-status"]))]
    elif "--cancel-job" in flags:
        words = ["jobs", "cancel", _quote(str(flags["--cancel-job"]))]
    elif "--stats" in flags:
        words = ["stats"]
    elif "--validate" in flags:
        words = ["validate"]
    elif "--list-rules" in flags:
        words = ["rules", "list"]
    elif "--version" in flags:
        words = ["version"]
    else:
        words = ["execute", *opt("--context"), *opt("--hash"), *opt("--wait"), *opt("--dry-run")]
    if flags.get("--output") == "json" and words[0] not in ("serve", "validate", "version"):
        words.append("--json")

    lines = [
        "error: qbt-rules 0.11 takes a command first; the 0.10.x flags-only form is gone.",
        f"  instead of: qbt-rules {' '.join(_quote(a) for a in argv)}",
        f"  run:        qbt-rules {' '.join([*words, *config])}",
    ]
    for old, variable in _OLD_SETTING_FLAGS.items():
        if old in flags:
            lines.append(
                f"  {old} is gone: set {variable}"
                if variable
                else f"  {old} is gone: the server is one process"
            )
    for old, variable in _OLD_SWITCHES.items():
        if old in flags:
            lines.append(f"  {old} is gone: set {variable}")
    if words[0] == "execute":
        lines.append(
            'qBittorrent\'s "Run external program": '
            'qbt-rules execute --context torrent-imported --hash "%I"'
        )
    lines.append("See `qbt-rules --help`, and the wiki's CLI-Reference page.")
    return "\n".join(lines)


def _quote(value: str | bool) -> str:
    import shlex

    return shlex.quote(str(value))


def main() -> None:
    hint = old_style_hint(sys.argv[1:])
    if hint:
        typer.echo(hint, err=True)
        raise SystemExit(EXIT_USAGE)
    app()
