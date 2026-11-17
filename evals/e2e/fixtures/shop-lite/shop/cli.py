"""Command line interface: `python3 -m shop quote ITEM... [--discount PERCENT]`."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, TextIO

from .cart import Cart
from .errors import InvalidItem, ShopError
from .formatting import format_cents


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shop", description="Cart pricing in whole cents")
    commands = parser.add_subparsers(dest="command", required=True)
    quote = commands.add_parser("quote", help="print the total of the items")
    quote.add_argument("items", nargs="+", metavar="ITEM", help="UNIT_PRICE_CENTSxQUANTITY, for example 1999x2")
    quote.add_argument("--discount", type=int, default=0, metavar="PERCENT", help="whole-number percent off")
    return parser


def parse_item(text: str) -> tuple[int, int]:
    price, separator, quantity = text.partition("x")
    if not separator or not price.isdigit() or not quantity.isdigit():
        raise InvalidItem(f"item must look like 1999x2, got {text!r}")
    return int(price), int(quantity)


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    try:
        cart = Cart()
        for index, text in enumerate(args.items):
            price, quantity = parse_item(text)
            cart.add(f"item-{index}", price, quantity)
        print(f"Total: {format_cents(cart.total(args.discount))}", file=out)
    except (ShopError, ValueError) as exc:
        print(f"error: {exc}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
