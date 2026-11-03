"""
Queue backend implementations

Available backends:
- SQLite: File-based queue (default, zero dependencies)
- Redis: In-memory queue (optional, high-performance)
"""

from qbt_rules.queue_backends.sqlite_queue import SQLiteQueue
from qbt_rules.queue_manager import QueueManager

__all__ = ["SQLiteQueue", "create_queue"]

# Redis is optional - only import if available
try:
    from qbt_rules.queue_backends.redis_queue import RedisQueue

    __all__.append("RedisQueue")
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


def create_queue(backend: str = "sqlite", **kwargs) -> QueueManager:
    """
    Factory function to create queue backend instances

    Args:
        backend: Backend type ('sqlite' or 'redis')
        **kwargs: Backend-specific configuration

    Returns:
        QueueManager instance

    Raises:
        ValueError: If backend is unknown or unavailable
    """
    if backend == "sqlite":
        sqlite_path = kwargs.get("sqlite_path", "/config/qbt-rules.db")
        return SQLiteQueue(db_path=sqlite_path)

    elif backend == "redis":
        if not REDIS_AVAILABLE:
            raise ValueError("Redis backend not available. Install with: pip install redis")
        redis_url = kwargs.get("redis_url", "redis://localhost:6379/0")
        return RedisQueue(redis_url=redis_url)

    else:
        raise ValueError(f"Unknown queue backend: {backend}. Available: sqlite, redis")
