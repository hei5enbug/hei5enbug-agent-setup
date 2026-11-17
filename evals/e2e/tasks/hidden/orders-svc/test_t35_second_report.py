import re
import shutil

from helpers_orders import REPO, run_cli, seeded_db

RATE = "0.0725"
ORDERS = (
    ("ord-0001", "c-1", "placed", "2026-01-15T09:00:00", 0, [("tea", 1000, 10)]),
    ("ord-0002", "c-1", "placed", "2026-01-16T09:00:00", 400, [("mug", 2000, 2)]),
)


def rate_sites(root):
    found = []
    for path in sorted([*(root / "orders").rglob("*.py"), *(root / "config").glob("*.toml")]):
        count = path.read_text(encoding="utf-8").count(RATE)
        if count:
            found.append((path.relative_to(root).as_posix(), count))
    return found


def test_the_customer_report_lists_each_order_and_the_total_with_tax(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    result = run_cli("report", "customer", "c-1", db=db)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["ord-0001: $107.25", "ord-0002: $38.61", "Total: $145.86"]


def test_the_tax_rate_is_written_in_one_place():
    assert sum(count for _, count in rate_sites(REPO)) == 1, rate_sites(REPO)


def test_changing_the_one_existing_rate_changes_both_reports(tmp_path):
    work = tmp_path / "copy"
    shutil.copytree(REPO / "orders", work / "orders", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "config", work / "config")
    first = rate_sites(work)[0][0]
    target = work / first
    target.write_text(target.read_text(encoding="utf-8").replace(RATE, "0.1000", 1), encoding="utf-8")
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    invoice = run_cli("report", "invoice", "ord-0001", db=db, cwd=work)
    customer = run_cli("report", "customer", "c-1", db=db, cwd=work)

    assert "Tax: $10.00" in invoice.stdout
    assert customer.stdout.splitlines() == ["ord-0001: $110.00", "ord-0002: $39.60", "Total: $149.60"], re.sub(r"\s+", " ", customer.stderr)
