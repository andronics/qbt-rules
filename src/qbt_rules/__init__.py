"""A rules engine for qBittorrent automation, with a job queue, scheduler and web dashboard"""

from importlib.metadata import PackageNotFoundError, metadata, version

try:
    __version__ = version("qbt-rules")
    # pyproject.toml's description, read rather than repeated as a literal ruff would have to wrap.
    __description__ = metadata("qbt-rules")["Summary"]
except PackageNotFoundError:  # pragma: no cover - a source tree that was never installed
    __version__ = "0+unknown"
    __description__ = ""

__all__ = ["__description__", "__version__"]
