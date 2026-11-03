"""
Shared utility functions for qBittorrent automation
"""

import logging
import re
import time
from typing import Any


def parse_bool(value: str | None) -> bool:
    """A boolean query parameter: true, 1, yes or on (any case) is True; absent is False"""
    return value is not None and value.strip().lower() in ("true", "1", "yes", "on")


def parse_tags(torrent: dict[str, Any]) -> list[str]:
    """
    Parse tags from torrent dictionary into list

    Args:
        torrent: Torrent dictionary from qBittorrent API

    Returns:
        List of tag strings
    """
    tags_str = torrent.get("tags", "")
    if not tags_str:
        return []
    return [tag.strip() for tag in tags_str.split(",") if tag.strip()]


def parse_duration(duration: str) -> int:
    """
    Parse human-readable duration to seconds

    Args:
        duration: Duration string like "30 days", "12 hours", "5 minutes"

    Returns:
        Duration in seconds

    Examples:
        >>> parse_duration("30 days")
        2592000
        >>> parse_duration("12 hours")
        43200
        >>> parse_duration("5 minutes")
        300
    """
    duration = duration.lower().strip()

    # Extract number and unit
    match = re.match(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?", duration)
    if not match:
        logging.warning(f"Invalid duration format: {duration}, defaulting to 0")
        return 0

    amount = int(match.group(1))
    unit = match.group(2)

    multipliers = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2592000,  # 30 days
        "year": 31536000,  # 365 days
    }

    return amount * multipliers.get(unit, 0)


def parse_size(size: str) -> int:
    """
    Parse human-readable size string (e.g., '5 Gb', '4KB', '1000b', '1.5 MiB')
    into bytes. Supports fractional values and differentiates bits vs bytes.

    Bits (b) → converted to bytes (divide by 8)
    Bytes (B) → used directly

    Examples:
        >>> parse_size("5 Gb")       # gigabits
        625000000
        >>> parse_size("4KB")        # kilobytes
        4000
        >>> parse_size("2 MiB")      # mebibytes
        2097152
        >>> parse_size("1000b")      # bits
        125
        >>> parse_size("1.5 MB")
        1500000
    """
    if not size:
        return 0

    s = size.strip()

    # number + unit (unit may include suffixes like KiB, MB, Gb, etc.)
    match = re.match(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)?", s)
    if not match:
        logging.warning(f"Invalid size format: {size}, defaulting to 0")
        return 0

    amount = float(match.group(1))
    unit = match.group(2) or "B"  # default to bytes if no unit

    # Normalize unit exactly as written (case matters for bit/byte)
    unit = unit.strip()

    # Define prefix multipliers
    si_prefixes = {
        "": 1,
        "k": 10**3,
        "M": 10**6,
        "G": 10**9,
        "T": 10**12,
        "P": 10**15,
    }

    iec_prefixes = {
        "Ki": 2**10,
        "Mi": 2**20,
        "Gi": 2**30,
        "Ti": 2**40,
        "Pi": 2**50,
    }

    # Extract prefix + type (bit or byte)
    # Examples:
    #   "MB"  -> prefix="M",  type="B"
    #   "Gb"  -> prefix="G",  type="b"
    #   "MiB" -> prefix="Mi", type="B"
    prefix = None
    unit_type = None  # 'b' or 'B'

    # IEC (KiB, MiB…)
    for pre in iec_prefixes:
        if unit.startswith(pre):
            prefix = pre
            unit_type = unit[len(pre) :]  # should be 'B' or 'b'
            break

    # SI (kB, MB…) — only if IEC not matched
    if prefix is None:
        # prefix = all except last char
        prefix = unit[:-1]
        unit_type = unit[-1]

        # Fix lowercase SI prefixes like "kb", "mb" → canonical "k", "M"
        prefix = {
            "k": "k",
            "K": "k",
            "m": "M",
            "M": "M",
            "g": "G",
            "G": "G",
            "t": "T",
            "T": "T",
            "p": "P",
            "P": "P",
            "": "",
        }.get(prefix, prefix)  # leave unexpected ones unchanged

    # Determine multiplier
    if prefix in iec_prefixes:
        multiplier = iec_prefixes[prefix]
    elif prefix in si_prefixes:
        multiplier = si_prefixes[prefix]
    else:
        logging.warning(f"Unknown size prefix '{prefix}', defaulting to 1")
        multiplier = 1

    # Bits vs Bytes
    if unit_type == "B":
        # bytes — OK
        value_bytes = amount * multiplier
    elif unit_type == "b":
        # bits — convert to bytes
        value_bytes = (amount * multiplier) / 8
    else:
        logging.warning(f"Invalid unit type '{unit_type}', defaulting to bytes")
        value_bytes = amount * multiplier

    return int(value_bytes)


