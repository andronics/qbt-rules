"""Tests for qbt_rules.cli_ui"""

import json

from qbt_rules.cli_ui import (
    render_table,
    print_table,
    render_kv,
    print_kv_section,
    print_json,
    print_message,
)


class TestRenderTable:
    """Test render_table()"""

    def test_renders_header_separator_and_rows(self):
        """Should produce a header line, separator rule, then one line per row"""
        result = render_table(['Job ID', 'Status'], [['abc-123', 'completed']])
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0].startswith('Job ID')
        assert set(lines[1]) == {'-'}
        assert 'abc-123' in lines[2]
        assert 'completed' in lines[2]

    def test_columns_auto_size_to_widest_cell(self):
        """Column width should expand to fit the widest cell, not just the header"""
        result = render_table(['ID'], [['a-very-long-identifier'], ['x']])
        lines = result.split("\n")

        # header, separator, and both data rows must all be the same length
        assert len(lines[0]) == len(lines[1]) == len(lines[2]) == len(lines[3])

    def test_separator_matches_full_row_width(self):
        """Separator rule should span the full width of the widest row, including header"""
        result = render_table(['Job ID', 'Status'], [['a-very-long-job-id', 'completed']])
        lines = result.split("\n")

        assert len(lines[1]) == len(lines[0]) == len(lines[2])

    def test_handles_empty_rows(self):
        """Should render just header + separator when there are no rows"""
        result = render_table(['Job ID', 'Status'], [])
        lines = result.split("\n")

        assert len(lines) == 2
        assert lines[0].startswith('Job ID')

    def test_non_string_cells_are_stringified(self):
        """Non-string cell values should be converted via str()"""
        result = render_table(['Count'], [[42]])

        assert '42' in result


class TestPrintTable:
    """Test print_table()"""

    def test_prints_table_without_title(self, capsys):
        """Should print just the table when no title is given"""
        print_table(['ID'], [['abc']])
        captured = capsys.readouterr()

        assert 'ID' in captured.out
        assert 'abc' in captured.out
        assert captured.out.startswith('ID')

    def test_prints_title_before_table(self, capsys):
        """Should print the title on its own line before the table"""
        print_table(['ID'], [['abc']], title='Jobs (showing 1 of 1 total):')
        captured = capsys.readouterr()

        assert 'Jobs (showing 1 of 1 total):' in captured.out
        title_pos = captured.out.index('Jobs (showing')
        table_pos = captured.out.index('ID')
        assert title_pos < table_pos


class TestRenderKv:
    """Test render_kv()"""

    def test_renders_label_value_pairs(self):
        """Should render each pair as 'Label: value'"""
        result = render_kv([('Job ID', 'abc-123'), ('Status', 'completed')])
        lines = result.split("\n")

        assert 'Job ID:' in lines[0]
        assert 'abc-123' in lines[0]
        assert 'Status:' in lines[1]
        assert 'completed' in lines[1]

    def test_labels_align_to_widest_label(self):
        """Values should start at the same column regardless of label length"""
        result = render_kv([('A', '1'), ('Longer Label', '2')])
        lines = result.split("\n")

        assert lines[0].index('1') == lines[1].index('2')

    def test_applies_indent(self):
        """Should prefix every line with the requested indent"""
        result = render_kv([('Key', 'value')], indent=4)

        assert result.startswith('    ')


class TestPrintKvSection:
    """Test print_kv_section()"""

    def test_prints_title_then_pairs(self, capsys):
        """Should print the section title followed by its pairs, pairs indented further"""
        print_kv_section('Job Details:', [('Job ID', 'abc-123')])
        captured = capsys.readouterr()

        assert 'Job Details:' in captured.out
        assert 'Job ID:' in captured.out
        assert 'abc-123' in captured.out
        title_pos = captured.out.index('Job Details:')
        pair_pos = captured.out.index('Job ID:')
        assert title_pos < pair_pos


class TestPrintJson:
    """Test print_json()"""

    def test_prints_valid_json(self, capsys):
        """Output should be parseable JSON matching the input"""
        data = {'job_id': 'abc-123', 'status': 'completed'}
        print_json(data)
        captured = capsys.readouterr()

        assert json.loads(captured.out) == data

    def test_serializes_non_json_native_values_via_str(self, capsys):
        """Values without a native JSON representation should be stringified, not raise"""
        class Weird:
            def __str__(self):
                return 'weird-value'

        print_json({'thing': Weird()})
        captured = capsys.readouterr()

        assert json.loads(captured.out) == {'thing': 'weird-value'}


class TestPrintMessage:
    """Test print_message()"""

    def test_prints_the_message(self, capsys):
        """Should print the given text as-is"""
        print_message('No jobs found')
        captured = capsys.readouterr()

        assert captured.out.strip() == 'No jobs found'
