"""
qBittorrent Rules Engine
Core logic for evaluating conditions and executing actions
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple

from qbt_rules.api import QBittorrentAPI
from qbt_rules.utils import parse_tags, is_older_than, is_newer_than, is_larger_than, is_smaller_than
from qbt_rules.errors import FieldError, OperatorError
from qbt_rules.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RuleStats:
    """Statistics for rule execution"""
    total_torrents: int = 0
    processed: int = 0
    rules_matched: int = 0
    actions_executed: int = 0
    actions_skipped: int = 0
    errors: int = 0


class ConditionEvaluator:
    """Evaluates rule conditions against torrents using dot notation"""

    def __init__(self, api: QBittorrentAPI):
        """
        Initialize condition evaluator

        Args:
            api: qBittorrent API client
        """
        self.api = api

        # Caches for per-torrent API calls
        self.trackers_cache: Dict[str, List[Dict]] = {}
        self.files_cache: Dict[str, List[Dict]] = {}
        self.peers_cache: Dict[str, List[Dict]] = {}
        self.properties_cache: Dict[str, Dict] = {}
        self.webseeds_cache: Dict[str, List[Dict]] = {}

        # Global context cache (shared across all torrents)
        self.transfer_info: Optional[Dict] = None
        self.app_preferences: Optional[Dict] = None

    def clear_caches(self):
        """Clear all caches (call between rule executions)"""
        self.trackers_cache.clear()
        self.files_cache.clear()
        self.peers_cache.clear()
        self.properties_cache.clear()
        self.webseeds_cache.clear()
        self.transfer_info = None
        self.app_preferences = None

    def evaluate(self, torrent: Dict, conditions: Any, current_context: Optional[str] = None, required_context: Optional[Any] = None) -> bool:
        """
        Evaluate all conditions for a torrent

        Args:
            torrent: Torrent dictionary from qBittorrent API
            conditions: Conditions from rule. Either a dict with 'all'/'any'/'none' keys,
                        or a bare list of condition entries (treated as an implicit 'all')
            current_context: Current runtime context (torrent-imported, download-finished, weekly-cleanup, adhoc-run, custom, or None)
            required_context: Context requirement from rule level (string or list of strings)
                            When None, rule has no context requirement and executes regardless of runtime context

        Returns:
            True if all conditions match

        Notes:
            - Rules WITHOUT context (required_context=None) execute regardless of runtime context
            - Rules WITH context only execute when runtime context matches their requirement
            - A bare list for `conditions` (no 'all'/'any'/'none' wrapper) is treated as an
              implicit 'all': every entry must match. Without this, a bare list silently
              matched nothing in 'all'/'any'/'none' and always evaluated to True.
        """
        try:
            # Check context requirement first (from rule level, not inside conditions)
            if required_context is not None:
                if not self._evaluate_context(current_context, required_context):
                    return False
            # If required_context is None, rule has no context requirement → continue to conditions

            # A bare list of conditions is shorthand for {'all': conditions}
            if isinstance(conditions, list):
                return self._evaluate_all(torrent, conditions)

            # Evaluate logical groups
            if 'all' in conditions:
                if not self._evaluate_all(torrent, conditions['all']):
                    return False

            if 'any' in conditions:
                if not self._evaluate_any(torrent, conditions['any']):
                    return False

            if 'none' in conditions:
                if not self._evaluate_none(torrent, conditions['none']):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error evaluating conditions for {torrent.get('name', 'unknown')}: {e}")
            return False

    def _evaluate_context(self, current_context: Optional[str], required_context: Any) -> bool:
        """
        Evaluate if current runtime context matches the rule's context requirement

        Args:
            current_context: Current runtime context (torrent-imported, weekly-cleanup, adhoc-run, etc.)
                           Can be None if running without a specific context
            required_context: Rule's context requirement (string or list of strings)
                            This is always non-None when this method is called

        Returns:
            True if runtime context matches the requirement, False otherwise

        Notes:
            - This method is only called when a rule HAS a context requirement (required_context is not None)
            - If current_context is None, the rule cannot match (no runtime context to match against)
            - If required_context is a list, checks if current_context is in that list
            - If required_context is a string, checks for exact match
        """
        if current_context is None:
            # No runtime context provided, but rule requires one → no match
            return False

        if isinstance(required_context, list):
            return current_context in required_context
        else:
            return current_context == required_context

    def _evaluate_all(self, torrent: Dict, conditions: List[Dict]) -> bool:
        """All conditions must match (AND)"""
        return all(self._evaluate_condition(torrent, cond) for cond in conditions)

    def _evaluate_any(self, torrent: Dict, conditions: List[Dict]) -> bool:
        """Any condition must match (OR)"""
        return any(self._evaluate_condition(torrent, cond) for cond in conditions)

    def _evaluate_none(self, torrent: Dict, conditions: List[Dict]) -> bool:
        """No conditions must match (NOT)"""
        return not any(self._evaluate_condition(torrent, cond) for cond in conditions)

    def _evaluate_condition(self, torrent: Dict, condition: Dict) -> bool:
        """
        Evaluate a single condition

        Args:
            torrent: Torrent dictionary
            condition: Condition dictionary with field, operator, value OR nested logical operator

        Returns:
            True if condition matches
        """
        # Handle nested logical operators
        if 'all' in condition:
            return self._evaluate_all(torrent, condition['all'])
        if 'any' in condition:
            return self._evaluate_any(torrent, condition['any'])
        if 'none' in condition:
            return self._evaluate_none(torrent, condition['none'])

        # Handle regular field conditions
        field = condition['field']
        operator = condition['operator']
        value = condition['value']

        # Get field value using dot notation
        actual = self._get_field_value(torrent, field)

        # Evaluate based on operator
        return self._apply_operator(actual, operator, value, field)

    def _get_field_value(self, torrent: Dict, field: str) -> Any:
        """
        Get field value with automatic API endpoint routing

        Args:
            torrent: Torrent dictionary
            field: Field name in dot notation (e.g., 'info.name', 'trackers.url')

        Returns:
            Field value

        Raises:
            FieldError: If field format is invalid
        """
        if '.' not in field:
            raise FieldError(
                field,
                "Field must use dot notation with API prefix"
            )

        # Split into API endpoint and property
        endpoint, property_name = field.split('.', 1)
        torrent_hash = torrent.get('hash', '')

        # Route to appropriate API endpoint
        if endpoint == 'info':
            # Base torrent info - already available, no API call
            if property_name == 'tags':
                return parse_tags(torrent)
            return torrent.get(property_name)

        elif endpoint == 'trackers':
            # Trackers collection - lazy load with cache
            if torrent_hash not in self.trackers_cache:
                self.trackers_cache[torrent_hash] = self.api.get_trackers(torrent_hash)
            items = self.trackers_cache[torrent_hash]
            # Filter out special entries (DHT, PeX, LSD)
            items = [t for t in items if t.get('url', '').startswith('http')]
            # Return list of property values
            return [item.get(property_name) for item in items if property_name in item]

        elif endpoint == 'files':
            # Files collection - lazy load with cache
            if torrent_hash not in self.files_cache:
                self.files_cache[torrent_hash] = self.api.get_files(torrent_hash)
            items = self.files_cache[torrent_hash]
            return [item.get(property_name) for item in items if property_name in item]

        elif endpoint == 'peers':
            # Peers collection - lazy load with cache
            if torrent_hash not in self.peers_cache:
                self.peers_cache[torrent_hash] = self.api.get_peers(torrent_hash)
            items = self.peers_cache[torrent_hash]
            return [item.get(property_name) for item in items if property_name in item]

        elif endpoint == 'properties':
            # Extended properties - lazy load with cache
            if torrent_hash not in self.properties_cache:
                self.properties_cache[torrent_hash] = self.api.get_properties(torrent_hash)
            props = self.properties_cache[torrent_hash]
            return props.get(property_name)

        elif endpoint == 'webseeds':
            # Web seeds collection - lazy load with cache
            if torrent_hash not in self.webseeds_cache:
                self.webseeds_cache[torrent_hash] = self.api.get_webseeds(torrent_hash)
            items = self.webseeds_cache[torrent_hash]
            return [item.get(property_name) for item in items if property_name in item]

        elif endpoint == 'transfer':
            # Global transfer info - single call cached
            if self.transfer_info is None:
                self.transfer_info = self.api.get_transfer_info()
            return self.transfer_info.get(property_name)

        elif endpoint == 'app':
            # Global app preferences - single call cached
            if self.app_preferences is None:
                self.app_preferences = self.api.get_app_preferences()
            return self.app_preferences.get(property_name)

        else:
            raise FieldError(
                field,
                f"Unknown API endpoint: '{endpoint}'"
            )

    def _apply_operator(self, actual: Any, operator: str, expected: Any, field: str) -> bool:
        """
        Apply comparison operator

        Args:
            actual: Actual value from torrent
            operator: Comparison operator
            expected: Expected value from rule
            field: Field name (for error messages)

        Returns:
            True if comparison matches

        Raises:
            OperatorError: If operator is unknown
        """
        # Handle None/missing values
        if actual is None:
            return operator in ['!=', 'not_in', 'not_contains']

        # Handle list values (from collection fields)
        if isinstance(actual, list):
            if not actual:  # Empty list
                return operator in ['!=', 'not_in', 'not_contains']

            # Negation operators need ALL items to satisfy the check (i.e. none
            # of the items positively match) -- applying ANY here would mean
            # "at least one item doesn't match", which is true for almost any
            # multi-item collection and defeats the point of a negation check.
            # E.g. tags ['private', 'iptorrent.com'] with not_contains 'private':
            # the 'iptorrent.com' tag alone satisfies not_contains, so ANY
            # incorrectly returns True even though the torrent IS tagged
            # private. Positive operators keep ANY semantics: "does at least
            # one item match" is the natural meaning for e.g. contains/==/in.
            if operator in ('!=', 'not_in', 'not_contains'):
                return all(self._apply_operator(item, operator, expected, field) for item in actual)

            return any(self._apply_operator(item, operator, expected, field) for item in actual)

        # String operators
        if operator == '==':
            return actual == expected
        elif operator == '!=':
            return actual != expected
        elif operator == 'contains':
            if isinstance(expected, list):
                return any(str(item) in str(actual) for item in expected)
            return expected in str(actual)
        elif operator == 'not_contains':
            if isinstance(expected, list):
                return not any(str(item) in str(actual) for item in expected)
            return expected not in str(actual)
        elif operator == 'matches':
            return re.search(str(expected), str(actual)) is not None

        # List operators
        elif operator == 'in':
            if isinstance(expected, list):
                return actual in expected
            return actual == expected
        elif operator == 'not_in':
            if isinstance(expected, list):
                return actual not in expected
            return actual != expected

        # Numeric operators
        elif operator in ['>', '<', '>=', '<=']:
            try:
                actual_num = float(actual)
                expected_num = float(expected)

                if operator == '>':
                    return actual_num > expected_num
                elif operator == '<':
                    return actual_num < expected_num
                elif operator == '>=':
                    return actual_num >= expected_num
                elif operator == '<=':
                    return actual_num <= expected_num
            except (ValueError, TypeError):
                logger.warning(f"Cannot compare non-numeric values for field {field}")
                return False

        # Size operators
        elif operator == 'smaller_than':
            return is_smaller_than(int(actual), str(expected))
        elif operator == 'larger_than':
            return is_larger_than(int(actual), str(expected))

        # Time operators
        elif operator == 'older_than':
            return is_older_than(int(actual), str(expected))
        elif operator == 'newer_than':
            return is_newer_than(int(actual), str(expected))

        else:
            raise OperatorError(operator, field)


class ActionExecutor:
    """Executes actions on torrents with idempotency checks"""

    def __init__(self, api: QBittorrentAPI, dry_run: bool):
        """
        Initialize action executor

        Args:
            api: qBittorrent API client
            dry_run: If True, only log actions without executing
        """
        self.api = api
        self.dry_run = dry_run

    def execute(self, torrent: Dict, action: Dict) -> Tuple[bool, bool]:
        """
        Execute an action on a torrent

        Args:
            torrent: Torrent dictionary
            action: Action dictionary with type and params

        Returns:
            Tuple of (success, skipped_due_to_idempotency)
        """
        action_type = action['type']
        params = action.get('params', {})

        try:
            # Check idempotency before executing
            if self._should_skip_idempotent(torrent, action_type, params):
                logger.info(f"  {torrent['name']} - {action_type} already in desired state (skipped)")
                return True, True
            if self.dry_run:
                self._log_dry_run(torrent, action_type, params)
                return True, True  # Dry run actions count as "skipped" (not actually executed)
            # Execute action
            return self._execute_action(torrent, action_type, params), False

        except Exception as e:
            logger.error(f"Action {action_type} failed for {torrent['name']}: {e}")
            return False, False

    def _should_skip_idempotent(self, torrent: Dict, action_type: str, params: Dict) -> bool:
        """Check if action is idempotent and already applied"""
        if action_type == 'stop':
            return 'paused' in torrent.get('state', '').lower()

        elif action_type == 'start':
            return 'paused' not in torrent.get('state', '').lower()

        elif action_type == 'set_category':
            return torrent.get('category') == params.get('category')

        elif action_type == 'add_tag':
            current_tags = set(parse_tags(torrent))
            new_tags = set(params.get('tags', []))
            return new_tags.issubset(current_tags)

        elif action_type == 'remove_tag':
            current_tags = set(parse_tags(torrent))
            remove_tags = set(params.get('tags', []))
            return not remove_tags.intersection(current_tags)

        # Non-idempotent actions
        return False

    def _log_dry_run(self, torrent: Dict, action_type: str, params: Dict):
        """Log what would happen in dry run"""
        if action_type == 'delete_torrent':
            keep_files = params.get('keep_files', False)
            logger.info(f"  Would delete {torrent['name']} (keep_files={keep_files})")
        else:
            logger.info(f"  Would {action_type} {torrent['name']} (params={params})")

    def _execute_action(self, torrent: Dict, action_type: str, params: Dict) -> bool:
        """Execute the actual action"""
        torrent_hash = torrent['hash']

        if action_type == 'stop':
            success = self.api.stop_torrents([torrent_hash])
            if success:
                logger.info(f"  Stopped {torrent['name']}")
            return success

        elif action_type == 'start':
            success = self.api.start_torrents([torrent_hash])
            if success:
                logger.info(f"  Started {torrent['name']}")
            return success

        elif action_type == 'force_start':
            success = self.api.force_start_torrents([torrent_hash])
            if success:
                logger.info(f"  Force started {torrent['name']}")
            return success

        elif action_type == 'recheck':
            success = self.api.recheck_torrents([torrent_hash])
            if success:
                logger.info(f"  Rechecking {torrent['name']}")
            return success

        elif action_type == 'reannounce':
            success = self.api.reannounce_torrents([torrent_hash])
            if success:
                logger.info(f"  Reannouncing {torrent['name']}")
            return success

        elif action_type == 'delete_torrent':
            keep_files = params.get('keep_files', False)
            success = self.api.delete_torrents([torrent_hash], delete_files=not keep_files)
            if success:
                logger.info(f"  Deleted {torrent['name']} (keep_files={keep_files})")
            return success

        elif action_type == 'set_category':
            category = params.get('category', '')
            success = self.api.set_category([torrent_hash], category)
            if success:
                logger.info(f"  Set category for {torrent['name']} to {category}")
            return success

        elif action_type == 'add_tag':
            tags = params.get('tags', [])
            success = self.api.add_tags([torrent_hash], tags)
            if success:
                logger.info(f"  Added tags {tags} to {torrent['name']}")
            return success

        elif action_type == 'remove_tag':
            tags = params.get('tags', [])
            success = self.api.remove_tags([torrent_hash], tags)
            if success:
                logger.info(f"  Removed tags {tags} from {torrent['name']}")
            return success

        elif action_type == 'set_tags':
            # Remove all existing tags first, then set new ones
            current_tags = parse_tags(torrent)
            new_tags = params.get('tags', [])
            if current_tags:
                self.api.remove_tags([torrent_hash], current_tags)
            success = self.api.add_tags([torrent_hash], new_tags)
            if success:
                logger.info(f"  Set tags for {torrent['name']} to {new_tags}")
            return success

        elif action_type == 'set_upload_limit':
            limit = params.get('limit', -1)
            success = self.api.set_upload_limit([torrent_hash], limit)
            if success:
                logger.info(f"  Set upload limit for {torrent['name']} to {limit}")
            return success

        elif action_type == 'set_download_limit':
            limit = params.get('limit', -1)
            success = self.api.set_download_limit([torrent_hash], limit)
            if success:
                logger.info(f"  Set download limit for {torrent['name']} to {limit}")
            return success

        else:
            logger.error(f"  Unknown action type: {action_type}")
            return False


class RulesEngine:
    """Main qBittorrent automation engine"""

    def __init__(self, api: QBittorrentAPI, config: 'Config', dry_run: bool = False):
        """
        Initialize engine

        Args:
            api: qBittorrent API client
            config: Configuration object
            dry_run: If True, only log actions without executing
        """
        self.api = api
        self.config = config
        self.dry_run = dry_run
        self.evaluator = ConditionEvaluator(api)
        self.executor = ActionExecutor(api, dry_run)
        self.stats = RuleStats()

    def run(self, context: Optional[str] = None, torrent_hash: Optional[str] = None):
        """
        Execute rules engine

        Args:
            context: Context type (torrent-imported, download-finished, weekly-cleanup, adhoc-run)
            torrent_hash: Optional torrent hash to process only one torrent
        """
        logger.info("=" * 60)
        logger.info("Starting qBittorrent automation engine")
        logger.info(f"Context: {context or 'none'}")
        logger.info(f"Dry run mode: {self.dry_run}")
        logger.info("=" * 60)

        try:
            # Fetch torrents
            if torrent_hash:
                # Single torrent mode (webhook)
                torrents = [t for t in self.api.get_torrents() if t['hash'] == torrent_hash]
                if not torrents:
                    logger.warning(f"Torrent not found: {torrent_hash}")
                    return
            else:
                # All torrents mode (weekly-cleanup/adhoc-run)
                torrents = self.api.get_torrents()

            self.stats.total_torrents = len(torrents)
            logger.info(f"Fetched {len(torrents)} torrent(s)")

            # Get rules (execute in YAML file order)
            rules = self.config.get_rules()
            logger.info(f"Loaded {len(rules)} rules (execute in file order)")

            # Process each rule
            processed_torrents = set()

            for rule in rules:
                if not rule.get('enabled', True):
                    logger.debug(f"Skipping disabled rule: {rule.get('name', 'unnamed')}")
                    continue

                logger.info(f"Processing rule: {rule.get('name', 'unnamed')}")

                matched_count = 0
                for torrent in torrents:
                    # Skip if already processed by stop_on_match rule
                    if torrent['hash'] in processed_torrents:
                        continue

                    # Skip if torrent was deleted by a previous rule
                    if torrent.get('_deleted'):
                        continue

                    # Evaluate conditions
                    # Pass runtime context and rule's context requirement separately
                    if self.evaluator.evaluate(torrent, rule.get('conditions', {}), context, rule.get('context')):
                        matched_count += 1
                        self.stats.rules_matched += 1

                        logger.debug(f"Rule '{rule.get('name', 'unnamed')}' matched: {torrent.get('name', 'unknown')}")

                        # Execute actions
                        for action in rule.get('actions', []):
                            success, skipped = self.executor.execute(torrent, action)
                            if success:
                                if skipped:
                                    self.stats.actions_skipped += 1
                                else:
                                    self.stats.actions_executed += 1

                                    # Re-fetch torrent to update cache for subsequent rules
                                    # This allows later rules to see changes (tags, category, etc.)
                                    try:
                                        updated = self.api.get_torrent(torrent['hash'])
                                        if updated:
                                            torrent.update(updated)
                                            logger.debug(f"Updated cache for {torrent.get('name', 'unknown')} after action")
                                        else:
                                            # Torrent was deleted
                                            logger.debug(f"Torrent {torrent['hash']} no longer exists (likely deleted)")
                                            torrent['_deleted'] = True
                                    except Exception as e:
                                        logger.warning(f"Failed to update cache for {torrent['hash']}: {e}")
                                        # Continue execution - don't fail the rule
                            else:
                                self.stats.errors += 1

                        # Mark as processed if stop_on_match
                        if rule.get('stop_on_match', False):
                            processed_torrents.add(torrent['hash'])

                if matched_count > 0:
                    logger.info(f"  Rule '{rule.get('name', 'unnamed')}' matched {matched_count} torrent(s)")

            self.stats.processed = len(processed_torrents)

        except Exception as e:
            logger.error(f"Fatal error during execution: {e}", exc_info=True)
            raise

        finally:
            self._print_summary()

    def _print_summary(self):
        """Print execution summary"""
        logger.info("=" * 60)
        logger.info("Execution complete - Summary:")
        logger.info(f"  Total torrents: {self.stats.total_torrents}")
        logger.info(f"  Processed: {self.stats.processed}")
        logger.info(f"  Rules matched: {self.stats.rules_matched}")
        logger.info(f"  Actions executed: {self.stats.actions_executed}")
        logger.info(f"  Actions skipped (idempotent): {self.stats.actions_skipped}")
        if self.stats.errors > 0:
            logger.warning(f"  Errors: {self.stats.errors}")
        logger.info("=" * 60)
