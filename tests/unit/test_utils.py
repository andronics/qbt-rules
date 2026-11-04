"""Comprehensive tests for utils.py - All utility functions."""

import time
from unittest.mock import patch

from qbt_rules.utils import (
    format_bytes,
    format_duration,
    format_speed,
    is_larger_than,
    is_newer_than,
    is_older_than,
    is_smaller_than,
    parse_duration,
    parse_size,
    parse_tags,
    validate_field_name,
)

# ============================================================================
# parse_tags()
# ============================================================================


class TestParseTags:
    """Test parse_tags() function."""

    def test_empty_tags(self):
        """Empty tags string returns empty list."""
        assert parse_tags({"tags": ""}) == []

    def test_missing_tags_key(self):
        """Missing tags key returns empty list."""
        assert parse_tags({}) == []

    def test_single_tag(self):
        """Single tag is parsed correctly."""
        assert parse_tags({"tags": "movies"}) == ["movies"]

    def test_multiple_tags(self):
        """Multiple comma-separated tags are parsed."""
        assert parse_tags({"tags": "movies,hd,new"}) == ["movies", "hd", "new"]

    def test_tags_with_spaces(self):
        """Tags with extra spaces are stripped."""
        assert parse_tags({"tags": "movies , hd , new"}) == ["movies", "hd", "new"]

    def test_tags_with_empty_values(self):
        """Empty values in tag list are filtered out."""
        assert parse_tags({"tags": "movies,,hd,,new"}) == ["movies", "hd", "new"]

    def test_tags_only_commas(self):
        """String with only commas returns empty list."""
        assert parse_tags({"tags": ",,,"}) == []

    def test_tags_with_whitespace_only(self):
        """Tags with only whitespace are filtered."""
        assert parse_tags({"tags": "  ,  ,  "}) == []


# ============================================================================
# parse_duration()
# ============================================================================


class TestParseDuration:
    """Test parse_duration() function."""

    def test_seconds(self):
        """Parse seconds correctly."""
        assert parse_duration("30 seconds") == 30

    def test_minutes(self):
        """Parse minutes correctly."""
        assert parse_duration("5 minutes") == 300

    def test_hours(self):
        """Parse hours correctly."""
        assert parse_duration("12 hours") == 43200

    def test_days(self):
        """Parse days correctly."""
        assert parse_duration("30 days") == 2592000

    def test_weeks(self):
        """Parse weeks correctly."""
        assert parse_duration("2 weeks") == 1209600

    def test_months(self):
        """Parse months correctly (30 days)."""
        assert parse_duration("3 months") == 7776000

    def test_years(self):
        """Parse years correctly (365 days)."""
        assert parse_duration("1 year") == 31536000

    def test_singular_unit(self):
        """Singular units work (without 's')."""
        assert parse_duration("1 day") == 86400

    def test_plural_unit(self):
        """Plural units work (with 's')."""
        assert parse_duration("2 days") == 172800

    def test_no_space(self):
        """Duration without space works."""
        assert parse_duration("5minutes") == 300

    def test_case_insensitive(self):
        """Duration is case insensitive."""
        assert parse_duration("30 DAYS") == 2592000

    def test_extra_whitespace(self):
        """Extra whitespace is handled."""
        assert parse_duration("  30   days  ") == 2592000

    def test_invalid_format(self):
        """Invalid format returns 0."""
        assert parse_duration("invalid") == 0

    def test_invalid_unit(self):
        """Invalid unit returns 0."""
        assert parse_duration("30 lightyears") == 0

    def test_missing_number(self):
        """Missing number returns 0."""
        assert parse_duration("days") == 0


# ============================================================================
# parse_size()
# ============================================================================


class TestParseSize:
    """Test parse_size() function."""

    # Bytes (SI)
    def test_bytes_no_unit(self):
        """Plain number defaults to bytes."""
        assert parse_size("1000") == 1000

    def test_bytes_with_b_uppercase(self):
        """Bytes with B unit."""
        assert parse_size("1000B") == 1000

    def test_kilobytes(self):
        """Kilobytes (SI)."""
        assert parse_size("4KB") == 4000

    def test_megabytes(self):
        """Megabytes (SI)."""
        assert parse_size("5MB") == 5000000

    def test_gigabytes(self):
        """Gigabytes (SI)."""
        assert parse_size("2GB") == 2000000000

    def test_terabytes(self):
        """Terabytes (SI)."""
        assert parse_size("1TB") == 1000000000000

    # Bytes (IEC)
    def test_kibibytes(self):
        """Kibibytes (IEC)."""
        assert parse_size("4KiB") == 4096

    def test_mebibytes(self):
        """Mebibytes (IEC)."""
        assert parse_size("2MiB") == 2097152

    def test_gibibytes(self):
        """Gibibytes (IEC)."""
        assert parse_size("1GiB") == 1073741824

    def test_tebibytes(self):
        """Tebibytes (IEC)."""
        assert parse_size("1TiB") == 1099511627776

    # Bits (SI) - converted to bytes
    def test_bits(self):
        """Bits are converted to bytes."""
        assert parse_size("1000b") == 125  # 1000 bits / 8

    def test_kilobits(self):
        """Kilobits (SI) converted to bytes."""
        assert parse_size("8Kb") == 1000  # 8000 bits / 8

    def test_megabits(self):
        """Megabits (SI) converted to bytes."""
        assert parse_size("8Mb") == 1000000  # 8M bits / 8

    def test_gigabits(self):
        """Gigabits (SI) converted to bytes."""
        assert parse_size("5Gb") == 625000000  # 5G bits / 8

    # Fractional values
    def test_fractional_megabytes(self):
        """Fractional values work."""
        assert parse_size("1.5MB") == 1500000

    def test_fractional_gibibytes(self):
        """Fractional IEC values work."""
        assert parse_size("0.5GiB") == 536870912

    # Case variations
    def test_lowercase_kb(self):
        """Lowercase 'kb' is kilobits (bits not bytes)."""
        assert parse_size("4kb") == 500  # 4000 bits / 8 = 500 bytes

    def test_lowercase_mb(self):
        """Lowercase 'mb' is megabits (bits not bytes)."""
        assert parse_size("5mb") == 625000  # 5M bits / 8 = 625000 bytes

    # Edge cases
    def test_empty_string(self):
        """Empty string returns 0."""
        assert parse_size("") == 0

    def test_whitespace_handling(self):
        """Whitespace is handled correctly."""
        assert parse_size("  5 MB  ") == 5000000

    def test_invalid_format(self):
        """Invalid format returns 0."""
        assert parse_size("invalid") == 0

    def test_unknown_prefix(self):
        """Unknown prefix defaults to multiplier 1."""
        assert parse_size("5XB") == 5

    def test_invalid_unit_type(self):
        """Invalid unit type (not B or b) defaults to bytes with warning."""
        # Unit type 'X' is invalid - should default to bytes
        assert parse_size("5X") == 5

    def test_zero_value(self):
        """Zero value works."""
        assert parse_size("0MB") == 0

    def test_large_value(self):
        """Large values work."""
        assert parse_size("100TB") == 100000000000000

    def test_no_unit_with_space(self):
        """Number with space but no unit defaults to bytes."""
        assert parse_size("1000 ") == 1000


# ============================================================================
# is_larger_than()
# ============================================================================


class TestIsLargerThan:
    """Test is_larger_than() function."""

    def test_larger(self):
        """Size larger than threshold returns True."""
        assert is_larger_than(2000000000, "1GB") is True

    def test_smaller(self):
        """Size smaller than threshold returns False."""
        assert is_larger_than(500000000, "1GB") is False

    def test_equal(self):
        """Size equal to threshold returns False."""
        assert is_larger_than(1000000000, "1GB") is False

    def test_negative_size(self):
        """Negative size returns False."""
        assert is_larger_than(-100, "1MB") is False

    def test_zero_size(self):
        """Zero size returns False."""
        assert is_larger_than(0, "1MB") is False

    def test_zero_threshold(self):
        """Zero threshold comparison works."""
        assert is_larger_than(100, "0MB") is True

    def test_iec_units(self):
        """IEC units work correctly."""
        assert is_larger_than(2097152, "1MiB") is True  # 2 MiB > 1 MiB

    def test_fractional_threshold(self):
        """Fractional threshold works."""
        assert is_larger_than(2000000, "1.5MB") is True


# ============================================================================
# is_smaller_than()
# ============================================================================


class TestIsSmallerThan:
    """Test is_smaller_than() function."""

    def test_smaller(self):
        """Size smaller than threshold returns True."""
        assert is_smaller_than(500000000, "1GB") is True

    def test_larger(self):
        """Size larger than threshold returns False."""
        assert is_smaller_than(2000000000, "1GB") is False

    def test_equal(self):
        """Size equal to threshold returns False."""
        assert is_smaller_than(1000000000, "1GB") is False

    def test_negative_size(self):
        """Negative size returns False."""
        assert is_smaller_than(-100, "1MB") is False

    def test_zero_size(self):
        """Zero size returns False for positive threshold."""
        assert is_smaller_than(0, "1MB") is True

    def test_zero_threshold(self):
        """Zero threshold comparison works."""
        assert is_smaller_than(0, "0MB") is False

    def test_iec_units(self):
        """IEC units work correctly."""
        assert is_smaller_than(1048576, "2MiB") is True  # 1 MiB < 2 MiB

    def test_fractional_threshold(self):
        """Fractional threshold works."""
        assert is_smaller_than(1000000, "1.5MB") is True


# ============================================================================
# is_older_than()
# ============================================================================


class TestIsOlderThan:
    """Test is_older_than() function."""

    def test_older(self):
        """Timestamp older than duration returns True."""
        now = int(time.time())
        old_timestamp = now - 7776000  # 90 days ago
        assert is_older_than(old_timestamp, "30 days") is True

    def test_newer(self):
        """Timestamp newer than duration returns False."""
        now = int(time.time())
        recent_timestamp = now - 86400  # 1 day ago
        assert is_older_than(recent_timestamp, "30 days") is False

    @patch("qbt_rules.utils.time.time", return_value=1700000000)
    def test_exact_duration(self, mock_time):
        """Timestamp exactly at duration boundary."""
        now = 1700000000
        timestamp = now - 2592000  # Exactly 30 days
        # Should be False because age == duration (not >)
        assert is_older_than(timestamp, "30 days") is False

    def test_zero_timestamp(self):
        """Zero timestamp returns False."""
        assert is_older_than(0, "30 days") is False

    def test_negative_timestamp(self):
        """Negative timestamp returns False."""
        assert is_older_than(-100, "30 days") is False

    def test_unsigned_minus_one_sentinel(self):
        """qBittorrent 4.x's "never" (the unsigned -1) returns False."""
        assert is_older_than(4294967295, "30 days") is False

    def test_very_old(self):
        """Very old timestamp returns True."""
        old_timestamp = 946684800  # Year 2000
        assert is_older_than(old_timestamp, "1 year") is True

    def test_future_timestamp(self):
        """Future timestamp returns False."""
        now = int(time.time())
        future_timestamp = now + 86400  # Tomorrow
        assert is_older_than(future_timestamp, "1 day") is False

    def test_different_units(self):
        """Different time units work correctly."""
        now = int(time.time())
        timestamp = now - 7200  # 2 hours ago
        assert is_older_than(timestamp, "1 hour") is True
        assert is_older_than(timestamp, "3 hours") is False


# ============================================================================
# is_newer_than()
# ============================================================================


class TestIsNewerThan:
    """Test is_newer_than() function."""

    def test_newer(self):
        """Timestamp newer than duration returns True."""
        now = int(time.time())
        recent_timestamp = now - 86400  # 1 day ago
        assert is_newer_than(recent_timestamp, "30 days") is True

    def test_older(self):
        """Timestamp older than duration returns False."""
        now = int(time.time())
        old_timestamp = now - 7776000  # 90 days ago
        assert is_newer_than(old_timestamp, "30 days") is False

    def test_exact_duration(self):
        """Timestamp exactly at duration boundary."""
        now = int(time.time())
        timestamp = now - 2592000  # Exactly 30 days
        # Should be False because age == duration (not <)
        assert is_newer_than(timestamp, "30 days") is False

    def test_zero_timestamp(self):
        """Zero timestamp returns False."""
        assert is_newer_than(0, "30 days") is False

    def test_negative_timestamp(self):
        """Negative timestamp returns False."""
        assert is_newer_than(-100, "30 days") is False

    def test_unsigned_minus_one_sentinel(self):
        """qBittorrent 4.x's "never" (the unsigned -1) is not a time in the future"""
        assert is_newer_than(4294967295, "30 days") is False

    def test_very_recent(self):
        """Very recent timestamp returns True."""
        now = int(time.time())
        timestamp = now - 60  # 1 minute ago
        assert is_newer_than(timestamp, "1 hour") is True

    def test_future_timestamp(self):
        """Future timestamp returns True."""
        now = int(time.time())
        future_timestamp = now + 86400  # Tomorrow
        assert is_newer_than(future_timestamp, "1 day") is True

    def test_different_units(self):
        """Different time units work correctly."""
        now = int(time.time())
        timestamp = now - 1800  # 30 minutes ago
        assert is_newer_than(timestamp, "1 hour") is True
        assert is_newer_than(timestamp, "15 minutes") is False


# ============================================================================
# format_bytes()
# ============================================================================


