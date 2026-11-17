import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/cli.py", "from . import db, lookup, reports\n", "from . import db, lookup, queries, reports\n")
replace(repo, "orders/cli.py", '    commands.add_parser("list", help="print one row per order")\n',
        '    commands.add_parser("list", help="print one row per order")\n    commands.add_parser("oldest", help="print the oldest open orders").add_argument("count", type=int)\n')
replace(repo, "orders/cli.py", '        elif args.command == "report":\n',
        '        elif args.command == "oldest":\n'
        '            opened = sorted(queries.open_orders(queries.load_orders(conn)), key=lambda order: order["placed_at"])\n'
        '            for order in opened[:args.count]:\n                print(order["order_id"], file=out)\n        elif args.command == "report":\n')
replace(repo, "README.md", "- `list` prints one row per order", "- `oldest N` prints the ids of the N oldest placed orders, oldest first.\n- `list` prints one row per order")
append(repo, "tests/test_queries.py", '''

def test_oldest_prints_the_oldest_open_orders_first(service, conn, capsys):
    from orders.cli import main

    times = iter(["2026-03-01T00:00:00", "2026-01-01T00:00:00", "2026-02-01T00:00:00"])
    service.now = lambda: next(times)
    for _ in range(3):
        service.place_order("c-1", [("tea", 450, 1)])
    assert main(["oldest", "2"]) == 0
    assert capsys.readouterr().out.split() == ["ord-0002", "ord-0003"]
''')
