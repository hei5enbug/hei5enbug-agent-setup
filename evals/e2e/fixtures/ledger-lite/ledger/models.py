"""Records used across the package. Debits are positive amounts and credits are negative ones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Entry:
    date: date
    account: str
    amount: Decimal
    memo: str = ""


@dataclass(frozen=True)
class StatementLine:
    date: date
    description: str
    amount: Decimal
