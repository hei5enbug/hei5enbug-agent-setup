import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/reports.py", "def invoice_text(conn: sqlite3.Connection, order_id: str, bill: bool = False) -> str:\n    service = OrderService(conn)\n",
        '''def order_total_cents(service: OrderService, order_id: str) -> int:
    subtotal = sum(price * quantity for _, price, quantity in service.lines_of(order_id))
    discounted = subtotal - service.get_order(order_id)["discount_cents"]
    return discounted + tax_cents(discounted)


def customer_text(conn: sqlite3.Connection, customer_id: str) -> str:
    service = OrderService(conn)
    totals = [(order["order_id"], order_total_cents(service, order["order_id"])) for order in service.orders_of(customer_id)]
    rows = [f"{order_id}: {format_cents(total)}" for order_id, total in totals]
    return "\\n".join([*rows, f"Total: {format_cents(sum(total for _, total in totals))}"])


def invoice_text(conn: sqlite3.Connection, order_id: str, bill: bool = False) -> str:
    service = OrderService(conn)
''')
replace(repo, "orders/cli.py", '    invoice.add_argument("--bill-to", action="store_true")\n',
        '    invoice.add_argument("--bill-to", action="store_true")\n    report.add_parser("customer", help="print the orders of a customer with their totals").add_argument("customer")\n')
replace(repo, "orders/cli.py", "            print(reports.invoice_text(conn, args.order, args.bill_to), file=out)\n",
        "            if args.kind == \"invoice\":\n                print(reports.invoice_text(conn, args.order, args.bill_to), file=out)\n"
        "            else:\n                print(reports.customer_text(conn, args.customer), file=out)\n")
replace(repo, "README.md", "- `list` prints one row per order",
        "- `report customer CUSTOMER` prints each order of a customer with its total including tax, then `Total:`.\n- `list` prints one row per order")
append(repo, "tests/test_reports.py", '''

def test_the_customer_report_lists_each_order_with_tax_and_a_total(service, conn):
    service.place_order("c-1", [("tea", 1000, 10)])
    service.place_order("c-1", [("tea", 1000, 2)], discount_percent=10)
    assert reports.customer_text(conn, "c-1") == "ord-0001: $107.25\\nord-0002: $19.31\\nTotal: $126.56"
''')
