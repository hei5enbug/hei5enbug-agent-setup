from datetime import date
from decimal import Decimal

from ledger.reports import month_end, month_end_balances, trial_balance


def test_month_end_handles_leap_years():
    assert month_end(2028, 2) == date(2028, 2, 29)
    assert month_end(2027, 2) == date(2027, 2, 28)


def test_march_month_end_balances(march_journal):
    balances = month_end_balances(march_journal, 2026, 3)
    assert balances["bank"] == Decimal("4450.51")
    assert balances["payroll"] == Decimal("1500.00")
    assert balances["sales"] == Decimal("-2300.50")


def test_trial_balance_is_zero_for_a_balanced_journal(march_journal):
    assert trial_balance(march_journal, date(2026, 3, 31)) == Decimal("0")
    assert trial_balance(march_journal, date(2026, 3, 10)) == Decimal("0")
