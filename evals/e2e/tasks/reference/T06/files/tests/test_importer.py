import pytest

from inventory.errors import ValidationError
from inventory.importer import (
    ImportReport,
    import_items,
    import_items_file,
    import_stock,
    import_stock_file,
    iter_rows,
    parse_quantity,
    read_text,
)

ITEMS = "sku,name,price,category\nNUT-1,Hex nut,0.25,parts\nBOLT-2,Bolt,0.40,\n,,,\nBAD,Bad price,abc,parts\nNUT-1,Duplicate,1.00,parts\n"


def test_items_are_imported_and_bad_rows_reported(app):
    report = import_items(ITEMS, app.catalog)
    assert report.imported == 2 and report.skipped == 2 and not report.ok
    assert app.catalog.get_item("BOLT-2").category == "general"
    assert [error.line for error in report.errors] == [5, 6]


def test_missing_columns_are_rejected():
    with pytest.raises(ValidationError, match="sku"):
        list(iter_rows("name,price\nx,1\n", ("sku", "name", "price")))


def test_blank_rows_are_skipped():
    rows = list(iter_rows("sku,warehouse,quantity\n\n , , \nA1,MAIN,3\n", ("sku", "warehouse", "quantity")))
    assert [row["sku"] for _, row in rows] == ["A1"]


def test_parse_quantity_rules():
    assert parse_quantity("7") == 7
    for bad in ("x", "1.5", "-2"):
        with pytest.raises(ValidationError):
            parse_quantity(bad)


def test_stock_rows_are_received_or_reported(app):
    text = "sku,warehouse,quantity\nWIDGET,main,5\nWIDGET,MAIN,0\nWIDGET,NOWHERE,1\nGADGET,EAST,two\n"
    report = import_stock(text, app.stock)
    assert report.imported == 1 and report.skipped == 3
    assert app.stock.quantity("MAIN", "WIDGET") == 25
    assert "quantity is zero" in report.summary()


def test_summary_lists_five_errors_and_counts_the_rest():
    report = ImportReport()
    for line in range(2, 9):
        report.add_error(line, "bad")
    text = report.summary()
    assert text.startswith("imported 0, skipped 7") and "(+2 more)" in text and "line 6: bad" in text
    assert "line 7" not in text


def test_summary_of_a_clean_import_is_short():
    report = ImportReport(imported=3)
    assert report.ok and report.summary() == "imported 3, skipped 0"


def test_files_are_read_with_a_bom_and_missing_files_fail(app, tmp_path):
    items = tmp_path / "items.csv"
    items.write_bytes(b"\xef\xbb\xbfsku,name,price\nNUT-9,Nut,1.50\n")
    assert import_items_file(items, app.catalog).imported == 1
    stock = tmp_path / "stock.csv"
    stock.write_text("sku,warehouse,quantity\nNUT-9,MAIN,4\n", encoding="utf-8")
    assert import_stock_file(stock, app.stock).imported == 1
    with pytest.raises(ValidationError, match="cannot read"):
        read_text(tmp_path / "missing.csv")
