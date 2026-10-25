import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "inventory/config.py", "from .errors import ConfigError\n", "from .errors import ConfigError\nfrom .reports import LOW_STOCK_THRESHOLD\n")
replace(repo, "inventory/config.py", "    tax_rate: Decimal = DEFAULT_TAX_RATE\n",
        "    tax_rate: Decimal = DEFAULT_TAX_RATE\n    low_stock_threshold: int = LOW_STOCK_THRESHOLD\n")
replace(repo, "inventory/config.py", '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n',
        '            tax_rate=_read_rate(env.get("INVENTORY_TAX_RATE"), DEFAULT_TAX_RATE),\n            low_stock_threshold=_read_threshold(env.get("INVENTORY_LOW_STOCK")),\n')
replace(repo, "inventory/config.py", "def _read_currency(", '''def _read_threshold(raw: str | None) -> int:
    if raw is None or not raw.strip():
        return LOW_STOCK_THRESHOLD
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"INVENTORY_LOW_STOCK must be a whole number, got {raw!r}") from exc
    if value < 0:
        raise ConfigError(f"INVENTORY_LOW_STOCK must not be negative, got {raw!r}")
    return value


def _read_currency(''')
replace(repo, "inventory/cli.py", "import argparse\nimport sys\n", "import argparse\nimport json\nimport sys\n")
replace(repo, "inventory/cli.py", '    report.set_defaults(handler=cmd_report)',
        '    report.add_argument("--format", choices=("text", "json"), default="text")\n    report.set_defaults(handler=cmd_report)')
replace(repo, "inventory/cli.py", '''    threshold = reports.LOW_STOCK_THRESHOLD
    sections = [
        formatting.render_valuation(reports.stock_valuation(app.db)),
        formatting.render_low_stock(reports.low_stock_items(app.db, threshold), threshold),
        formatting.render_order_counts(reports.order_counts(app.db)),
    ]
''', '''    threshold = app.config.low_stock_threshold
    valuations = reports.stock_valuation(app.db)
    low_stock = reports.low_stock_items(app.db, threshold)
    counts = reports.order_counts(app.db)
    if args.format == "json":
        payload = {
            "valuation": {valuation.warehouse: f"{valuation.total:.2f}" for valuation in valuations},
            "low_stock": [{"sku": e.sku, "name": e.name, "quantity": e.quantity} for e in low_stock],
            "orders": counts,
        }
        print(json.dumps(payload), file=out)
        return
    sections = [
        formatting.render_valuation(valuations),
        formatting.render_low_stock(low_stock, threshold),
        formatting.render_order_counts(counts),
    ]
''')
