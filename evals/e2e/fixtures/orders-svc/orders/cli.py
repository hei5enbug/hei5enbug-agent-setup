"""Command line interface: `python3 -m orders COMMAND ...`."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence, TextIO

from . import db, lookup, reports
from .dates import day_expression
from .errors import OrdersError
from .service import Line, OrderService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orders", description="A small order service")
    commands = parser.add_subparsers(dest="command", required=True)
    place = commands.add_parser("place", help="place an order and print its id")
    place.add_argument("customer")
    place.add_argument("lines", nargs="+", metavar="SKU:UNIT_PRICE_CENTS:QUANTITY")
    place.add_argument("--discount", type=int, default=0, metavar="PERCENT")
    for name in ("cancel", "ship"):
        commands.add_parser(name, help=f"{name} a placed order").add_argument("order")
    amend = commands.add_parser("amend", help="set the quantity of a line")
    amend.add_argument("order")
    amend.add_argument("sku")
    amend.add_argument("quantity", type=int)
    add_line = commands.add_parser("add-line", help="add a line to an order")
    add_line.add_argument("order")
    add_line.add_argument("sku")
    add_line.add_argument("quantity", type=int)
    add_line.add_argument("unit_price", type=int)
    commands.add_parser("list", help="print one row per order")
    report = commands.add_parser("report", help="print a report").add_subparsers(dest="kind", required=True)
    invoice = report.add_parser("invoice", help="print the invoice of an order")
    invoice.add_argument("order")
    invoice.add_argument("--bill-to", action="store_true")
    commands.add_parser("whoami", help="print the name and tier of a customer").add_argument("customer")
    return parser


def parse_line(text: str) -> Line:
    sku, price, quantity = text.split(":")
    return sku, int(price), int(quantity)


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    conn = db.connect()
    service = OrderService(conn)
    try:
        if args.command == "place":
            print(service.place_order(args.customer, [parse_line(text) for text in args.lines], args.discount), file=out)
        elif args.command == "cancel":
            service.cancel_order(args.order)
        elif args.command == "ship":
            service.ship_order(args.order)
        elif args.command == "amend":
            service.set_line(args.order, args.sku, args.quantity)
        elif args.command == "add-line":
            service.set_line(args.order, args.sku, args.quantity, args.unit_price)
        elif args.command == "list":
            for row in conn.execute(f"SELECT order_id, {day_expression('placed_at')} AS day, status, customer_id "
                                    "FROM orders ORDER BY rowid"):
                print(f"{row['order_id']}  {row['day']}  {row['status']}  {row['customer_id']}", file=out)
        elif args.command == "report":
            print(reports.invoice_text(conn, args.order, args.bill_to), file=out)
        elif args.command == "whoami":
            found = lookup.find_customer(conn, args.customer)
            if found is None:
                raise OrdersError(f"unknown customer {args.customer}")
            name, tier = found
            print(f"{name} ({tier})", file=out)
    except (OrdersError, ValueError) as exc:
        print(f"error: {exc}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
