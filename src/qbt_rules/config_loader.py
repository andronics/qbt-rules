"""
The running configuration: the settings (config.py, on interpose) plus rules.yml

config.py resolves every setting once, at startup. rules.yml is different: it is
re-read whenever it changes on disk (hot reload), and the dashboard's editor
writes it, so it lives here, with the RuleResolver that expands its refs.

A missing rules.yml is not an error: there are simply no rules until one is
written (the editor creates it on its first save). An empty one is the same.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

from qbt_rules import config as settings_module
from qbt_rules.errors import ConfigurationError
from qbt_rules.resolver import RuleResolver
from qbt_rules.rules_validation import check_rules_structure

logger = logging.getLogger(__name__)


def load_yaml_file(file_path: Path) -> dict[str, Any]:
    """
    Load a YAML mapping, with errors a user can act on

    A missing or empty file is an empty mapping.

    Raises:
        ConfigurationError: If the file can't be read or isn't a YAML mapping
    """
    try:
        with open(file_path) as f:
            content: Any = yaml.safe_load(f)
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        raise ConfigurationError(str(file_path), f"Invalid YAML syntax: {e!s}") from e
    except PermissionError as e:
        raise ConfigurationError(str(file_path), "Permission denied - cannot read file") from e
    except OSError as e:
        raise ConfigurationError(str(file_path), f"Cannot read file: {e!s}") from e

    if content is None:
        return {}
    if not isinstance(content, dict):
        raise ConfigurationError(str(file_path), "The top level must be a mapping")
    return content


class Config:
    """The settings, and rules.yml with hot reload"""

    def __init__(self, settings: settings_module.Config):
        self.settings = settings
        self.config_file = settings.config_file
        self.rules_file = settings.rules_file
        self.history_dir = settings.history_dir
        self.schedule: list[dict[str, str]] = [
            {"cron": entry.cron, "context": entry.context} for entry in settings.schedule
        ]

        # Resolver and cache for resolved rules (set by _load_rules)
        self._resolver: RuleResolver | None = None
        self._resolved_rules_cache: list[dict[str, Any]] | None = None

        self._load_rules()

        # rules.yml's identity when last loaded, for hot-reload. None makes
        # the first get_rules() re-read it.
        self._rules_stamp: tuple[int, int, int] | None = None

    def _load_rules(self) -> None:
        """Load rules.yml and initialize resolver

        Everything is validated before any of it is assigned, so a reload
        that fails leaves the previously loaded rules, refs and resolver
        fully intact (get_rules() relies on that to keep serving them).
        """
        logger.debug(f"Loading rules from {self.rules_file}")

        if not self.rules_file.exists():
            logger.warning(
                f"{self.rules_file} does not exist: no rules are loaded until it does (the "
                "dashboard's rules editor creates it on its first save)"
            )
        raw_rules = load_yaml_file(self.rules_file)

        # The same checks the rules editor runs before it will save a file
        # (rules_validation.check_rules_structure) -- here only the first
        # problem is reported, as a ConfigurationError.
        problems = check_rules_structure(raw_rules)
        if problems:
            raise ConfigurationError(str(self.rules_file), problems[0].message)

        rules: list[dict[str, Any]] = raw_rules.get("rules") or []
        logger.debug(f"Loaded {len(rules)} rules")

        # Extract refs block and initialize resolver
        refs = raw_rules.get("refs") or {}
        instances = raw_rules.get("instances") or {}

        # Create resolver with global refs
        # TODO: Support per-instance resolvers when running against specific instances
        resolver = RuleResolver(refs=refs, instance_id=None, instances=instances)

        # Schema marker for rules.yml, defaulting to 1 for files written
        # before this existed. Not consulted by anything today -- purely a
        # forward-compat hook so a future migration can tell "this file
        # predates schema versioning" from "this file already declared one"
        # without sniffing structure. Refreshed on every hot-reload since
        # this is set inside _load_rules(), which get_rules() re-invokes
        # when rules.yml changes on disk.
        self.rules_version = raw_rules.get("version", 1)
        self.rules = rules
        self._resolver = resolver

        # Invalidate resolved rules cache
        self._resolved_rules_cache = None

        if refs:
            logger.debug(
                f"Initialized resolver with refs: vars={len(resolver.vars)}, "
                f"conditions={len(resolver.conditions)}, "
                f"actions={len(resolver.actions)}"
            )

    def is_dry_run(self) -> bool:
        """Whether dry_run (QBT_RULES_DRY_RUN, or --dry-run) is on"""
        return self.settings.dry_run

    def _current_rules_stamp(self) -> tuple[int, int, int]:
        """
        rules.yml's identity on disk: any change to it means reload

        Compared for inequality rather than "mtime went up", so a file
        swapped for an older one (a restored backup, `cp -p`, a git
        checkout) still reloads. Inode catches an atomic replace even
        within one mtime tick; size catches an in-place rewrite. A missing
        file is (0, 0, 0), so creating it reloads too.
        """
        try:
            st = self.rules_file.stat()
        except FileNotFoundError:
            return (0, 0, 0)
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    def reload_rules(self, force: bool = False) -> bool:
        """
        Re-read rules.yml if it changed on disk since it was last loaded
        (or unconditionally with force=True)

        Raises whatever loading raises -- ConfigurationError for a file the
        loader rejects -- leaving the previously loaded rules in place.

        Returns:
            True if the rules were reloaded
        """
        stamp = self._current_rules_stamp()
        if not force and stamp == self._rules_stamp:
            return False
        self._load_rules()
        self._rules_stamp = stamp
        logger.info(f"Rules reloaded from {self.rules_file}")
        return True

    def get_rules(self, resolved: bool = True) -> list[dict[str, Any]]:
        """
        Get list of rules with hot-reload support

        Re-reads rules.yml if the file has been modified since last load.
        This allows rules to be updated without restarting the server.

        Args:
            resolved: If True, return rules with refs/vars resolved (default: True)
                     If False, return raw rules without resolution

        Returns:
            List of rule dictionaries

        Note:
            If reload fails (syntax error, etc.), the previously loaded
            rules are retained and a warning is logged.

        Examples:
            >>> config.get_rules()  # Resolved rules (default)
            [{'id': 'cleanup', 'conditions': [...], 'actions': [...]}]

            >>> config.get_rules(resolved=False)  # Raw rules
            [{'id': 'cleanup', 'conditions': [{'$ref': 'conditions.well-seeded'}], ...}]
        """
        try:
            self.reload_rules()
        except Exception as e:
            # Keep existing rules on error - graceful degradation
            logger.warning(
                f"Failed to reload rules from {self.rules_file}: {e}. Using cached rules."
            )

        # Return raw rules if requested
        if not resolved:
            return self.rules

        # Return cached resolved rules if available
        if self._resolved_rules_cache is not None:
            return self._resolved_rules_cache

        # Resolve rules and cache the result
        if self._resolver is None:
            # No refs block - return raw rules
            self._resolved_rules_cache = self.rules
        else:
            # Resolve each rule
            resolved_rules = []
            for rule in self.rules:
                try:
                    resolved_rule = self._resolver.resolve_rule(rule)
                    resolved_rules.append(resolved_rule)
                except Exception as e:
                    # Log error with rule id for debugging
                    rule_id = rule.get("id", "unknown")
                    logger.error(f"Failed to resolve rule '{rule_id}': {e}")
                    raise  # Re-raise to surface the error

            self._resolved_rules_cache = resolved_rules
            logger.debug(f"Resolved and cached {len(resolved_rules)} rules")

        return self._resolved_rules_cache


def load_config(path: Path | None = None, environ: dict[str, str] | None = None) -> Config:
    """
    Load the settings (config.load_config) and rules.yml

    Args:
        path: The config file; None reads QBT_RULES_CONFIG, else /etc/qbt-rules/config.yaml
        environ: The environment; None is os.environ

    Raises:
        config.ConfigError: A setting is invalid, or one that was removed is still set
        ConfigurationError: rules.yml can't be loaded
    """
    return Config(settings_module.load_config(path, environ))
