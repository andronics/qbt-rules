"""
qBittorrent Web API client - qbittorrent-api wrapper

Wraps qbittorrent-api package for multi-version support (v4.1+ through v5.1.4+)
Maintains backward compatibility with existing qbt-rules interface
"""

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import qbittorrentapi
import requests

from qbt_rules.errors import AuthenticationError, ConnectionError, RequestTimeoutError
from qbt_rules.log_setup import get_logger

if TYPE_CHECKING:
    from qbittorrentapi.torrents import TorrentStatusesT

logger = get_logger(__name__)

# (connect, read) seconds for every request to qBittorrent, instead of qbittorrent-api's
# own 15.1 s for both: connecting fails sooner, and the read timeout is generous because
# torrents/info on a large library can take a while on a busy server. qbittorrent-api
# retries (urllib3's retry, its own second attempt, and the HTTP/HTTPS detection before
# each), so a qBittorrent that accepts connections but never answers fails a call after
# several reads: measured, about 4 connect and 6 read timeouts, some 6-7 minutes.
REQUEST_TIMEOUT = (10.0, 60.0)


def _is_timeout(e: qbittorrentapi.APIConnectionError) -> bool:
    """qbittorrent-api raises APIConnectionError inside its ``except``, so the cause is
    the exception's context"""
    return isinstance(e.__context__, requests.exceptions.Timeout)


