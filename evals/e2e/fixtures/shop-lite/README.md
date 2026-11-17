# shop-lite

Cart pricing in whole cents, with a small command line that quotes a total.

## Usage

```bash
python3 -m shop quote 1999x2 500x1
python3 -m shop quote 2000x3 --discount 10
```

- `quote ITEM... [--discount PERCENT]` prints the order total. `ITEM` is `UNIT_PRICE_CENTSxQUANTITY`.
- `PERCENT` is a whole number from 0 to 100. The discount is rounded down to whole cents.
- Shipping is 5.00 unless the discounted amount reaches 50.00, and it is decided after the discount.
- A failing command prints the reason on stderr and exits with 1.

## Development

```bash
python3 -m pytest -q
```

Contribution rules are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
