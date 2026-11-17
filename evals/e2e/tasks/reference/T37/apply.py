import sys

from patch_tools import replace

repo = sys.argv[1]
replace(repo, "orders/lookup.py", "import json\nimport sqlite3\nfrom pathlib import Path\n\n\ndef find_customer(conn: sqlite3.Connection, customer_id: str) -> tuple[str, str] | None:\n    \"\"\"The (name, tier) of a customer, or None when the customer is unknown.\"\"\"\n",
        'import json\nimport sqlite3\nfrom dataclasses import dataclass\nfrom pathlib import Path\n\n\n@dataclass(frozen=True)\nclass Customer:\n    customer_id: str\n    name: str\n    tier: str\n\n\ndef find_customer(conn: sqlite3.Connection, customer_id: str) -> Customer | None:\n    """The customer, or None when the customer is unknown."""\n')
replace(repo, "orders/lookup.py", '    row = conn.execute("SELECT name, tier FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()\n    return None if row is None else (row["name"], row["tier"])\n',
        '    row = conn.execute("SELECT customer_id, name, tier FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()\n    return None if row is None else Customer(row["customer_id"], row["name"], row["tier"])\n')
replace(repo, "orders/lookup.py", "list(find_customer(conn, cid))", "[find_customer(conn, cid).name, find_customer(conn, cid).tier]")
replace(repo, "orders/lookup.py", "def load_snapshot(path: str | Path) -> dict[str, tuple[str, str]]:", "def load_snapshot(path: str | Path) -> dict[str, Customer]:")
replace(repo, "orders/lookup.py", "    return {cid: (name, tier) for cid, (name, tier) in raw.items()}\n",
        "    return {cid: Customer(cid, name, tier) for cid, (name, tier) in raw.items()}\n")
replace(repo, "orders/billing.py", "    name, tier = found\n    return f\"{name} ({tier})\"\n", "    return f\"{found.name} ({found.tier})\"\n")
replace(repo, "orders/cli.py", "            name, tier = found\n            print(f\"{name} ({tier})\", file=out)\n", "            print(f\"{found.name} ({found.tier})\", file=out)\n")
