"""Tests for arguments module."""

import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from qbt_rules.arguments import (
    smart_config_default,
    create_parser,
    validate_torrent_hash,
    process_args,
    handle_utility_args,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean up environment variables before and after each test."""
    # Clean up before test
    monkeypatch.delenv('DRY_RUN', raising=False)
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    monkeypatch.delenv('TRACE_MODE', raising=False)

    yield

    # Clean up after test
    monkeypatch.delenv('DRY_RUN', raising=False)
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    monkeypatch.delenv('TRACE_MODE', raising=False)


class TestSmartConfigDefault:
    """Test smart config directory default logic."""

    def test_returns_local_config_when_exists(self, tmp_path, monkeypatch):
        """Returns ./config when it exists as a directory."""
        # Change to tmp_path and create config directory
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        result = smart_config_default()
        assert result == "./config"

    def test_returns_docker_config_when_local_missing(self, tmp_path, monkeypatch):
        """Returns /config when ./config doesn't exist."""
        # Change to tmp_path where no config dir exists
        monkeypatch.chdir(tmp_path)

        result = smart_config_default()
        assert result == "/config"

    def test_returns_docker_config_when_local_is_file(self, tmp_path, monkeypatch):
        """Returns /config when ./config exists but is a file."""
        # Change to tmp_path and create config as a file
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "config"
        config_file.write_text("not a directory")

        result = smart_config_default()
        assert result == "/config"


class TestCreateParser:
    """Test argument parser creation."""

    def test_create_parser_returns_argumentparser(self):
        """create_parser returns ArgumentParser instance."""
        parser = create_parser()
        assert parser is not None
        assert hasattr(parser, 'parse_args')

    def test_parser_has_context_argument(self):
        """Parser includes --context argument."""
        parser = create_parser()
        args = parser.parse_args(['--context', 'adhoc-run'])
        assert args.context == 'adhoc-run'

    def test_parser_has_torrent_hash_argument(self):
        """Parser includes --hash argument."""
        parser = create_parser()
        args = parser.parse_args(['--hash', 'a' * 40])
        assert args.hash == 'a' * 40

    def test_parser_has_config_dir_argument(self):
        """Parser includes --config-dir argument."""
        parser = create_parser()
        args = parser.parse_args(['--config-dir', '/tmp/config'])
        assert args.config_dir == Path('/tmp/config')

    def test_parser_has_dry_run_argument(self):
        """Parser includes --dry-run argument."""
        parser = create_parser()
        args = parser.parse_args(['--dry-run'])
        assert args.dry_run is True

    def test_parser_dry_run_default_false(self):
        """Parser --dry-run defaults to False."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.dry_run is False

    def test_parser_has_log_level_argument(self):
        """Parser includes --log-level argument."""
        parser = create_parser()
        args = parser.parse_args(['--log-level', 'DEBUG'])
        assert args.log_level == 'DEBUG'

    def test_parser_log_level_choices(self):
        """Parser --log-level accepts valid choices."""
        parser = create_parser()
        for level in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
            args = parser.parse_args(['--log-level', level])
            assert args.log_level == level

    def test_parser_has_trace_argument(self):
        """Parser includes --trace argument."""
        parser = create_parser()
        args = parser.parse_args(['--trace'])
        assert args.trace is True

    def test_parser_trace_default_false(self):
        """Parser --trace defaults to False."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.trace is False

    def test_parser_has_validate_argument(self):
        """Parser includes --validate argument."""
        parser = create_parser()
        args = parser.parse_args(['--validate'])
        assert args.validate is True

    def test_parser_has_list_rules_argument(self):
        """Parser includes --list-rules argument."""
        parser = create_parser()
        args = parser.parse_args(['--list-rules'])
        assert args.list_rules is True

    def test_parser_has_version_argument(self):
        """Parser includes --version argument."""
        parser = create_parser()
        # Version argument exits, so we can't test it directly
        # Just verify the parser was created successfully
        assert parser is not None


class TestValidateTorrentHash:
    """Test torrent hash validation."""

    def test_valid_hash_lowercase(self):
        """Valid lowercase hex hash passes."""
        hash_val = 'a' * 40
        result = validate_torrent_hash(hash_val)
        assert result == hash_val

    def test_valid_hash_uppercase_returns_lowercase(self):
        """Valid uppercase hex hash is converted to lowercase."""
        hash_val = 'A' * 40
        result = validate_torrent_hash(hash_val)
        assert result == 'a' * 40

    def test_valid_hash_mixed_case_returns_lowercase(self):
        """Valid mixed case hex hash is converted to lowercase."""
        hash_val = 'AbCdEf0123456789' * 2 + '01234567'  # 40 chars
        result = validate_torrent_hash(hash_val)
        assert result == hash_val.lower()

    def test_valid_hex_characters(self):
        """Valid hash with all hex characters (0-9, a-f)."""
        hash_val = '0123456789abcdef' * 2 + '01234567'  # 40 chars
        result = validate_torrent_hash(hash_val)
        assert result == hash_val.lower()

    def test_none_raises_valueerror(self):
        """None input raises ValueError."""
        with pytest.raises(ValueError, match="Torrent hash is required"):
            validate_torrent_hash(None)

    def test_empty_string_raises_valueerror(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Torrent hash is required"):
            validate_torrent_hash('')

    def test_too_short_raises_valueerror(self):
        """Hash with 39 characters raises ValueError."""
        with pytest.raises(ValueError, match="Invalid torrent hash length"):
            validate_torrent_hash('a' * 39)

    def test_too_long_raises_valueerror(self):
        """Hash with 41 characters raises ValueError."""
        with pytest.raises(ValueError, match="Invalid torrent hash length"):
            validate_torrent_hash('a' * 41)

    def test_invalid_characters_raises_valueerror(self):
        """Hash with non-hex characters raises ValueError."""
        with pytest.raises(ValueError, match="Invalid torrent hash format"):
            validate_torrent_hash('g' * 40)

    def test_special_characters_raises_valueerror(self):
        """Hash with special characters raises ValueError."""
        with pytest.raises(ValueError, match="Invalid torrent hash format"):
            validate_torrent_hash('a' * 39 + '!')

    def test_spaces_raises_valueerror(self):
        """Hash with spaces raises ValueError."""
        with pytest.raises(ValueError, match="Invalid torrent hash format"):
            validate_torrent_hash('a' * 20 + ' ' + 'a' * 19)


class TestProcessArgs:
    """Test argument processing."""

    def test_sets_dry_run_env_var_when_true(self, monkeypatch):
        """Sets DRY_RUN environment variable when args.dry_run=True."""
        # Clean env
        monkeypatch.delenv('DRY_RUN', raising=False)

        args = Mock()
        args.dry_run = True
        args.log_level = None
        args.trace = False
        args.config_dir = '/test/config'

        process_args(args)

        assert os.environ.get('DRY_RUN') == 'true'

    def test_does_not_set_dry_run_when_false(self, monkeypatch):
        """Doesn't set DRY_RUN environment variable when args.dry_run=False."""
        # Clean env
        monkeypatch.delenv('DRY_RUN', raising=False)

        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = False
        args.config_dir = '/test/config'

        process_args(args)

        assert 'DRY_RUN' not in os.environ

    def test_sets_log_level_env_var(self, monkeypatch):
        """Sets LOG_LEVEL environment variable when provided."""
        # Clean env
        monkeypatch.delenv('LOG_LEVEL', raising=False)

        args = Mock()
        args.dry_run = False
        args.log_level = 'DEBUG'
        args.trace = False
        args.config_dir = '/test/config'

        process_args(args)

        assert os.environ.get('LOG_LEVEL') == 'DEBUG'

    def test_sets_trace_mode_env_var(self, monkeypatch):
        """Sets TRACE_MODE environment variable when args.trace=True."""
        # Clean env
        monkeypatch.delenv('TRACE_MODE', raising=False)

        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = True
        args.config_dir = '/test/config'

        process_args(args)

        assert os.environ.get('TRACE_MODE') == 'true'

    def test_config_dir_from_args_highest_priority(self, monkeypatch):
        """config_dir from args.config_dir has highest priority."""
        # Set env var
        monkeypatch.setenv('CONFIG_DIR', '/env/config')

        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = False
        args.config_dir = Path('/args/config')  # Parser returns Path

        result = process_args(args)

        assert result == Path('/args/config')

    def test_config_dir_from_env_var_medium_priority(self, monkeypatch):
        """config_dir from CONFIG_DIR env var when args.config_dir is None."""
        # Set env var
        monkeypatch.setenv('CONFIG_DIR', '/env/config')

        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = False
        args.config_dir = None

        result = process_args(args)

        assert result == Path('/env/config')

    def test_config_dir_from_smart_default_lowest_priority(self, monkeypatch, tmp_path):
        """config_dir from smart_config_default() when no args or env."""
        # Clean env
        monkeypatch.delenv('CONFIG_DIR', raising=False)
        # Create config dir for smart default
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = False
        args.config_dir = None

        result = process_args(args)

        assert result == Path('./config')

    def test_returns_path_object(self):
        """process_args returns Path object."""
        args = Mock()
        args.dry_run = False
        args.log_level = None
        args.trace = False
        args.config_dir = Path('/test/config')  # Parser returns Path

        result = process_args(args)

        assert isinstance(result, Path)
        assert result == Path('/test/config')


class TestHandleUtilityArgs:
    """Test utility argument handling."""

    def test_returns_false_when_no_utility_args(self):
        """Returns False when neither validate nor list_rules set."""
        args = Mock()
        args.validate = False
        args.list_rules = False

        mock_config = Mock()

        result = handle_utility_args(args, mock_config)

        assert result is False

    def test_validate_returns_true(self):
        """Returns True when args.validate=True."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_qbittorrent_config.return_value = {
            'host': 'localhost',
            'user': 'admin',
            'pass': 'admin'
        }
        mock_config.get_rules.return_value = []

        result = handle_utility_args(args, mock_config)

        assert result is True

    def test_validate_checks_qbittorrent_config(self):
        """Validate checks qBittorrent configuration via the real
        get_qbittorrent_config() (cli.py), not a Config method -- the
        deferred `from qbt_rules.cli import get_qbittorrent_config` inside
        handle_utility_args() means the patch target is where it's
        defined, not where it's used."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_rules.return_value = []

        with patch('qbt_rules.cli.get_qbittorrent_config') as mock_get_qbt:
            mock_get_qbt.return_value = {
                'host': 'localhost',
                'username': 'admin',
                'password': 'admin',
            }
            handle_utility_args(args, mock_config)

            mock_get_qbt.assert_called_once_with(args, mock_config)

    def test_validate_with_missing_qbittorrent_config(self, capsys):
        """Validate handles missing qBittorrent config fields."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_rules.return_value = []

        with patch('qbt_rules.cli.get_qbittorrent_config') as mock_get_qbt:
            mock_get_qbt.return_value = {
                'host': 'localhost',
                'username': '',
                'password': '',
            }
            result = handle_utility_args(args, mock_config)

        # Should still return True (validation completes with errors)
        assert result is True

    def test_validate_loads_rules(self):
        """Validate loads and counts rules."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_rules.return_value = [
            {'name': 'Rule 1', 'enabled': True, 'conditions': {'all': []}, 'actions': []},
            {'name': 'Rule 2', 'enabled': True, 'conditions': {'all': []}, 'actions': []},
        ]

        with patch('qbt_rules.cli.get_qbittorrent_config') as mock_get_qbt:
            mock_get_qbt.return_value = {
                'host': 'localhost',
                'username': 'admin',
                'password': 'admin',
            }
            handle_utility_args(args, mock_config)

        # Should call get_rules
        mock_config.get_rules.assert_called_once()

    def test_validate_with_no_rules_warns(self, capsys):
        """Validate warns when no rules defined."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_qbittorrent_config.return_value = {
            'host': 'localhost',
            'user': 'admin',
            'pass': 'admin'
        }
        mock_config.get_rules.return_value = []

        handle_utility_args(args, mock_config)

        # Should complete without error

    def test_list_rules_returns_true(self):
        """Returns True when args.list_rules=True."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = []

        result = handle_utility_args(args, mock_config)

        assert result is True

    def test_list_rules_displays_rules(self):
        """list_rules displays all rules."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = [
            {
                'name': 'Test Rule',
                'enabled': True,
                'stop_on_match': False,
                'conditions': {'trigger': 'adhoc-run', 'all': []},
                'actions': []
            }
        ]

        handle_utility_args(args, mock_config)

        # Should call get_rules
        mock_config.get_rules.assert_called_once()

    def test_list_rules_with_enabled_status(self):
        """list_rules shows enabled status."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = [
            {'name': 'Enabled Rule', 'enabled': True, 'conditions': {}, 'actions': []},
            {'name': 'Disabled Rule', 'enabled': False, 'conditions': {}, 'actions': []},
        ]

        handle_utility_args(args, mock_config)

        # Should process both rules

    def test_list_rules_with_context_filter(self):
        """list_rules shows trigger filter."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = [
            {'name': 'Manual Rule', 'enabled': True, 'conditions': {'trigger': 'adhoc-run'}, 'actions': []},
            {'name': 'Multi Context', 'enabled': True, 'conditions': {'trigger': ['adhoc-run', 'weekly-cleanup']}, 'actions': []},
            {'name': 'No Context', 'enabled': True, 'conditions': {}, 'actions': []},
        ]

        handle_utility_args(args, mock_config)

        # Should process all rules

    def test_list_rules_with_unnamed_rule(self):
        """list_rules handles rules with no name."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = [
            {'enabled': True, 'conditions': {}, 'actions': []},  # No name field
        ]

        handle_utility_args(args, mock_config)

        # Should handle unnamed rule gracefully

    def test_list_rules_with_empty_list(self):
        """list_rules handles empty rules list."""
        args = Mock()
        args.validate = False
        args.list_rules = True

        mock_config = Mock()
        mock_config.get_rules.return_value = []

        handle_utility_args(args, mock_config)

        # Should complete without error

    def test_validate_warns_on_rule_with_no_conditions(self, caplog):
        """Validate warns when a rule has no conditions."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_qbittorrent_config.return_value = {
            'host': 'localhost',
            'user': 'admin',
            'pass': 'admin'
        }
        mock_config.get_rules.return_value = [
            {
                'name': 'NoConditionsRule',
                'actions': [{'action': 'set_category', 'category': 'test'}]
                # Missing 'conditions'
            }
        ]

        result = handle_utility_args(args, mock_config)

        # Check that warning was logged
        assert any("No conditions defined" in record.message for record in caplog.records)
        assert result is True

    def test_validate_succeeds_with_complete_rule(self):
        """Validate succeeds for a rule with both conditions and actions (covers line 248)."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_qbittorrent_config.return_value = {
            'host': 'localhost',
            'user': 'admin',
            'pass': 'admin'
        }
        mock_config.get_rules.return_value = [
            {
                'name': 'CompleteRule',
                'conditions': {'all': [{'field': 'info.ratio', 'operator': '>=', 'value': 1.0}]},
                'actions': [{'action': 'set_category', 'category': 'test'}]
            }
        ]

        result = handle_utility_args(args, mock_config)

        # This test primarily ensures line 248 is covered (success logging path)
        assert result is True

    def test_validate_handles_exception(self):
        """Validate handles exceptions gracefully."""
        args = Mock()
        args.validate = True
        args.list_rules = False

        mock_config = Mock()
        mock_config.get_qbittorrent.side_effect = Exception("Config error")

        # Should not raise, just log error
        result = handle_utility_args(args, mock_config)

        assert result is True
