from datetime import date
from decimal import Decimal

import pytest

from ledger.statements import StatementError, load_statement


def test_statement_lines_are_sorted_and_typed(sample_dir):
    lines = load_statement(sample_dir / "march_statement.csv")
    assert len(lines) == 6
    assert lines[0].date == date(2026, 3, 1) and lines[0].amount == Decimal("5000.00")
    assert [line.date for line in lines] == sorted(line.date for line in lines)


def test_bad_date_is_reported_with_its_line(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("date,description,amount\n2026-13-01,x,1\n", encoding="utf-8")
    with pytest.raises(StatementError, match=r"s\.csv:2"):
        load_statement(path)


def test_missing_column_is_an_error(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("date,amount\n2026-03-01,1\n", encoding="utf-8")
    with pytest.raises(StatementError):
        load_statement(path)
