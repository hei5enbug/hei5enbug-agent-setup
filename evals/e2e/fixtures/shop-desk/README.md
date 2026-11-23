# shop-desk

Order desk for a small shop: customers, orders, and a sales report, kept in one JSON file.

## Usage

```bash
python3 -m shop --store shop-data.json place 1 AB-100:2,CD-200:1
python3 -m shop --store shop-data.json lookup 1
python3 -m shop --store shop-data.json sales
python3 -m shop price AB-100
python3 -m shop week 2026-03-01
```

- `--store FILE` names the data file; it defaults to `shop-data.json`, or to `SHOP_STORE` when that is set.
- `place CUSTOMER_ID SKU:QTY[,SKU:QTY...]` stores an order and prints its subtotal, discount, and total. A customer's
  tier gives a percentage discount on the subtotal: basic 0, silver 5, gold 10.
- `lookup CUSTOMER_ID` prints the customer's name and tier.
- `sales` prints one line per customer with the order count, net amount, and tax.
- `price SKU` prints the unit price of a SKU. A SKU is matched ignoring case and surrounding spaces, everywhere one is
  accepted.
- `week DATE` prints the week label of a day, such as `2026-W09`.
- A failing command prints the reason on stderr and exits with 2.

## Settings

A setting has a default in `shop/settings.py` and is overridden by the environment variable `SHOP_<NAME>` in upper case,
for example `SHOP_TAX_PERCENT=10`.

## Reporting database

The week labels are also computed inside the reporting database, which runs SQLite and counts a week from Sunday, with
the days before the year's first Sunday in week 00. A label in `shop/dates.py` must equal the database's label for the
same day. `python3 scripts/engine_check.py` compares the two over every day of 2020 to 2030.

## Development

```bash
python3 -m pytest -q
```

Contribution rules are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
