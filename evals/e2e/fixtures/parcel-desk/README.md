# parcel-desk

Shipping quotes for parcels. A quote is a base fee by billed weight and zone, a fuel surcharge, and optional insurance.

## Usage

```bash
python3 -m parcel quote --weight 1180 --zone B
python3 -m parcel quote --weight 2500 --zone A --declared 20000
```

- `quote --weight GRAMS --zone ZONE [--declared CENTS]` prints the label and the quote in cents.
- Weight is billed in 500 g steps, rounded up. The base fee is the billed weight times the zone rate per 500 g.
- The fuel surcharge is 8% of the base fee. Insurance is 1% of the declared value, at least 50 cents, and 0 when
  nothing is declared.
- A failing command prints the reason on stderr and exits with 2.

## Development

```bash
python3 -m pytest -q
```

Contribution rules are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
