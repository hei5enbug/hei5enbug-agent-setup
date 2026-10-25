"""Period reports."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from .journal import Journal


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def month_end_balances(journal: Journal, year: int, month: int) -> dict[str, Decimal]:
    """Balance of every account at the end of the given month."""
    last_day = month_end(year, month)
    return {account: journal.balance(account, last_day) for account in journal.accounts()}


def trial_balance(journal: Journal, as_of: date) -> Decimal:
    """Sum of all account balances at `as_of`. A consistent double-entry journal always gives zero."""
    return sum((journal.balance(account, as_of) for account in journal.accounts()), Decimal("0"))
