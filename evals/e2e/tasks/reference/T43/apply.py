import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/cli.py", "from . import catalog, orders, reports\n", "import json\n\nfrom . import catalog, orders, reports, store\n")
replace(repo, "shop/cli.py", "from .money import format_cents\n", "from .money import format_cents\nfrom .storage import StorageClient, StorageError\n")
replace(repo, "shop/cli.py", '    price = commands.add_parser("price"', '    export = commands.add_parser("export-orders", help="upload every order to the storage")\n    export.add_argument("--to", required=True, help="storage directory")\n    price = commands.add_parser("price"')
replace(repo, "shop/cli.py", '    elif args.command == "price":', '    elif args.command == "export-orders":\n        rows = store.load(args.store)["orders"]\n'
        '        StorageClient(args.to).upload("orders.json", json.dumps(rows, indent=2).encode("utf-8"))\n'
        '        print(f"exported {len(rows)} orders", file=out)\n    elif args.command == "price":')
replace(repo, "shop/cli.py", "    except ShopError as exc:", "    except (ShopError, StorageError) as exc:")
append(repo, "tests/test_cli.py", '''

def test_export_orders_uploads_the_orders(data_file, tmp_path):
    run("--store", str(data_file), "place", "2", "AB-100:4")
    code, out, _ = run("--store", str(data_file), "export-orders", "--to", str(tmp_path / "bucket"))
    assert (code, out) == (0, "exported 1 orders\\n")
    assert (tmp_path / "bucket" / "orders.json").is_file()
''')
replace(repo, "README.md", "- `price SKU` prints", "- `export-orders --to DIR` uploads every stored order to the storage directory as `orders.json` and prints\n  `exported N orders`.\n- `price SKU` prints")
replace(repo, "docs/ko/README.ko.md", "- `price SKU`는", "- `export-orders --to DIR`는 저장된 모든 주문을 `orders.json`으로 저장소 디렉터리에 올리고 `exported N orders`를\n  출력합니다.\n- `price SKU`는")
