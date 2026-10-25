from datetime import date
from decimal import Decimal

from ledger.journal import Journal
from ledger.models import Entry
from ledger.reports import month_end_balances, trial_balance


def entry(day, account, amount, month=3):
    return Entry(date(2026, month, day), account, Decimal(amount))


def test_entries_on_the_cutoff_day_are_included():
    journal = Journal([entry(1, "bank", "10"), entry(15, "bank", "5"), entry(16, "bank", "7")])
    assert journal.balance("bank", date(2026, 3, 15)) == Decimal("15")


def test_cutoff_before_the_first_entry_gives_zero():
    journal = Journal([entry(10, "bank", "10")])
    assert journal.balance("bank", date(2026, 3, 9)) == Decimal("0")
    assert journal.balance("bank", date(2026, 3, 10)) == Decimal("10")


def test_several_entries_on_the_same_day_all_count():
    journal = Journal([entry(5, "bank", "1.10"), entry(5, "bank", "2.20"), entry(5, "cash", "9")])
    assert journal.balance("bank", date(2026, 3, 5)) == Decimal("3.30")
    assert journal.balance("cash", date(2026, 3, 5)) == Decimal("9")


def test_without_a_cutoff_everything_counts():
    journal = Journal([entry(1, "bank", "4"), entry(31, "bank", "6")])
    assert journal.balance("bank") == Decimal("10")


def test_month_end_balances_include_the_last_day():
    journal = Journal([entry(30, "bank", "100", month=4), entry(1, "bank", "50", month=5)])
    assert month_end_balances(journal, 2026, 4) == {"bank": Decimal("100")}
    assert month_end_balances(journal, 2026, 5) == {"bank": Decimal("150")}


def test_trial_balance_on_a_day_with_entries_is_zero():
    journal = Journal([entry(31, "bank", "-20"), entry(31, "rent", "20"), entry(2, "bank", "30"), entry(2, "equity", "-30")])
    assert trial_balance(journal, date(2026, 3, 31)) == Decimal("0")
    assert journal.balance("bank", date(2026, 3, 31)) == Decimal("10")
