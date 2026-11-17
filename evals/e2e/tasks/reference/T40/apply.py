import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/db.py", '    "CREATE TABLE IF NOT EXISTS lines',
        '    "CREATE UNIQUE INDEX IF NOT EXISTS orders_order_id ON orders (order_id)",\n    "CREATE TABLE IF NOT EXISTS lines')
replace(repo, "orders/service.py", "import sqlite3\nfrom datetime", "import csv\nimport sqlite3\nfrom datetime")
replace(repo, "orders/service.py", "    def get_order(self, order_id: str) -> dict:\n",
        '''    def import_orders(self, path: str) -> int:
        """Import the orders of a CSV file once each, however often or at the same time the file is imported."""
        with open(path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        added = 0
        with self.conn:
            for row in rows:
                inserted = self.conn.execute("INSERT OR IGNORE INTO orders VALUES (?, ?, 'placed', ?, 0)",
                                             (row["order_id"], row["customer_id"], row["placed_at"])).rowcount
                if inserted:
                    self.conn.execute("INSERT INTO lines VALUES (?, ?, ?, ?)", (row["order_id"], row["sku"],
                                      int(row["unit_price_cents"]), int(row["quantity"])))
                    added += inserted
        return added

    def get_order(self, order_id: str) -> dict:
''')
replace(repo, "orders/cli.py", '    commands.add_parser("list", help="print one row per order")\n',
        '    commands.add_parser("list", help="print one row per order")\n    commands.add_parser("import", help="import orders from a CSV file").add_argument("file")\n')
replace(repo, "orders/cli.py", '        elif args.command == "report":\n',
        '        elif args.command == "import":\n            print(f"imported {service.import_orders(args.file)} new orders", file=out)\n        elif args.command == "report":\n')
replace(repo, "README.md", "- `list` prints one row per order",
        "- `import FILE.csv` imports orders (`order_id,customer_id,placed_at,sku,unit_price_cents,quantity`, one line per order). An order id that exists is skipped, so repeated or simultaneous imports leave one copy.\n- `list` prints one row per order")
append(repo, "tests/test_cli.py", '''

def test_importing_the_same_file_twice_stores_each_order_once(conn, tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text("order_id,customer_id,placed_at,sku,unit_price_cents,quantity\\n"
                      "ord-1001,c-1,2026-02-01T10:00:00,tea,450,2\\n", encoding="utf-8")
    assert run("import", str(source))[1] == "imported 1 new orders\\n"
    assert run("import", str(source))[1] == "imported 0 new orders\\n"
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
''')
