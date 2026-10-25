"""Command line interface: `python3 -m inventory [--data FILE] <command>`."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Mapping, Sequence, TextIO

from . import formatting, importer, reports
from .app import App, create_app
from .config import Config
from .errors import InventoryError, ValidationError
from .models import ORDER_STATUSES
from .money import format_money, parse_money

Handler = Callable[[App, argparse.Namespace, TextIO], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventory", description="Inventory and order management")
    parser.add_argument("--data", help="path of the JSON data file (default: $INVENTORY_DATA_FILE or inventory.json)")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_item_commands(commands)
    _add_warehouse_commands(commands)
    _add_stock_commands(commands)
    _add_order_commands(commands)
    _add_import_commands(commands)
    report = commands.add_parser("report", help="print valuation, low stock, and order counts")
    report.set_defaults(handler=cmd_report)
    return parser


def _add_item_commands(commands: argparse._SubParsersAction) -> None:
    item = commands.add_parser("item", help="manage the catalog").add_subparsers(dest="action", required=True)
    add = item.add_parser("add", help="add an item")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("price")
    add.add_argument("--category", default="general")
    add.set_defaults(handler=cmd_item_add)
    listing = item.add_parser("list", help="list active items")
    listing.add_argument("--category")
    listing.set_defaults(handler=cmd_item_list)


def _add_warehouse_commands(commands: argparse._SubParsersAction) -> None:
    group = commands.add_parser("warehouse", help="manage warehouses").add_subparsers(dest="action", required=True)
    add = group.add_parser("add", help="add a warehouse")
    add.add_argument("code")
    add.add_argument("name")
    add.add_argument("--priority", type=int, default=100)
    add.set_defaults(handler=cmd_warehouse_add)
    group.add_parser("list", help="list warehouses by priority").set_defaults(handler=cmd_warehouse_list)


def _add_stock_commands(commands: argparse._SubParsersAction) -> None:
    group = commands.add_parser("stock", help="receive and count stock").add_subparsers(dest="action", required=True)
    receive = group.add_parser("receive", help="add received units to a warehouse")
    receive.add_argument("warehouse")
    receive.add_argument("sku")
    receive.add_argument("quantity", type=int)
    receive.set_defaults(handler=cmd_stock_receive)
    adjust = group.add_parser("adjust", help="set the counted quantity")
    adjust.add_argument("warehouse")
    adjust.add_argument("sku")
    adjust.add_argument("quantity", type=int)
    adjust.set_defaults(handler=cmd_stock_adjust)
    show = group.add_parser("show", help="show the quantities in one warehouse")
    show.add_argument("warehouse")
    show.set_defaults(handler=cmd_stock_show)


def _add_order_commands(commands: argparse._SubParsersAction) -> None:
    group = commands.add_parser("order", help="place and manage orders").add_subparsers(dest="action", required=True)
    create = group.add_parser("create", help="place an order")
    create.add_argument("--customer", required=True)
    create.add_argument("--line", action="append", required=True, metavar="SKU=QTY")
    create.set_defaults(handler=cmd_order_create)
    show = group.add_parser("show", help="show one order")
    show.add_argument("order_id", type=int)
    show.set_defaults(handler=cmd_order_show)
    listing = group.add_parser("list", help="list orders")
    listing.add_argument("--status", choices=ORDER_STATUSES)
    listing.set_defaults(handler=cmd_order_list)
    for name, handler in (("ship", cmd_order_ship), ("cancel", cmd_order_cancel)):
        action = group.add_parser(name, help=f"{name} an order")
        action.add_argument("order_id", type=int)
        action.set_defaults(handler=handler)


def _add_import_commands(commands: argparse._SubParsersAction) -> None:
    group = commands.add_parser("import", help="import CSV files").add_subparsers(dest="action", required=True)
    for name, handler in (("items", cmd_import_items), ("stock", cmd_import_stock)):
        action = group.add_parser(name, help=f"import {name} from a CSV file")
        action.add_argument("path")
        action.set_defaults(handler=handler)


def parse_line(spec: str) -> tuple[str, int]:
    sku, separator, raw_quantity = spec.partition("=")
    if not separator:
        raise ValidationError(f"order line must look like SKU=QTY, got {spec!r}")
    try:
        return sku, int(raw_quantity)
    except ValueError:
        raise ValidationError(f"quantity is not a whole number: {raw_quantity!r}") from None


def cmd_item_add(app: App, args: argparse.Namespace, out: TextIO) -> None:
    item = app.catalog.add_item(args.sku, args.name, parse_money(args.price), args.category)
    app.save()
    print(f"Added item {item.sku} ({format_money(item.unit_price)})", file=out)


def cmd_item_list(app: App, args: argparse.Namespace, out: TextIO) -> None:
    print(formatting.render_items(app.catalog.list_items(category=args.category)), file=out)


def cmd_warehouse_add(app: App, args: argparse.Namespace, out: TextIO) -> None:
    warehouse = app.warehouses.add_warehouse(args.code, args.name, args.priority)
    app.save()
    print(f"Added warehouse {warehouse.code} (priority {warehouse.priority})", file=out)


def cmd_warehouse_list(app: App, args: argparse.Namespace, out: TextIO) -> None:
    print(formatting.render_warehouses(app.warehouses.list_warehouses()), file=out)


def cmd_stock_receive(app: App, args: argparse.Namespace, out: TextIO) -> None:
    app.catalog.get_item(args.sku)
    quantity = app.stock.receive(args.warehouse.upper(), args.sku, args.quantity)
    app.save()
    print(f"{args.warehouse.upper()} now holds {quantity} of {args.sku.upper()}", file=out)


def cmd_stock_adjust(app: App, args: argparse.Namespace, out: TextIO) -> None:
    delta = app.stock.adjust(args.warehouse.upper(), args.sku, args.quantity)
    app.save()
    print(f"Adjusted {args.sku.upper()} in {args.warehouse.upper()} by {delta:+d}", file=out)


def cmd_stock_show(app: App, args: argparse.Namespace, out: TextIO) -> None:
    levels = app.stock.levels(args.warehouse.upper())
    rows = [[sku, str(quantity)] for sku, quantity in sorted(levels.items())]
    print(formatting.render_table(["SKU", "QTY"], rows), file=out)


def cmd_order_create(app: App, args: argparse.Namespace, out: TextIO) -> None:
    order = app.orders.create_order(args.customer, [parse_line(spec) for spec in args.line])
    app.save()
    print(f"Created order #{order.id}, total {format_money(order.total)}", file=out)


def cmd_order_show(app: App, args: argparse.Namespace, out: TextIO) -> None:
    print(formatting.render_order(app.orders.get_order(args.order_id)), file=out)


def cmd_order_list(app: App, args: argparse.Namespace, out: TextIO) -> None:
    print(formatting.render_orders(app.orders.list_orders(args.status)), file=out)


def cmd_order_ship(app: App, args: argparse.Namespace, out: TextIO) -> None:
    order = app.orders.ship_order(args.order_id)
    app.save()
    print(f"Order #{order.id} shipped", file=out)


def cmd_order_cancel(app: App, args: argparse.Namespace, out: TextIO) -> None:
    order = app.orders.cancel_order(args.order_id)
    app.save()
    print(f"Order #{order.id} cancelled", file=out)


def cmd_import_items(app: App, args: argparse.Namespace, out: TextIO) -> None:
    report = importer.import_items_file(args.path, app.catalog)
    app.save()
    print(report.summary(), file=out)


def cmd_import_stock(app: App, args: argparse.Namespace, out: TextIO) -> None:
    report = importer.import_stock_file(args.path, app.stock)
    app.save()
    print(report.summary(), file=out)


def cmd_report(app: App, args: argparse.Namespace, out: TextIO) -> None:
    threshold = reports.LOW_STOCK_THRESHOLD
    sections = [
        formatting.render_valuation(reports.stock_valuation(app.db)),
        formatting.render_low_stock(reports.low_stock_items(app.db, threshold), threshold),
        formatting.render_order_counts(reports.order_counts(app.db)),
    ]
    print("\n\n".join(sections), file=out)


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(argv)
    try:
        app = create_app(args.data, Config.from_env(environ))
        args.handler(app, args, out)
    except InventoryError as exc:
        print(f"error: {exc}", file=err)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
