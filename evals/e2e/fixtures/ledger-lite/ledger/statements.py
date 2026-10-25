"""Bank statement files."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import StatementLine


class StatementError(ValueError):
    """A statement file could not be read."""


def load_statement(path: str | Path) -> list[StatementLine]:
    lines: list[StatementLine] = []
    with open(path, newline="", encoding="utf-8") as stream:
        for number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                lines.append(
                    StatementLine(
                        date=date.fromisoformat(row["date"].strip()),
                        description=row["description"].strip(),
                        amount=Decimal(row["amount"].strip()),
                    )
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                raise StatementError(f"{path}:{number}: bad statement row ({exc})") from exc
    return sorted(lines, key=lambda line: line.date)
