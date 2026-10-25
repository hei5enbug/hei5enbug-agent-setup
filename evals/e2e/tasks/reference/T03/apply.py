import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "inventory/reports.py", '''    total = ZERO
    for row in rows:
        if row.quantity == 0:
            rows.remove(row)
            continue
        total += row.value
''', '''    rows = [row for row in rows if row.quantity > 0]
    total = sum((row.value for row in rows), ZERO)
''')
append(repo, "tests/test_reports.py", '''

def test_valuation_counts_the_item_after_an_emptied_one(app):
    app.stock.adjust("MAIN", "GADGET", 0)
    valuation = reports.warehouse_valuation(app.db, "MAIN")
    assert [r.sku for r in valuation.rows] == ["WIDGET"]
    assert valuation.total == Decimal("200.00")
''')