def is_larger_than(size_bytes: int, human_size: str) -> bool:
    """
    Check if size_bytes is larger than a human-readable size.

    Args:
        size_bytes: Size in bytes (integer)
        human_size: Human-readable size string like "5 MB", "3 Gb", "2 MiB"

    Returns:
        True if size_bytes is larger than the parsed human_size.
    """
    if size_bytes < 0:
        return False

    target_bytes = parse_size(human_size)
    return size_bytes > target_bytes


def is_smaller_than(size_bytes: int, human_size: str) -> bool:
    """
    Check if size_bytes is smaller than a human-readable size.

    Args:
        size_bytes: Size in bytes (integer)
        human_size: Human-readable size string like "5 MB", "3 Gb", "2 MiB"

    Returns:
        True if size_bytes is smaller than the parsed human_size.
    """
    if size_bytes < 0:
        return False

    target_bytes = parse_size(human_size)
    return size_bytes < target_bytes


def is_older_than(timestamp: int, duration: str) -> bool:
    """
    Check if timestamp is older than duration

    Args:
        timestamp: Unix timestamp in seconds
        duration: Duration string like "30 days"

    Returns:
        True if timestamp is older than duration
    """
    if timestamp <= 0:
        return False

    age_seconds = time.time() - timestamp
    duration_seconds = parse_duration(duration)
    return age_seconds > duration_seconds


def is_newer_than(timestamp: int, duration: str) -> bool:
    """
    Check if timestamp is newer than duration

    Args:
        timestamp: Unix timestamp in seconds
        duration: Duration string like "30 days"

    Returns:
        True if timestamp is newer than duration
    """
    if timestamp <= 0:
        return False

    age_seconds = time.time() - timestamp
    duration_seconds = parse_duration(duration)
    return age_seconds < duration_seconds


def format_bytes(bytes_count: float) -> str:
    """
    Format bytes into human-readable string

    Args:
        bytes_count: Number of bytes

    Returns:
        Formatted string like "1.5 GB"
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.2f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.2f} PB"


def format_speed(bytes_per_second: int) -> str:
    """
    Format speed into human-readable string

    Args:
        bytes_per_second: Speed in bytes per second

    Returns:
        Formatted string like "1.5 MB/s"
    """
    return f"{format_bytes(bytes_per_second)}/s"


def format_duration(seconds: int) -> str:
    """
    Format seconds into human-readable duration

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string like "2d 5h 30m"
    """
    if seconds < 60:
        return f"{seconds}s"

    parts = []

    days = seconds // 86400
    if days > 0:
        parts.append(f"{days}d")
        seconds %= 86400

    hours = seconds // 3600
    if hours > 0:
        parts.append(f"{hours}h")
        seconds %= 3600

    minutes = seconds // 60
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts)


def validate_field_name(field: str) -> bool:
    """
    Validate that field name uses correct dot notation

    Args:
        field: Field name to validate

    Returns:
        True if valid

    Raises:
        ValueError if invalid format
    """
    if "." not in field:
        return False

    prefix = field.split(".", 1)[0]
    valid_prefixes = ["info", "trackers", "files", "peers", "properties", "transfer", "webseeds"]

    return prefix in valid_prefixes
