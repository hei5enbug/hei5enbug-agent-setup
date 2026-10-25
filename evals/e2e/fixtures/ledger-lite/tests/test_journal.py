from datetime import date
from decimal import Decimal

import pytest

from ledger.journal import Journal, JournalError, load_entries
from ledger.models import Entry


def entry(day: int, account: str, amount: str) -> Entry:
    return Entry(date(2026, 3, day), account, Decimal(amount))


def test_entries_are_kept_in_date_order():
    journal = Journal([entry(9, "bank", "1"), entry(2, "bank", "2")])
    assert [e.date.day for e in journal.entries()] == [2, 9]


def test_add_returns_a_new_journal():
    journal = Journal()
    bigger = journal.add(entry(1, "bank", "5"))
    assert len(journal) == 0 and len(bigger) == 1


def test_balance_without_cutoff_sums_everything():
    journal = Journal([entry(1, "bank", "10.50"), entry(8, "bank", "-3.25"), entry(8, "cash", "9")])
    assert journal.balance("bank") == Decimal("7.25")


def test_balance_ignores_entries_after_the_cutoff():
    journal = Journal([entry(1, "bank", "10"), entry(20, "bank", "5")])
    assert journal.balance("bank", date(2026, 3, 10)) == Decimal("10")


def test_balance_of_an_unknown_account_is_zero():
    assert Journal([entry(1, "bank", "10")]).balance("cash") == Decimal("0")


def test_march_closing_balance_includes_the_last_day(march_journal):
    assert march_journal.balance("bank", date(2026, 3, 31)) == Decimal("4450.51")


def test_march_journal_is_balanced(march_journal):
    assert march_journal.is_balanced()
    assert len(march_journal) == 10


def test_bad_rows_name_file_and_line(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,account,amount,memo\n2026-03-01,bank,abc,x\n", encoding="utf-8")
    with pytest.raises(JournalError, match=r"bad\.csv:2"):
        load_entries(path)
