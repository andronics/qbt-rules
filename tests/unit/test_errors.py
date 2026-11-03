"""Comprehensive tests for errors.py - Error classes and formatting."""

import pytest
import sys
from unittest.mock import patch, MagicMock
from qbt_rules.errors import (
    QBittorrentError,
    AuthenticationError,
    ConnectionError,
    APIError,
    ConfigurationError,
    LoggingSetupError,
    RuleValidationError,
    FieldError,
    OperatorError,
    handle_errors,
)


# ============================================================================
# QBittorrentError - Base Class
# ============================================================================


class TestQBittorrentError:
    """Test base QBittorrentError class."""

    def test_basic_error(self):
        """Create basic error with minimal args."""
        error = QBittorrentError("TEST-001", "Test message")
        assert error.code == "TEST-001"
        assert error.message == "Test message"
        assert error.details == {}
        assert error.fix is None

    def test_error_with_details(self):
        """Error with details dict."""
        error = QBittorrentError(
            "TEST-001", "Test message", details={"Key1": "Value1", "Key2": "Value2"}
        )
        assert "Key1" in error.details
        assert error.details["Key1"] == "Value1"

    def test_error_with_fix(self):
        """Error with fix suggestion."""
        error = QBittorrentError("TEST-001", "Test message", fix="Do this to fix")
        assert error.fix == "Do this to fix"

    def test_format_error_basic(self):
        """Format basic error message."""
        error = QBittorrentError("TEST-001", "Test message")
        formatted = error.format_error()
        assert "Test message" in formatted

    def test_format_error_complete(self):
        """Format complete error with details and fix."""
        error = QBittorrentError(
            "TEST-001",
            "Test message",
            details={"Host": "localhost", "Port": 8080},
            fix="Check configuration",
        )
        formatted = error.format_error()
        assert "Test message" in formatted
        assert "Host: localhost" in formatted
        assert "Port: 8080" in formatted
        assert "Fix: Check configuration" in formatted


# ============================================================================
# AuthenticationError
# ============================================================================


class TestAuthenticationError:
    """Test AuthenticationError class."""

    def test_basic_auth_error(self):
        """Create authentication error."""
        error = AuthenticationError("http://localhost:8080")
        assert error.code == "AUTH-001"
        assert "cannot connect" in error.message.lower()
        assert error.details["Host"] == "http://localhost:8080"

    def test_auth_error_with_response(self):
        """Authentication error with response text."""
        error = AuthenticationError("http://localhost:8080", "Forbidden")
        assert error.details["Response"] == "Forbidden"

    def test_auth_error_has_fix(self):
        """Authentication error includes fix suggestion."""
        error = AuthenticationError("http://localhost:8080")
        assert error.fix is not None
        assert "QBITTORRENT" in error.fix


# ============================================================================
# ConnectionError
# ============================================================================


class TestConnectionError:
    """Test ConnectionError class."""

    def test_connection_error(self):
        """Create connection error."""
        error = ConnectionError("http://localhost:8080", "Connection refused")
        assert error.code == "CONN-001"
        assert "cannot reach" in error.message.lower()
        assert error.details["Host"] == "http://localhost:8080"
        assert "Connection refused" in error.details["Error"]

    def test_connection_error_has_fix(self):
        """Connection error includes fix suggestion."""
        error = ConnectionError("http://localhost:8080", "Timeout")
        assert error.fix is not None
        assert "running" in error.fix.lower()


# ============================================================================
# APIError
# ============================================================================


class TestAPIError:
    """Test APIError class."""

    def test_api_error_basic(self):
        """Create API error."""
        error = APIError("/api/v2/torrents/info", 500)
        assert error.code == "API-001"
        assert "API request failed" in error.message
        assert error.details["Endpoint"] == "/api/v2/torrents/info"
        assert error.details["Status Code"] == 500

    def test_api_error_with_response(self):
        """API error with response text."""
        error = APIError("/api/endpoint", 404, "Not found")
        assert error.details["Response"] == "Not found"

    def test_api_error_truncates_long_response(self):
        """API error truncates very long responses."""
        long_response = "x" * 300
        error = APIError("/api/endpoint", 500, long_response)
        assert len(error.details["Response"]) == 200


# ============================================================================
# ConfigurationError
# ============================================================================


class TestConfigurationError:
    """Test ConfigurationError class."""

    def test_config_error(self):
        """Create configuration error."""
        error = ConfigurationError("/config/rules.yml", "File not found")
        assert error.code == "CFG-001"
        assert "cannot load" in error.message.lower()
        assert error.details["File"] == "/config/rules.yml"
        assert error.details["Problem"] == "File not found"

    def test_config_error_has_fix(self):
        """Configuration error includes fix suggestion."""
        error = ConfigurationError("/config/rules.yml", "Invalid YAML")
        assert error.fix is not None
        assert "YAML" in error.fix


# ============================================================================
# LoggingSetupError
# ============================================================================


