import json

from helpers_orders import run_cli, seeded_db

OLD_SNAPSHOT = {"c-1": ["Ada Lovelace", "gold"], "c-2": ["Alan Turing", "silver"]}
ORDERS = (("ord-0001", "c-1", "placed", "2026-01-15T09:00:00", 0, [("tea", 450, 2)]),)


def test_find_customer_returns_a_customer_and_none_for_an_unknown_one(tmp_path):
    from orders import db
    from orders.lookup import find_customer

    conn = db.connect(seeded_db(tmp_path / "orders.db"))

    found = find_customer(conn, "c-1")

    assert (found.customer_id, found.name, found.tier) == ("c-1", "Ada Lovelace", "gold")
    assert find_customer(conn, "c-9") is None


def test_whoami_and_the_invoice_bill_to_line_still_print_the_customer(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    whoami = run_cli("whoami", "c-1", db=db)
    invoice = run_cli("report", "invoice", "ord-0001", "--bill-to", db=db)

    assert (whoami.returncode, whoami.stdout) == (0, "Ada Lovelace (gold)\n"), whoami.stderr
    assert invoice.returncode == 0 and "Bill to: Ada Lovelace (gold)" in invoice.stdout, invoice.stderr


def test_a_snapshot_written_by_the_previous_version_still_loads(tmp_path):
    from orders.lookup import load_snapshot

    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(OLD_SNAPSHOT), encoding="utf-8")

    loaded = load_snapshot(path)

    assert {key: (value.name, value.tier) for key, value in loaded.items()} == {key: tuple(value) for key, value in OLD_SNAPSHOT.items()}
    assert loaded["c-1"].customer_id == "c-1"


def test_a_snapshot_saved_now_loads_back_the_same_customers(tmp_path):
    from orders import db
    from orders.lookup import find_customer, load_snapshot, save_snapshot

    conn = db.connect(seeded_db(tmp_path / "orders.db"))
    path = tmp_path / "snapshot.json"

    save_snapshot(conn, path)

    assert load_snapshot(path) == {cid: find_customer(conn, cid) for cid in ("c-1", "c-2")}
