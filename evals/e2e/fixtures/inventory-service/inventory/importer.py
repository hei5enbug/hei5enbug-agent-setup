"""CSV import of items and opening stock.

Item files have the columns sku, name, price and optionally category. Stock files have sku, warehouse and quantity.
Rows that fail validation are collected in the report instead of aborting the whole file.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .errors import InventoryError, ValidationError
from .items import CatalogService
from .money import parse_money
from .stock import StockLedger

ITEM_COLUMNS = ("sku", "name", "price")
STOCK_COLUMNS = ("sku", "warehouse", "quantity")


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, line: int, message: str) -> None:
        self.skipped += 1
        self.errors.append(RowError(line, message))

    def summary(self) -> str:
        text = f"imported {self.imported}, skipped {self.skipped}"
        if self.errors:
            details = "; ".join(f"line {error.line}: {error.message}" for error in self.errors[:5])
            more = len(self.errors) - 5
            suffix = f" (+{more} more)" if more > 0 else ""
            text = f"{text}. {details}{suffix}"
        return text


def read_text(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc.strerror or exc}") from exc


def iter_rows(text: str, required: tuple[str, ...]) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (line number, row) for each data row, after checking that the header has the required columns."""
    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip().lower() for name in (reader.fieldnames or [])]
    missing = [column for column in required if column not in header]
    if missing:
        raise ValidationError(f"missing column(s): {', '.join(missing)}")
    reader.fieldnames = header
    for row in reader:
        if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue
        yield reader.line_num, {key: (value or "").strip() for key, value in row.items() if isinstance(key, str)}


def parse_quantity(raw: str) -> int:
    try:
        quantity = int(raw)
    except ValueError:
        raise ValidationError(f"quantity is not a whole number: {raw!r}") from None
    if quantity < 0:
        raise ValidationError(f"quantity must not be negative: {quantity}")
    return quantity


def import_items(text: str, catalog: CatalogService) -> ImportReport:
    report = ImportReport()
    for line, row in iter_rows(text, ITEM_COLUMNS):
        try:
            price: Decimal = parse_money(row["price"])
            catalog.add_item(row["sku"], row["name"], price, row.get("category") or "general")
        except InventoryError as exc:
            report.add_error(line, str(exc))
            continue
        report.imported += 1
    return report


def import_stock(text: str, ledger: StockLedger, *, reference: str = "csv-import") -> ImportReport:
    report = ImportReport()
    for line, row in iter_rows(text, STOCK_COLUMNS):
        try:
            quantity = parse_quantity(row["quantity"])
            if quantity == 0:
                report.add_error(line, "quantity is zero")
                continue
            ledger.receive(row["warehouse"].upper(), row["sku"], quantity, reference)
        except InventoryError as exc:
            report.add_error(line, str(exc))
            continue
        report.imported += 1
    return report


def import_items_file(path: str | Path, catalog: CatalogService) -> ImportReport:
    return import_items(read_text(path), catalog)


def import_stock_file(path: str | Path, ledger: StockLedger) -> ImportReport:
    return import_stock(read_text(path), ledger)