class TestLoggingSetupError:
    """Test LoggingSetupError class."""

    def test_logging_error_basic(self):
        """Create logging setup error."""
        error = LoggingSetupError("/var/log/qbt.log", "Permission denied")
        assert error.code == "LOG-001"
        assert "cannot setup" in error.message.lower()
        assert error.details["Log Path"] == "/var/log/qbt.log"
        assert error.details["Problem"] == "Permission denied"

    def test_logging_error_with_config_dir(self):
        """Logging error with config dir."""
        error = LoggingSetupError("/var/log/qbt.log", "Permission denied", "/config")
        assert error.details["CONFIG_DIR"] == "/config"

    def test_logging_error_has_fix(self):
        """Logging error includes fix suggestion."""
        error = LoggingSetupError("/var/log/qbt.log", "Permission denied")
        assert error.fix is not None
        assert "LOG_FILE" in error.fix


# ============================================================================
# RuleValidationError
# ============================================================================


class TestRuleValidationError:
    """Test RuleValidationError class."""

    def test_rule_validation_error(self):
        """Create rule validation error."""
        error = RuleValidationError("My Rule", "Missing 'actions' field")
        assert error.code == "RULE-001"
        assert "invalid rule" in error.message.lower()
        assert error.details["Rule"] == "My Rule"
        assert error.details["Problem"] == "Missing 'actions' field"

    def test_rule_validation_error_has_fix(self):
        """Rule validation error includes fix suggestion."""
        error = RuleValidationError("My Rule", "Invalid syntax")
        assert error.fix is not None
        assert "rules.yml" in error.fix


# ============================================================================
# FieldError
# ============================================================================


class TestFieldError:
    """Test FieldError class."""

    def test_field_error(self):
        """Create field error."""
        error = FieldError("invalid.field", "Unknown prefix")
        assert error.code == "FIELD-001"
        assert "invalid field" in error.message.lower()
        assert error.details["Field"] == "invalid.field"
        assert error.details["Problem"] == "Unknown prefix"

    def test_field_error_includes_valid_prefixes(self):
        """Field error lists valid prefixes."""
        error = FieldError("bad.field", "Unknown prefix")
        assert "Valid prefixes" in error.details
        assert "info.*" in error.details["Valid prefixes"]
        assert "trackers.*" in error.details["Valid prefixes"]

    def test_field_error_has_fix(self):
        """Field error includes fix suggestion."""
        error = FieldError("badfield", "No dot notation")
        assert error.fix is not None
        assert "dot notation" in error.fix


# ============================================================================
# OperatorError
# ============================================================================


class TestOperatorError:
    """Test OperatorError class."""

    def test_operator_error(self):
        """Create operator error."""
        error = OperatorError("unknown_op", "info.name")
        assert error.code == "OP-001"
        assert "unknown operator" in error.message.lower()
        assert error.details["Operator"] == "unknown_op"
        assert error.details["Field"] == "info.name"

    def test_operator_error_includes_valid_operators(self):
        """Operator error lists valid operators."""
        error = OperatorError("bad_op", "info.ratio")
        assert "Valid operators" in error.details
        assert "==" in error.details["Valid operators"]
        assert "contains" in error.details["Valid operators"]
        assert "older_than" in error.details["Valid operators"]

    def test_operator_error_has_fix(self):
        """Operator error includes fix suggestion."""
        error = OperatorError("bad_op", "info.field")
        assert error.fix is not None
        assert "supported operators" in error.fix


# ============================================================================
# handle_errors decorator
# ============================================================================


class TestHandleErrorsDecorator:
    """Test handle_errors decorator."""

    def test_successful_execution(self):
        """Decorator allows successful execution."""

        @handle_errors
        def successful_func():
            return "success"

        result = successful_func()
        assert result == "success"

    def test_handles_qbittorrent_error(self):
        """Decorator catches QBittorrentError and exits."""

        @handle_errors
        def error_func():
            raise ConfigurationError("/config/test.yml", "Test error")

        with patch("sys.exit") as mock_exit:
            error_func()
            mock_exit.assert_called_once_with(1)

    def test_handles_keyboard_interrupt(self):
        """Decorator handles KeyboardInterrupt gracefully."""

        @handle_errors
        def interrupted_func():
            raise KeyboardInterrupt()

        with patch("sys.exit") as mock_exit:
            interrupted_func()
            mock_exit.assert_called_once_with(0)

    def test_handles_unexpected_exception(self):
        """Decorator handles unexpected exceptions."""

        @handle_errors
        def unexpected_error_func():
            raise ValueError("Unexpected error")

        with patch("sys.exit") as mock_exit:
            unexpected_error_func()
            mock_exit.assert_called_once_with(1)

    def test_preserves_function_args(self):
        """Decorator preserves function arguments."""

        @handle_errors
        def func_with_args(a, b, c=None):
            return f"{a}-{b}-{c}"

        result = func_with_args("x", "y", c="z")
        assert result == "x-y-z"
