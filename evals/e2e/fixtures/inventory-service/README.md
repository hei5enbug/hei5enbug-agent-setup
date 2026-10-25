# inventory-service

A small inventory and order management service for a two-warehouse shop. It keeps items, per-warehouse stock,
orders, and a stock audit log in one JSON file, and ships with a command line interface.

## Quick start

```bash
python3 -m inventory warehouse add MAIN "Main warehouse" --priority 10
python3 -m inventory warehouse add EAST "East depot" --priority 20
python3 -m inventory item add WIDGET "Widget" 10.00 --category hardware
python3 -m inventory stock receive MAIN WIDGET 20
python3 -m inventory order create --customer kim@example.com --line WIDGET=3
python3 -m inventory report
```

Use `--data FILE` before the command to choose the data file. All commands exit with 0 on success and 2 when the
request is rejected; the reason is printed on stderr.

## Concepts

- **Item**: a product with a SKU, a name, a category, and a unit price.
- **Warehouse**: a stock location. A lower `priority` number is drawn from first.
- **Order**: placing an order takes stock from the warehouses immediately and records where each unit came from.
  An order is `placed`, then `shipped`, or `cancelled`. Only a placed order can be cancelled.
- **Pricing**: lines of 10, 50, and 100 units get a 5, 10, and 15 percent discount. Tax is added to the subtotal.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INVENTORY_DATA_FILE` | `inventory.json` | Path of the JSON data file. |
| `INVENTORY_CURRENCY` | `USD` | Three-letter currency code shown in reports. |
| `INVENTORY_TAX_RATE` | `0.08` | Tax rate between 0 and 1 added to each order subtotal. |

## CSV import

`import items FILE` reads the columns `sku,name,price[,category]`. `import stock FILE` reads
`sku,warehouse,quantity`. Rows that fail validation are skipped and listed in the summary.

## Development

```bash
python3 -m pytest -q
python3 tools/linecov.py inventory/importer.py
```

`tools/linecov.py` runs the test suite and prints the line coverage of one module with the line numbers that were
never executed. It needs nothing besides pytest. Add `--min 90` to exit with 1 when the coverage is lower.

Project rules for contributors and agents are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
