"""
Centralized logging configuration for qBittorrent automation
Provides consistent logging setup across all modules and triggers
"""

import sys
import logging
from typing import Dict, Any

# Standard log formats
LOG_FORMAT_SIMPLE = '%(asctime)s | %(levelname)-8s | %(message)s'
LOG_FORMAT_DETAILED = '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(logging_config: Dict[str, Any]):
    """
    Setup logging configuration with fallback to console-only

    Configures both file and console handlers with standardized format.
    Falls back gracefully to console-only logging if file logging fails.

    Args:
        logging_config: Pre-resolved dict from cli.py's get_logging_config()
            -- {'level': str, 'file': Path, 'trace_mode': bool, 'http_access': bool}
    """
    log_level = logging_config['level']

    # Select format based on trace mode
    log_format = LOG_FORMAT_DETAILED if logging_config['trace_mode'] else LOG_FORMAT_SIMPLE

    # Try to setup file logging
    file_handler = None
    try:
        log_file = logging_config['file']
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(log_format, datefmt=DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
    except (PermissionError, OSError) as e:
        # Fall back to console-only logging
        print(f"Cannot setup file logging: {e}", file=sys.stderr)
        print(f"Continuing with console-only logging", file=sys.stderr)

    # Console handler (always works) -- stderr, not stdout, so diagnostic
    # logging never contaminates stdout data output (tables/JSON) from the
    # cli_ui layer, keeping --output json pipeable
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
