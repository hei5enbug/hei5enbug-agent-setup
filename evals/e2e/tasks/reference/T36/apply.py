import sys

from patch_tools import append, replace

repo = sys.argv[1]
replace(repo, "orders/cli.py", "import argparse\nimport sys\n", "import argparse\nimport json\nimport sys\n")
replace(repo, "orders/cli.py", "from . import db, lookup, reports\n", "from . import db, lookup, queries, reports, storage\n")
replace(repo, "orders/cli.py", '    commands.add_parser("list", help="print one row per order")\n',
        '    commands.add_parser("list", help="print one row per order")\n    commands.add_parser("export", help="store every order as JSON")\n')
replace(repo, "orders/cli.py", '        elif args.command == "report":\n',
        '        elif args.command == "export":\n            orders = queries.load_orders(conn)\n'
        '            storage.default_client().put("orders.json", json.dumps(orders, indent=2).encode("utf-8"))\n'
        '            print(f"exported {len(orders)} orders", file=out)\n        elif args.command == "report":\n')
replace(repo, "orders/cli.py", "    except (OrdersError, ValueError) as exc:", "    except (OrdersError, ValueError, storage.StorageError) as exc:")
replace(repo, "README.md", "- `list` prints one row per order", "- `export` stores every order as a JSON list under the key `orders.json` of the storage client (`ORDERS_STORAGE_DIR`).\n- `list` prints one row per order")
append(repo, "tests/test_cli.py", '''

def test_export_stores_the_orders_and_reports_a_failing_client(conn, tmp_path, monkeypatch):
    run("place", "c-1", "tea:450:2")
    monkeypatch.setenv("ORDERS_STORAGE_DIR", str(tmp_path / "store"))
    assert run("export")[0] == 0 and (tmp_path / "store" / "orders.json").is_file()
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ORDERS_STORAGE_DIR", str(tmp_path / "blocker" / "store"))
    code, _, err = run("export")
    assert code == 1 and "cannot store orders.json" in err
''')
