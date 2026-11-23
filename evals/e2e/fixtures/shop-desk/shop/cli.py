"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Sequence, TextIO

from . import catalog, orders, reports
from .customers import lookup_customer
from .dates import week_label
from .errors import ShopError
from .money import format_cents

EXIT_USER_ERROR = 2
DEFAULT_STORE = "shop-data.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shop", description="Order desk for a small shop")
    parser.add_argument("--store", default=os.environ.get("SHOP_STORE", DEFAULT_STORE), help="data file")
    commands = parser.add_subparsers(dest="command", required=True)
    place = commands.add_parser("place", help="place an order")
    place.add_argument("customer_id", type=int)
    place.add_argument("lines", help="SKU:QTY[,SKU:QTY...]")
    lookup = commands.add_parser("lookup", help="show a customer")
    lookup.add_argument("customer_id", type=int)
    commands.add_parser("sales", help="sales report")
    price = commands.add_parser("price", help="show a unit price")
    price.add_argument("sku")
    week = commands.add_parser("week", help="week label of a day")
    week.add_argument("day", help="YYYY-MM-DD")
    return parser


def run(args: argparse.Namespace, out: TextIO) -> None:
    if args.command == "place":
        order = orders.place_order(args.store, args.customer_id, orders.parse_lines(args.lines))
        total = order["subtotal_cents"] - order["discount_cents"]
        print(f"order {order['id']}: subtotal {format_cents(order['subtotal_cents'])} "
              f"discount {format_cents(order['discount_cents'])} total {format_cents(total)}", file=out)
    elif args.command == "lookup":
        customer = lookup_customer(args.store, args.customer_id)
        print(f"{customer['name']} ({customer['tier']})", file=out)
    elif args.command == "sales":
        for row in reports.sales_report(args.store):
            print(f"customer {row['customer_id']}: orders {row['orders']} net {format_cents(row['net_cents'])} "
                  f"tax {format_cents(row['tax_cents'])}", file=out)
    elif args.command == "price":
        print(format_cents(catalog.price_cents(args.sku)), file=out)
    elif args.command == "week":
        print(week_label(date.fromisoformat(args.day)), file=out)


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    try:
        run(args, out)
    except ShopError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USER_ERROR
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