def _clear_timeouts[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """A timed-out request raises RequestTimeoutError, not qbittorrent-api's
    "Failed to connect to qBittorrent. Timeout Error: ..." """

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except qbittorrentapi.APIConnectionError as e:
            if not _is_timeout(e):
                raise
            api = cast("QBittorrentAPI", args[0])
            raise RequestTimeoutError(api.host, *REQUEST_TIMEOUT) from e

    return wrapper


class QBittorrentAPI:
    """
    qBittorrent Web API client wrapper

    Uses qbittorrent-api package for:
    - Multi-version support (v4.1+ through v5.1.4+)
    - Automatic version detection
    - Auto-managed authentication
    - Structured response types
    """

    def __init__(self, host: str, username: str, password: str, connect_now: bool = True):
        """
        Initialize API client and optionally authenticate

        Args:
            host: qBittorrent host URL (e.g., 'http://localhost:8080')
            username: qBittorrent username
            password: qBittorrent password
            connect_now: If True, authenticate immediately; if False, defer until first API call

        Raises:
            AuthenticationError: If login fails (only when connect_now=True)
            ConnectionError: If cannot reach server (only when connect_now=True)
            RequestTimeoutError: If the server didn't answer in time (only when connect_now=True)
        """
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self._connected = False

        # Initialize qbittorrent-api client (does not connect yet)
        self.client = qbittorrentapi.Client(
            host=self.host,
            username=self.username,
            password=self.password,
            REQUESTS_ARGS={"timeout": REQUEST_TIMEOUT},
        )

        if connect_now:
            self._ensure_connected()

    def _ensure_connected(self) -> None:
        """
        Ensure we're connected to qBittorrent (lazy initialization support)

        Raises:
            AuthenticationError: If login fails
            ConnectionError: If cannot reach server
            RequestTimeoutError: If the server didn't answer in time (REQUEST_TIMEOUT)
        """
        if self._connected:
            return

        try:
            # Verify connection
            self.client.auth_log_in()
            self._connected = True

            logger.info(f"Successfully authenticated with qBittorrent at {self.host}")
            logger.debug(f"qBittorrent version: {self.client.app_version()}")
            logger.debug(f"Web API version: {self.client.app_web_api_version()}")

        except qbittorrentapi.LoginFailed as e:
            raise AuthenticationError(self.host, str(e)) from e
        except qbittorrentapi.APIConnectionError as e:
            if _is_timeout(e):
                raise RequestTimeoutError(self.host, *REQUEST_TIMEOUT) from e
            raise ConnectionError(self.host, str(e)) from e
        except Exception as e:
            raise ConnectionError(self.host, str(e)) from e

    # Torrent Information Methods

    def get_torrents(
        self,
        filter_type: str | None = None,
        category: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get list of torrents

        Args:
            filter_type: Filter by state (e.g., 'downloading', 'seeding', 'completed')
            category: Filter by category
            tag: Filter by tag

        Returns:
            List of torrent dictionaries
        """
        self._ensure_connected()

        # Use qbittorrent-api Client
        # qbittorrent-api checks the filter value itself; callers pass config strings
        status_filter = cast("TorrentStatusesT | None", filter_type)
        torrents = self.client.torrents_info(
            status_filter=status_filter, category=category, tag=tag
        )

        # Convert to list of dicts (qbittorrent-api returns TorrentInfoList)
        return [dict(t) for t in torrents]

    def get_torrent(self, torrent_hash: str) -> dict[str, Any] | None:
        """
        Get single torrent by hash

        Args:
            torrent_hash: Torrent hash

        Returns:
            Torrent dictionary or None if not found
        """
        self._ensure_connected()

        # Use qbittorrent-api Client with specific hash
        torrents = self.client.torrents_info(torrent_hashes=torrent_hash)

        # Return first torrent or None if not found
        return dict(torrents[0]) if torrents else None

    def get_properties(self, torrent_hash: str) -> dict[str, Any]:
        """
        Get detailed torrent properties

        Args:
            torrent_hash: Torrent hash

        Returns:
            Properties dictionary
        """
        props = self.client.torrents_properties(torrent_hash=torrent_hash)
        return dict(props)

    def get_trackers(self, torrent_hash: str) -> list[dict[str, Any]]:
        """
        Get tracker information for a torrent

        Args:
            torrent_hash: Torrent hash

        Returns:
            List of tracker dictionaries
        """
        trackers = self.client.torrents_trackers(torrent_hash=torrent_hash)
        return [dict(t) for t in trackers]

    def get_files(self, torrent_hash: str) -> list[dict[str, Any]]:
        """
        Get file list for a torrent

        Args:
            torrent_hash: Torrent hash

        Returns:
            List of file dictionaries
        """
        files = self.client.torrents_files(torrent_hash=torrent_hash)
        return [dict(f) for f in files]

    def get_webseeds(self, torrent_hash: str) -> list[dict[str, Any]]:
        """
        Get web seeds for a torrent

        Args:
            torrent_hash: Torrent hash

        Returns:
            List of web seed dictionaries
        """
        webseeds = self.client.torrents_webseeds(torrent_hash=torrent_hash)
        return [dict(w) for w in webseeds]

    def get_peers(self, torrent_hash: str) -> list[dict[str, Any]]:
        """
        Get peer information for a torrent

        Args:
            torrent_hash: Torrent hash

        Returns:
            List of peer dictionaries
        """
        peers_data = self.client.sync_torrent_peers(torrent_hash=torrent_hash)

        # Convert peers dict to list of dicts for consistency
        peers_dict = cast("dict[str, dict[str, Any]]", peers_data.get("peers", {}))
        return [{"id": peer_id, **dict(peer_data)} for peer_id, peer_data in peers_dict.items()]

    # Global Information Methods

    def get_transfer_info(self) -> dict[str, Any]:
        """
        Get global transfer information

        Returns:
            Transfer info dictionary with speeds, data transferred, etc.
        """
        info = self.client.transfer_info()
        return dict(info)

    def get_app_preferences(self) -> dict[str, Any]:
        """
        Get application preferences

        Returns:
            Preferences dictionary
        """
        prefs = self.client.app_preferences()
        return dict(prefs)

    # Torrent Control Methods

    def stop_torrents(self, hashes: list[str]) -> bool:
        """Stop torrents (pause in qBittorrent v5.0+)"""
        self.client.torrents_pause(torrent_hashes=hashes)
        return True

    def start_torrents(self, hashes: list[str]) -> bool:
        """Start torrents (resume in qBittorrent v5.0+)"""
        self.client.torrents_resume(torrent_hashes=hashes)
        return True

    def force_start_torrents(self, hashes: list[str], enable: bool = True) -> bool:
        """Force start torrents, or release them back to normal queue management if enable=False"""
        self.client.torrents_set_force_start(enable=enable, torrent_hashes=hashes)
        return True

    def recheck_torrents(self, hashes: list[str]) -> bool:
        """Recheck torrents"""
        self.client.torrents_recheck(torrent_hashes=hashes)
        return True

    def reannounce_torrents(self, hashes: list[str]) -> bool:
        """Reannounce torrents to trackers"""
        self.client.torrents_reannounce(torrent_hashes=hashes)
        return True

    def delete_torrents(self, hashes: list[str], delete_files: bool) -> bool:
        """Delete torrents"""
        self.client.torrents_delete(delete_files=delete_files, torrent_hashes=hashes)
        return True

    # Category and Tag Methods

    def set_category(self, hashes: list[str], category: str) -> bool:
        """Set category"""
        self.client.torrents_set_category(category=category, torrent_hashes=hashes)
        return True

    def add_tags(self, hashes: list[str], tags: list[str]) -> bool:
        """Add tags"""
        self.client.torrents_add_tags(tags=tags, torrent_hashes=hashes)
        return True

    def remove_tags(self, hashes: list[str], tags: list[str]) -> bool:
        """Remove tags"""
        self.client.torrents_remove_tags(tags=tags, torrent_hashes=hashes)
        return True

    # Limit Methods

    def set_upload_limit(self, hashes: list[str], limit: int) -> bool:
        """Set upload limit (bytes/s, -1 for unlimited)"""
        self.client.torrents_set_upload_limit(limit=limit, torrent_hashes=hashes)
        return True

    def set_download_limit(self, hashes: list[str], limit: int) -> bool:
        """Set download limit (bytes/s, -1 for unlimited)"""
        self.client.torrents_set_download_limit(limit=limit, torrent_hashes=hashes)
        return True

    def set_share_limits(
        self, hashes: list[str], ratio_limit: float = -2, seeding_time_limit: int = -2
    ) -> bool:
        """
        Set share limits

        Args:
            hashes: List of torrent hashes
            ratio_limit: Max ratio (-2=global, -1=unlimited, >=0=limit)
            seeding_time_limit: Max seeding time in minutes (-2=global, -1=unlimited, >=0=limit)
        """
        self.client.torrents_set_share_limits(
            ratio_limit=ratio_limit, seeding_time_limit=seeding_time_limit, torrent_hashes=hashes
        )
        return True

    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int) -> bool:
        """
        Set the download priority of individual files in one torrent

        Args:
            torrent_hash: Torrent hash
            file_ids: File indices, as /torrents/files reports them
            priority: 0 (do not download), 1 (normal), 6 (high), 7 (maximum)
        """
        self.client.torrents_file_priority(
            torrent_hash=torrent_hash, file_ids=file_ids, priority=priority
        )
        return True

    # Priority Methods

    def increase_priority(self, hashes: list[str]) -> bool:
        """Increase torrent priority"""
        self.client.torrents_increase_priority(torrent_hashes=hashes)
        return True

    def decrease_priority(self, hashes: list[str]) -> bool:
        """Decrease torrent priority"""
        self.client.torrents_decrease_priority(torrent_hashes=hashes)
        return True

    def set_top_priority(self, hashes: list[str]) -> bool:
        """Set maximum priority"""
        self.client.torrents_top_priority(torrent_hashes=hashes)
        return True

    def set_bottom_priority(self, hashes: list[str]) -> bool:
        """Set minimum priority"""
        self.client.torrents_bottom_priority(torrent_hashes=hashes)
        return True


# Every public method talks to qBittorrent (after _ensure_connected, which reports its own
# timeouts), so each one reports a timeout the same way
for _name, _method in list(vars(QBittorrentAPI).items()):
    if not _name.startswith("_") and callable(_method):
        setattr(QBittorrentAPI, _name, _clear_timeouts(_method))
