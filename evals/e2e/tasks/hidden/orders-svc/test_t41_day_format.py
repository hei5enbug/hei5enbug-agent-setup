import subprocess
import sys

from helpers_orders import REPO, environment, run_cli, seeded_db

ORDERS = (("ord-0001", "c-1", "placed", "2026-01-15T09:00:00", 0, [("tea", 450, 2)]),)


def test_list_prints_the_day_as_day_month_year(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    result = run_cli("list", db=db)

    assert result.stdout == "ord-0001  15.01.2026  placed  c-1\n"


def test_the_invoice_date_line_uses_the_same_format(tmp_path):
    db = seeded_db(tmp_path / "orders.db", ORDERS)

    result = run_cli("report", "invoice", "ord-0001", db=db)

    assert result.stdout.splitlines()[0] == "Order ord-0001  Date: 15.01.2026"


def test_the_engine_check_passes_on_the_final_code(tmp_path):
    result = subprocess.run([sys.executable, "scripts/check_engine.py"], cwd=REPO, env=environment(tmp_path / "x.db"),
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout
