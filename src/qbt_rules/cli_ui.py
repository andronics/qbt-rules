"""
CLI data-display rendering

Dedicated output layer for data-display commands (--list-jobs, --job-status,
--stats, --cancel-job, --list-rules). Writes directly to stdout via print() --
never goes through the logging module, so diagnostic logging (timestamps,
levels) stays fully separate from user-facing tables and detail dumps.
"""

import json
from typing import Any, List, Optional, Sequence, Tuple


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """
    Render headers and rows as an aligned table string

    Column widths auto-size to content (header or widest cell in that
    column), with a two-space gutter between columns.

    Args:
        headers: Column header labels
        rows: Row data, each row a sequence of values (str() is applied)

    Returns:
        Multi-line table string (header row, separator rule, data rows)
    """
    str_rows = [[str(cell) for cell in row] for row in rows]

    widths = [len(str(header)) for header in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def format_row(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    header_line = format_row(headers)
    lines = [header_line, "-" * len(header_line)]
    lines.extend(format_row(row) for row in str_rows)

    return "\n".join(lines)


def print_table(headers: Sequence[str], rows: Sequence[Sequence[Any]], title: Optional[str] = None) -> None:
    """
    Print a table, optionally preceded by a title line

    Args:
        headers: Column header labels
        rows: Row data, each row a sequence of values
        title: Optional title printed on its own line before the table
    """
    if title:
        print(f"\n{title}\n")
    print(render_table(headers, rows))


def render_kv(pairs: Sequence[Tuple[str, Any]], indent: int = 0) -> str:
    """
    Render label/value pairs as aligned "Label: value" lines

    Args:
        pairs: (label, value) tuples
        indent: Number of spaces to prefix each line with

    Returns:
        Multi-line "Label: value" string, labels aligned to the widest label
    """
    prefix = " " * indent
    width = max((len(str(label)) for label, _ in pairs), default=0)
    return "\n".join(f"{prefix}{str(label) + ':':<{width + 1}} {value}" for label, value in pairs)


def print_kv_section(title: str, pairs: Sequence[Tuple[str, Any]], indent: int = 0) -> None:
    """
    Print a titled section followed by its label/value pairs

    Args:
        title: Section title, printed on its own line
        pairs: (label, value) tuples
        indent: Number of spaces to prefix each label/value line with
    """
    prefix = " " * indent
    print(f"\n{prefix}{title}")
    print(render_kv(pairs, indent=indent + 2))


def print_json(data: Any) -> None:
    """
    Print data as indented JSON

    Args:
        data: JSON-serializable value (non-serializable values are
              stringified via json.dumps' default=str)
    """
    print(json.dumps(data, indent=2, default=str))


def print_message(text: str) -> None:
    """Print a one-off message line (confirmations, empty-state notices)"""
    print(text)
