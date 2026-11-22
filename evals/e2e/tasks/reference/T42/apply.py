import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/reports.py", "def sales_report(", "def tax_cents(net: int) -> int:\n    \"\"\"The tax on a net amount at the configured rate, cents below one dropped.\"\"\"\n"
        "    return net * settings.get(\"tax_percent\") // 100\n\n\ndef sales_report(")
replace(repo, "shop/reports.py", 'row["tax_cents"] = row["net_cents"] * settings.get("tax_percent") // 100', 'row["tax_cents"] = tax_cents(row["net_cents"])')
append(repo, "shop/reports.py", '''

def statement(path: str | os.PathLike[str], customer_id: int) -> list[dict]:
    """One row per order of the customer: net amount, tax, and total."""
    customers.lookup_customer(path, customer_id)
    rows = []
    for order in store.load(path)["orders"]:
        if order["customer_id"] == customer_id:
            net = net_cents(order)
            rows.append({"order_id": order["id"], "net_cents": net, "tax_cents": tax_cents(net), "total_cents": net + tax_cents(net)})
    return rows
''')
replace(repo, "shop/reports.py", "from . import settings, store\n", "from . import customers, settings, store\n")
replace(repo, "shop/cli.py", '    price = commands.add_parser("price"', '    statement = commands.add_parser("statement", help="orders of a customer with tax")\n    statement.add_argument("customer_id", type=int)\n    price = commands.add_parser("price"')
replace(repo, "shop/cli.py", '    elif args.command == "price":', '    elif args.command == "statement":\n        for row in reports.statement(args.store, args.customer_id):\n'
        '            print(f"order {row[\'order_id\']}: net {format_cents(row[\'net_cents\'])} tax {format_cents(row[\'tax_cents\'])} "\n'
        '                  f"total {format_cents(row[\'total_cents\'])}", file=out)\n    elif args.command == "price":')
append(repo, "tests/test_cli.py", '''

def test_statement_prints_each_order_with_tax(data_file):
    run("--store", str(data_file), "place", "2", "AB-100:4")
    assert run("--store", str(data_file), "statement", "2")[1] == "order 1: net 50.00 tax 4.00 total 54.00\\n"
''')
replace(repo, "README.md", "- `price SKU` prints", "- `statement CUSTOMER_ID` prints one line per order of the customer with its net amount, tax, and total, taxed at the\n  same rate as `sales`.\n- `price SKU` prints")
replace(repo, "docs/ko/README.ko.md", "- `price SKU`는", "- `statement CUSTOMER_ID`는 고객의 주문마다 순금액, 세금, 합계를 한 줄로 출력하며, `sales`와 같은 세율로 세금을\n  계산합니다.\n- `price SKU`는")
