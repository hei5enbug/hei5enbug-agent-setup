import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/reports.py", "    return list(totals.items())\n", "    return sorted(totals.items(), key=lambda pair: -pair[1])\n")
replace(repo, "shop/cli.py", '    price = commands.add_parser("price"', '    top = commands.add_parser("top-customers", help="customers by spend")\n    top.add_argument("--limit", type=int, default=3)\n    price = commands.add_parser("price"')
replace(repo, "shop/cli.py", "from . import catalog, orders, reports\n", "from . import catalog, orders, reports, store\n")
replace(repo, "shop/cli.py", '    elif args.command == "price":', '    elif args.command == "top-customers":\n        for customer_id, spent in reports.customers_by_spend(store.load(args.store)["orders"])[: args.limit]:\n'
        '            print(f"customer {customer_id}: {format_cents(spent)}", file=out)\n    elif args.command == "price":')
append(repo, "tests/test_cli.py", '''

def test_top_customers_lists_the_biggest_spender_first(data_file):
    run("--store", str(data_file), "place", "2", "AB-100:2")
    run("--store", str(data_file), "place", "3", "AB-100:8")
    assert run("--store", str(data_file), "top-customers", "--limit", "1")[1] == "customer 3: 95.00\\n"
''')
replace(repo, "README.md", "- `price SKU` prints", "- `top-customers [--limit N]` prints the customers with the largest net spend first, three by default.\n- `price SKU` prints")
replace(repo, "docs/ko/README.ko.md", "- `price SKU`는", "- `top-customers [--limit N]`는 순지출이 큰 고객부터 출력하며 기본은 세 명입니다.\n- `price SKU`는")
