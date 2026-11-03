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
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Log file rotation defaults (logging.max_bytes / logging.backup_count)
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


def setup_logging(logging_config: dict[str, Any]) -> None:
    """
    Setup logging configuration with fallback to console-only

    Configures the console handler and, when logging.file is set, a file
    handler, each with its own format. Falls back gracefully to
    console-only logging if file logging fails. The console (stderr) is the
    template's convention, and the default: in a container it's what
    `docker logs` and Kubernetes keep.

    Args:
        logging_config: The logging settings, from `qbt-rules serve` (cli.py)
            -- {'level': str, 'file': Path or None, 'trace_mode': bool,
                'max_bytes': int, 'backup_count': int}
    """
    log_level = logging_config["level"]
    trace_mode = logging_config["trace_mode"]

    # Timestamp and level on every line, and module, function and line under
    # logging.trace_mode, on the console (what `docker logs` keeps) and in the
    # file alike. Both honour logging.level: at DEBUG a long-running server
    # writes hundreds of MB a day of per-torrent evaluation detail.
    log_format = LOG_FORMAT_DETAILED if trace_mode else LOG_FORMAT_SIMPLE

    # Try to setup file logging
    # The file rotates by size (logging.max_bytes, 0 disables rotation),
    # keeping logging.backup_count old files -- a plain FileHandler grew
    # without bound on a long-running server. The server is one process, so
    # this one handler is the only writer that rotates the file.
    file_handler = None
    log_file = logging_config.get("file")
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=logging_config.get("max_bytes", DEFAULT_MAX_BYTES),
                backupCount=logging_config.get("backup_count", DEFAULT_BACKUP_COUNT),
            )
            file_handler.setLevel(getattr(logging, log_level))
            file_handler.setFormatter(logging.Formatter(log_format, datefmt=DATE_FORMAT))
        except (PermissionError, OSError) as e:
            # Fall back to console-only logging
            print(f"Cannot setup file logging: {e}", file=sys.stderr)  # noqa: T201  logging not set up yet
            print("Continuing with console-only logging", file=sys.stderr)  # noqa: T201  logging not set up yet

    # Console handler (always works) -- stderr, not stdout, so diagnostic
    # logging never contaminates stdout data output (tables/JSON) from the
    # cli_ui layer, keeping --json pipeable
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter(log_format, datefmt=DATE_FORMAT)
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


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance configured for the module
    """
    return logging.getLogger(name)
