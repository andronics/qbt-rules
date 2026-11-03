"""Running the API: one uvicorn process (template-python decision 0008).

uvicorn handles SIGTERM and SIGINT: it stops taking requests, and the app's lifespan then
stops the worker and scheduler threads (api.BackgroundThreads) before the process exits.

uvicorn's loggers propagate to the root logger that log_setup configured (the console, and
logging.file when set, rotated by size). Its access log goes through AccessLogFilter, which
leaves out every request unless logging.http_access is on, and then removes the API key from
every logged URL.
"""

from __future__ import annotations

import logging
import re

from qbt_rules.config import Config, ConfigError

logger = logging.getLogger(__name__)

ACCESS_LOGGER = "uvicorn.access"
REDACTED = "[REDACTED]"

_KEY_PARAM = re.compile(r"(?i)([?&]key=)[^&#\s\"]*")


def redact_key(text: str) -> str:
    """Every ``key=`` query parameter's value replaced with [REDACTED]."""
    return _KEY_PARAM.sub(rf"\g<1>{REDACTED}", text)


class AccessLogFilter(logging.Filter):
    """uvicorn's access log: nothing when quiet (logging.http_access off), else without API keys.

    Quiet drops every record, not only the polling paths: the CLI's own requests (``execute
    --wait`` polls ``/api/jobs/{id}`` every 2 s) and the dashboard's are requests like any other.
    uvicorn logs ``'%s - "%s %s HTTP/%s" %d'`` with (client, method, path and query, HTTP
    version, status). Any other record on the logger is redacted as a whole message.
    """

    def __init__(self, quiet: bool) -> None:
        super().__init__()
        self.quiet = quiet

    def filter(self, record: logging.LogRecord) -> bool:
        if self.quiet:
            return False
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            client, method, _, version, status = args
            target: str = args[2]
            record.args = (client, method, redact_key(target), version, status)
            return True
        message = record.getMessage()
        redacted = redact_key(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def install_access_log_filter(quiet: bool) -> AccessLogFilter:
    """Replace any AccessLogFilter on uvicorn's access logger with a new one."""
    access = logging.getLogger(ACCESS_LOGGER)
    for existing in list(access.filters):
        if isinstance(existing, AccessLogFilter):
            access.removeFilter(existing)
    log_filter = AccessLogFilter(quiet)
    access.addFilter(log_filter)
    return log_filter


def check_one_process(config: Config) -> None:
    """Refuse server.workers above 1 at the last moment before serving.

    config.load_config already refuses it; this catches a Config built any other way
    (``dataclasses.replace``, a test, an embedding caller).
    """
    if config.workers != 1:
        raise ConfigError(
            f"server.workers is {config.workers}: qbt-rules runs one process now (uvicorn, no "
            "Gunicorn), so its worker and scheduler run exactly once. Drop the setting"
        )


def serve(config: Config) -> None:
    """Run the API under uvicorn until SIGTERM or SIGINT."""
    import uvicorn

    from qbt_rules.api import create_app

    check_one_process(config)
    install_access_log_filter(quiet=not config.http_access)
    logger.info(f"Starting server on {config.host}:{config.port}")
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        # log_setup configured logging; uvicorn's loggers propagate to it
        log_config=None,
        log_level=config.log_level.lower(),
        proxy_headers=True,
        # A request still running this long after SIGTERM is cut off, so the worker
        # thread gets its turn before Docker's 10 s stop timeout
        timeout_graceful_shutdown=3,
    )
    logger.info("Server stopped")
