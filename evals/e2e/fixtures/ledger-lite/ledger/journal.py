"""The journal: a date-ordered list of entries with balance queries."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from .models import Entry


class JournalError(ValueError):
    """An entry file could not be read."""


class Journal:
    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        self._entries = sorted(entries, key=lambda entry: entry.date)

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, entry: Entry) -> "Journal":
        """Return a new journal that also holds `entry`."""
        return Journal([*self._entries, entry])

    def entries(self, account: str | None = None) -> list[Entry]:
        return [entry for entry in self._entries if account is None or entry.account == account]

    def accounts(self) -> list[str]:
        return sorted({entry.account for entry in self._entries})

    def balance(self, account: str, as_of: date | None = None) -> Decimal:
        """Sum of the account's entries dated up to and including `as_of`, or of all entries when it is None."""
        return sum(
            (
                entry.amount
                for entry in self._entries
                if entry.account == account and (as_of is None or entry.date < as_of)
            ),
            Decimal("0"),
        )

    def is_balanced(self) -> bool:
        return sum((entry.amount for entry in self._entries), Decimal("0")) == 0


def load_entries(path: str | Path) -> Journal:
    entries: list[Entry] = []
    with open(path, newline="", encoding="utf-8") as stream:
        for number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                entries.append(
                    Entry(
                        date=date.fromisoformat(row["date"].strip()),
                        account=row["account"].strip(),
                        amount=Decimal(row["amount"].strip()),
                        memo=(row.get("memo") or "").strip(),
                    )
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                raise JournalError(f"{path}:{number}: bad entry row ({exc})") from exc
    return Journal(entries)
