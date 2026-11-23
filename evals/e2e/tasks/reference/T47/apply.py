import sys

from patch_tools import append, replace

repo = sys.argv[1]

replace(repo, "shop/store.py", "import json\nimport os\nfrom pathlib import Path\nfrom typing import Any\n",
        "import json\nimport os\nimport threading\nfrom contextlib import contextmanager\nfrom pathlib import Path\nfrom typing import Any, Iterator\n")
append(repo, "shop/store.py", '''

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def locked(path: str | os.PathLike[str]) -> Iterator[None]:
    """Hold the data file against other runs of this process while a read-modify-write is in progress."""
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        yield
''')
append(repo, "shop/orders.py", '''

def import_orders(path: str | os.PathLike[str], csv_path: str | os.PathLike[str]) -> int:
    """Store each CSV row that is not stored yet, one order per `ref`. Running it again adds nothing."""
    imported = 0
    with store.locked(path):
        known = {order["ref"] for order in store.load(path)["orders"] if order["ref"]}
        with open(csv_path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["ref"] in known:
                    continue
                place_order(path, int(row["customer_id"]), [(row["sku"], int(row["quantity"]))],
                            placed_on=date.fromisoformat(row["placed_on"]), ref=row["ref"])
                known.add(row["ref"])
                imported += 1
    return imported
''')
replace(repo, "shop/orders.py", "import os\nfrom datetime import date\n", "import csv\nimport os\nfrom datetime import date\n")
replace(repo, "shop/cli.py", '    price = commands.add_parser("price"', '    load = commands.add_parser("import-orders", help="import orders from a CSV file")\n    load.add_argument("file")\n    price = commands.add_parser("price"')
replace(repo, "shop/cli.py", '    elif args.command == "price":', '    elif args.command == "import-orders":\n        print(f"imported {orders.import_orders(args.store, args.file)}", file=out)\n    elif args.command == "price":')
append(repo, "tests/test_cli.py", '''

def test_import_orders_reads_a_csv_and_a_rerun_adds_nothing(data_file, tmp_path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("ref,customer_id,sku,quantity,placed_on\\nR-1,2,AB-100,2,2026-03-02\\n", encoding="utf-8")
    assert run("--store", str(data_file), "import-orders", str(csv_path))[1] == "imported 1\\n"
    assert run("--store", str(data_file), "import-orders", str(csv_path))[1] == "imported 0\\n"
''')
replace(repo, "README.md", "- `price SKU` prints", "- `import-orders FILE` stores the orders of a CSV file with the header `ref,customer_id,sku,quantity,placed_on` and prints\n  `imported N` for the orders it added. An order whose `ref` is already stored is skipped, so a rerun is safe.\n- `price SKU` prints")
replace(repo, "docs/ko/README.ko.md", "- `price SKU`는", "- `import-orders FILE`은 헤더가 `ref,customer_id,sku,quantity,placed_on`인 CSV 파일의 주문을 저장하고, 새로 추가한 주문 수를\n  `imported N`으로 출력합니다. `ref`가 이미 저장된 주문은 건너뛰므로 다시 실행해도 안전합니다.\n- `price SKU`는")