class TestFormatBytes:
    """Test format_bytes() function."""

    def test_bytes(self):
        """Bytes are formatted correctly."""
        assert format_bytes(500) == "500.00 B"

    def test_kilobytes(self):
        """Kilobytes are formatted correctly."""
        assert format_bytes(1536) == "1.50 KB"

    def test_megabytes(self):
        """Megabytes are formatted correctly."""
        assert format_bytes(1572864) == "1.50 MB"

    def test_gigabytes(self):
        """Gigabytes are formatted correctly."""
        assert format_bytes(1610612736) == "1.50 GB"

    def test_terabytes(self):
        """Terabytes are formatted correctly."""
        assert format_bytes(1649267441664) == "1.50 TB"

    def test_petabytes(self):
        """Petabytes are formatted correctly."""
        assert format_bytes(1688849860263936) == "1.50 PB"

    def test_zero(self):
        """Zero bytes formatted correctly."""
        assert format_bytes(0) == "0.00 B"

    def test_exact_boundary(self):
        """Exact unit boundary formatted correctly."""
        assert format_bytes(1024) == "1.00 KB"


# ============================================================================
# format_speed()
# ============================================================================


class TestFormatSpeed:
    """Test format_speed() function."""

    def test_bytes_per_second(self):
        """Bytes per second formatted with /s suffix."""
        assert format_speed(500) == "500.00 B/s"

    def test_kilobytes_per_second(self):
        """Kilobytes per second formatted correctly."""
        assert format_speed(1536) == "1.50 KB/s"

    def test_megabytes_per_second(self):
        """Megabytes per second formatted correctly."""
        assert format_speed(1572864) == "1.50 MB/s"

    def test_zero_speed(self):
        """Zero speed formatted correctly."""
        assert format_speed(0) == "0.00 B/s"


# ============================================================================
# format_duration()
# ============================================================================


class TestFormatDuration:
    """Test format_duration() function."""

    def test_seconds_only(self):
        """Seconds only (< 60s)."""
        assert format_duration(45) == "45s"

    def test_minutes_only(self):
        """Minutes only."""
        assert format_duration(300) == "5m"

    def test_hours_only(self):
        """Hours only."""
        assert format_duration(7200) == "2h"

    def test_days_only(self):
        """Days only."""
        assert format_duration(172800) == "2d"

    def test_days_and_hours(self):
        """Days and hours."""
        assert format_duration(90000) == "1d 1h"

    def test_days_hours_minutes(self):
        """Days, hours, and minutes."""
        assert format_duration(90060) == "1d 1h 1m"

    def test_hours_and_minutes(self):
        """Hours and minutes."""
        assert format_duration(3660) == "1h 1m"

    def test_zero_duration(self):
        """Zero duration."""
        assert format_duration(0) == "0s"

    def test_large_duration(self):
        """Large duration."""
        assert format_duration(2592000) == "30d"

    def test_no_seconds_in_output(self):
        """Seconds are not shown when >= 60."""
        assert format_duration(125) == "2m"  # 2m 5s, but 5s is omitted


# ============================================================================
# validate_field_name()
# ============================================================================


class TestValidateFieldName:
    """Test validate_field_name() function."""

    def test_valid_info_field(self):
        """Valid info field."""
        assert validate_field_name("info.name") is True

    def test_valid_trackers_field(self):
        """Valid trackers field."""
        assert validate_field_name("trackers.url") is True

    def test_valid_files_field(self):
        """Valid files field."""
        assert validate_field_name("files.size") is True

    def test_valid_peers_field(self):
        """Valid peers field."""
        assert validate_field_name("peers.ip") is True

    def test_valid_properties_field(self):
        """Valid properties field."""
        assert validate_field_name("properties.save_path") is True

    def test_valid_transfer_field(self):
        """Valid transfer field."""
        assert validate_field_name("transfer.dl_speed") is True

    def test_valid_webseeds_field(self):
        """Valid webseeds field."""
        assert validate_field_name("webseeds.url") is True

    def test_invalid_prefix(self):
        """Invalid prefix returns False."""
        assert validate_field_name("invalid.field") is False

    def test_no_dot(self):
        """No dot returns False."""
        assert validate_field_name("invalidfield") is False

    def test_empty_string(self):
        """Empty string returns False."""
        assert validate_field_name("") is False

    def test_only_dot(self):
        """Only dot returns False."""
        assert validate_field_name(".") is False

    def test_nested_field(self):
        """Nested field works (only first prefix checked)."""
        assert validate_field_name("info.nested.field") is True
