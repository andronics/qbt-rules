"""
User-friendly error handling for qBittorrent automation
Provides clear, actionable error messages without Python stack traces
"""

import sys
from typing import Optional

from qbt_rules.logging import get_logger

logger = get_logger(__name__)


class QBittorrentError(Exception):
    """Base exception for all qBittorrent automation errors"""

    def __init__(self, code: str, message: str, details: Optional[dict] = None, fix: Optional[str] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        self.fix = fix
        super().__init__(self.format_error())

    def format_error(self) -> str:
        """Format error message for user display"""
        lines = [self.message]

        if self.details:
            for key, value in self.details.items():
                lines.append(f"  • {key}: {value}")

        if self.fix:
            lines.append(f"  • Fix: {self.fix}")

        return "\n".join(lines)


class AuthenticationError(QBittorrentError):
    """Authentication with qBittorrent failed"""

    def __init__(self, host: str, response_text: Optional[str] = None):
        details = {"Host": host}
        if response_text:
            details["Response"] = response_text

        super().__init__(
            code="AUTH-001",
            message="Cannot connect to qBittorrent",
            details=details,
            fix="Check QBITTORRENT_HOST, QBITTORRENT_USER, and QBITTORRENT_PASS environment variables"
        )


class ConnectionError(QBittorrentError):
    """Cannot reach qBittorrent server"""

    def __init__(self, host: str, original_error: str):
        super().__init__(
            code="CONN-001",
            message="Cannot reach qBittorrent server",
            details={
                "Host": host,
                "Error": str(original_error)
            },
            fix="Check that qBittorrent is running and the host/port are correct"
        )


class APIError(QBittorrentError):
    """qBittorrent API call failed"""

    def __init__(self, endpoint: str, status_code: int, response_text: Optional[str] = None):
        details = {
            "Endpoint": endpoint,
            "Status Code": status_code
        }
        if response_text:
            details["Response"] = response_text[:200]  # Limit response length

        super().__init__(
            code="API-001",
            message="qBittorrent API request failed",
            details=details,
            fix="Check qBittorrent logs for more details"
        )


class ConfigurationError(QBittorrentError):
    """Configuration file error"""

    def __init__(self, file_path: str, reason: str):
        super().__init__(
            code="CFG-001",
            message=f"Cannot load configuration",
            details={
                "File": file_path,
                "Problem": reason
            },
            fix="Check that the configuration file exists and has valid YAML syntax"
        )


class LoggingSetupError(QBittorrentError):
    """Cannot setup file logging"""

    def __init__(self, log_path: str, reason: str, config_dir: Optional[str] = None):
        details = {
            "Log Path": log_path,
            "Problem": reason
        }
        if config_dir:
            details["CONFIG_DIR"] = config_dir

        super().__init__(
            code="LOG-001",
            message="Cannot setup file logging",
            details=details,
            fix="Set LOG_FILE environment variable to a writable path (e.g., LOG_FILE=./logs/qbittorrent.log), or ensure CONFIG_DIR points to a writable location"
        )


class RuleValidationError(QBittorrentError):
    """Rule configuration is invalid"""

    def __init__(self, rule_name: str, reason: str):
        super().__init__(
            code="RULE-001",
            message=f"Invalid rule configuration",
            details={
                "Rule": rule_name,
                "Problem": reason
            },
            fix="Check the rule syntax in rules.yml"
        )


class FieldError(QBittorrentError):
    """Invalid field reference in condition"""

    def __init__(self, field: str, reason: str):
        valid_prefixes = "info.*, trackers.*, files.*, peers.*, properties.*, transfer.*, webseeds.*"
        super().__init__(
            code="FIELD-001",
            message=f"Invalid field reference",
            details={
                "Field": field,
                "Problem": reason,
                "Valid prefixes": valid_prefixes
            },
            fix="Use dot notation with API prefix (e.g., 'info.name', 'trackers.url')"
        )


class OperatorError(QBittorrentError):
    """Unknown operator in condition"""

    def __init__(self, operator: str, field: str):
        valid_operators = "==, !=, >, <, >=, <=, contains, not_contains, matches, in, not_in, older_than, newer_than"
        super().__init__(
            code="OP-001",
            message=f"Unknown operator",
            details={
                "Operator": operator,
                "Field": field,
                "Valid operators": valid_operators
            },
            fix="Use one of the supported operators"
        )


class DataNotReadyError(QBittorrentError):
    """Torrent metadata for a collection field isn't loaded yet"""

    def __init__(self, field: str, torrent_hash: str):
        super().__init__(
            code="DATA-001",
            message="Torrent metadata not yet available",
            details={
                "Field": field,
                "Hash": torrent_hash,
                "Problem": "qBittorrent returned no files for this torrent, which normally "
                           "means metadata hasn't loaded yet, not that the torrent has zero files"
            },
            fix="This rule will be skipped for this torrent on this run; it will be "
                "re-evaluated on the next trigger (e.g. context: finished, or the hourly "
                "schedule) once metadata is available"
        )


class ResolverError(QBittorrentError):
    """Base class for resolver errors"""
    pass


class InvalidRefError(ResolverError):
    """Invalid $ref path or format"""

    def __init__(self, ref_path: str, reason: str):
        super().__init__(
            code="REF-001",
            message=f"Invalid reference path: {ref_path}",
            details={"Problem": reason},
            fix="Use format 'group.name' (e.g., 'conditions.private-tracker', 'actions.safe-delete')"
        )


class UnknownRefError(ResolverError):
    """Reference not found in refs block"""

    def __init__(self, ref_path: str, available_refs: list):
        group = ref_path.split('.')[0] if '.' in ref_path else 'unknown'
        super().__init__(
            code="REF-002",
            message=f"Unknown reference: {ref_path}",
            details={
                "Reference": ref_path,
                "Available in '{group}'": ', '.join(available_refs) if available_refs else "(none defined)"
            },
            fix=f"Define '{ref_path}' in the refs.{group} section of your config"
        )


class InvalidVariableError(ResolverError):
    """Invalid variable path or format"""

    def __init__(self, var_path: str, reason: str):
        super().__init__(
            code="VAR-001",
            message=f"Invalid variable path: {var_path}",
            details={"Problem": reason},
            fix="Use format 'vars.name' (e.g., '${vars.min_ratio}')"
        )


class UnknownVariableError(ResolverError):
    """Variable not found in refs.vars"""

    def __init__(self, var_name: str, available_vars: list):
        super().__init__(
            code="VAR-002",
            message=f"Unknown variable: {var_name}",
            details={
                "Variable": var_name,
                "Available variables": ', '.join(available_vars) if available_vars else "(none defined)"
            },
            fix=f"Define '{var_name}' in the refs.vars section of your config"
        )


class CircularRefError(ResolverError):
    """Circular reference detected"""

    def __init__(self, ref_path: str, ref_stack: list):
        chain = ' -> '.join(ref_stack + [ref_path])
        super().__init__(
            code="REF-003",
            message=f"Circular reference detected",
            details={
                "Reference chain": chain,
                "Problem": f"'{ref_path}' references itself directly or indirectly"
            },
            fix="Remove the circular dependency by restructuring your refs"
        )


class RefTypeMismatchError(ResolverError):
    """Reference type does not match context"""

    def __init__(self, ref_path: str, allowed_groups: list, actual_group: str, location: str, available_refs: list = None):
        # Format allowed groups for display
        if len(allowed_groups) == 1:
            expected = f"'{allowed_groups[0]}.*'"
        else:
            expected = ' or '.join(f"'{g}.*'" for g in allowed_groups)

        # Build helpful details
        details = {
            "Reference": ref_path,
            "Location": location,
            "Expected": expected,
            "Got": f"'{actual_group}.*'"
        }

        # Add available refs if provided
        if available_refs is not None:
            group_name = allowed_groups[0] if len(allowed_groups) == 1 else 'allowed'
            details[f"Available {group_name} refs"] = ', '.join(available_refs) if available_refs else "(none defined)"

        super().__init__(
            code="REF-004",
            message=f"Reference type mismatch: cannot use '{ref_path}' in this context",
            details=details,
            fix=f"Use a {expected} reference instead, or move this reference to the appropriate block"
        )


def handle_errors(func):
    """Decorator for user-friendly error handling"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except QBittorrentError as e:
            # Our custom errors - display nicely
            logger.error(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            logger.info("\nOperation cancelled by user")
            sys.exit(0)
        except Exception as e:
            # Unexpected error - show generic message
            logger.error("Unexpected error occurred")
            logger.error(f"  • Error: {type(e).__name__}: {str(e)}")
            logger.error("  • Fix: Please report this issue with the error details above")
            logger.debug("Full stack trace:", exc_info=True)
            sys.exit(1)
    return wrapper
