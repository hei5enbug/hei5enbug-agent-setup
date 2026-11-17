# orders-svc

A small order service on SQLite with a command line. The database file is `ORDERS_DB`, or `data/orders.db`.

## Commands

```bash
python3 -m orders place c-1 tea:450:2 mug:1200:1 --discount 10
python3 -m orders list
python3 -m orders report invoice ord-0001
python3 -m orders cancel ord-0001
```

- `place CUSTOMER SKU:UNIT_PRICE_CENTS:QUANTITY... [--discount PERCENT]` places an order and prints its id.
- `cancel ORDER`, `ship ORDER` move a placed order to `cancelled` or `shipped`.
- `amend ORDER SKU QUANTITY` sets the quantity of a line, and `add-line ORDER SKU QUANTITY UNIT_PRICE_CENTS` adds one.
- `list` prints one row per order: id, date, status, customer.
- `report invoice ORDER [--bill-to]` prints the invoice with tax. `whoami CUSTOMER` prints a customer's name and tier.
- A failing command prints the reason on stderr and exits with 1.

## Rules

- Only a placed order can change. A shipped or cancelled order is final.
- Sales tax is 7.25 percent of the discounted amount, rounded half up to whole cents.

## Database engine

Dates are formatted inside the SQL queries by SQLite's `strftime` (`SQL_DAY` in `orders/dates.py`), and
`orders.dates.format_day` must give the same text for Python-side values. The formatting depends on the engine, so
after changing either one, run `python3 scripts/check_engine.py`, which compares both on the real engine.

## Development

```bash
python3 -m pytest -q
```
