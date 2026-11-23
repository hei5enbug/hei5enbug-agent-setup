"""Command line interface: `parcel quote --weight GRAMS --zone ZONE [--declared CENTS]`."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, TextIO

from .errors import ParcelError
from .labels import format_label, format_quote
from .models import Parcel
from .quote import build_quote

EXIT_USER_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parcel", description="Shipping quotes for parcels")
    commands = parser.add_subparsers(dest="command", required=True)
    quote = commands.add_parser("quote", help="quote one parcel")
    quote.add_argument("--weight", type=int, required=True, help="weight in grams")
    quote.add_argument("--zone", required=True)
    quote.add_argument("--declared", type=int, default=0, help="declared value in cents")
    return parser


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    parcel = Parcel(weight_grams=args.weight, zone=args.zone.upper(), declared_value_cents=args.declared)
    try:
        quote = build_quote(parcel)
        print(format_label(parcel), file=out)
        print(format_quote(quote), file=out)
    except ParcelError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USER_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
