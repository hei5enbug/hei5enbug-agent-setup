"""Match bank statement lines to journal entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .journal import Journal
from .models import Entry, StatementLine

DEFAULT_WINDOW_DAYS = 3


@dataclass
class ReconcileResult:
    matched: list[tuple[Entry, StatementLine]] = field(default_factory=list)
    unmatched_entries: list[Entry] = field(default_factory=list)
    unmatched_lines: list[StatementLine] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.unmatched_entries and not self.unmatched_lines


def reconcile(
    journal: Journal,
    lines: list[StatementLine],
    account: str = "bank",
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> ReconcileResult:
    """Pair each statement line with an unused entry of the same amount dated within `window_days`."""
    window = timedelta(days=window_days)
    free = journal.entries(account)
    result = ReconcileResult()
    for line in lines:
        match = next(
            (entry for entry in free if entry.amount == line.amount and abs(entry.date - line.date) <= window),
            None,
        )
        if match is None:
            result.unmatched_lines.append(line)
            continue
        free.remove(match)
        result.matched.append((match, line))
    result.unmatched_entries = free
    return result
