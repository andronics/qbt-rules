"""
Centralized logging configuration for qBittorrent automation
Provides consistent logging setup across all modules and triggers
"""

import logging
import logging.handlers
import sys
from typing import Any

# Standard log formats
LOG_FORMAT_SIMPLE = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_FORMAT_DETAILED = (
    "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
)
CONSOLE_FORMAT_BARE = "%(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Log file rotation defaults (logging.max_bytes / logging.backup_count)
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

# Settings of the file handler installed by the last setup_logging() call,
# kept so set_file_rotation() can rebuild it in another process
_file_settings: dict[str, Any] | None = None


def setup_logging(logging_config: dict[str, Any]):
    """
    Setup logging configuration with fallback to console-only

    Configures both file and console handlers, each with its own format.
    Falls back gracefully to console-only logging if file logging fails.

    Args:
        logging_config: Pre-resolved dict from legacy_cli.py's get_logging_config()
            -- {'level': str, 'file': Path, 'trace_mode': bool,
                'http_access': bool, 'client_mode': bool,
                'max_bytes': int, 'backup_count': int}
    """
    global _file_settings

    log_level = logging_config["level"]
    trace_mode = logging_config["trace_mode"]
    client_mode = logging_config.get("client_mode", False)

    # The log file is the persistent diagnostic record -- full format
    # (timestamp, level, and function/line under --trace) so it's there to
    # review later. It honours logging.level like the console does: at
    # DEBUG a long-running server writes hundreds of MB a day of per-torrent
    # evaluation detail, so DEBUG in the file is opt-in, not the default.
    file_log_format = LOG_FORMAT_DETAILED if trace_mode else LOG_FORMAT_SIMPLE

    # In client mode (any invocation other than --serve), console output is
    # bare message text: someone running e.g. `qbt-rules --job-status <id>`
    # interactively is looking straight at the result, not a log stream, so
    # a timestamp/level prefix on every line is just noise -- the full
    # diagnostic still lands in the file above. --trace explicitly asks for
    # verbose detail, so it wins in either mode. Server mode always keeps
    # the full format, since its console output is what `docker logs`
    # captures for live monitoring.
    if trace_mode:
        console_log_format = LOG_FORMAT_DETAILED
    elif client_mode:
        console_log_format = CONSOLE_FORMAT_BARE
    else:
        console_log_format = LOG_FORMAT_SIMPLE

    # Try to setup file logging
    # The file rotates by size (logging.max_bytes, 0 disables rotation),
    # keeping logging.backup_count old files -- a plain FileHandler grew
    # without bound on a long-running server.
    file_handler = None
    _file_settings = None
    try:
        log_file = logging_config["file"]
        log_file.parent.mkdir(parents=True, exist_ok=True)

        settings = {
            "file": log_file,
            "level": getattr(logging, log_level),
            "formatter": logging.Formatter(file_log_format, datefmt=DATE_FORMAT),
            "max_bytes": logging_config.get("max_bytes", DEFAULT_MAX_BYTES),
            "backup_count": logging_config.get("backup_count", DEFAULT_BACKUP_COUNT),
        }
        file_handler = _build_file_handler(settings, rotate=True)
        _file_settings = settings
    except (PermissionError, OSError) as e:
        # Fall back to console-only logging
        print(f"Cannot setup file logging: {e}", file=sys.stderr)  # noqa: T201  logging not set up yet
        print("Continuing with console-only logging", file=sys.stderr)  # noqa: T201  logging not set up yet

    # Console handler (always works) -- stderr, not stdout, so diagnostic
    # logging never contaminates stdout data output (tables/JSON) from the
    # cli_ui layer, keeping --output json pipeable
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter(console_log_format, datefmt=DATE_FORMAT)
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers to avoid duplicates
    for handler in logger.handlers[:]:  # Iterate over copy
        handler.close()
        logger.removeHandler(handler)

    if file_handler:
        logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def _build_file_handler(settings: dict[str, Any], rotate: bool) -> logging.Handler:
    if rotate:
        handler = logging.handlers.RotatingFileHandler(
            settings["file"],
            maxBytes=settings["max_bytes"],
            backupCount=settings["backup_count"],
        )
    else:
        handler = logging.handlers.WatchedFileHandler(settings["file"])
    handler.setLevel(settings["level"])
    handler.setFormatter(settings["formatter"])
    return handler


def set_file_rotation(enabled: bool):
    """
    Switch this process's log file handler between rotating and watching

    Under Gunicorn the master and every forked worker write the same log
    file. If each one rotated it, they'd rename the file out from under
    each other (lost or misplaced lines, backups shifted twice). So only
    one process should rotate (RotatingFileHandler); the others use a
    WatchedFileHandler, which writes without rotating and reopens the file
    when it notices another process has rotated it. A no-op when file
    logging isn't active (e.g. it fell back to console-only).
    """
    if _file_settings is None:
        return
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if not isinstance(handler, logging.FileHandler):
            continue
        if isinstance(handler, logging.handlers.RotatingFileHandler) == enabled:
            continue
        root.removeHandler(handler)
        handler.close()
        root.addHandler(_build_file_handler(_file_settings, rotate=enabled))


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance configured for the module
    """
    return logging.getLogger(name)
