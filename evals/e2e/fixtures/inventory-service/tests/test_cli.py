import io

from inventory.cli import main


def run(*argv, data):
    out, err = io.StringIO(), io.StringIO()
    code = main(["--data", str(data), *argv], environ={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def seed(data):
    for argv in (
        ["warehouse", "add", "MAIN", "Main warehouse", "--priority", "10"],
        ["warehouse", "add", "EAST", "East depot", "--priority", "20"],
        ["item", "add", "WIDGET", "Widget", "40.00", "--category", "hardware"],
        ["item", "add", "BOLT", "Bolt", "0.40", "--category", "parts"],
        ["stock", "receive", "MAIN", "WIDGET", "6"],
        ["stock", "receive", "EAST", "BOLT", "100"],
    ):
        assert run(*argv, data=data)[0] == 0


def test_item_and_warehouse_listing(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    code, out, _ = run("item", "list", data=data)
    assert code == 0 and "WIDGET" in out and "40.00" in out
    code, out, _ = run("warehouse", "list", data=data)
    assert out.splitlines()[2].startswith("MAIN")


def test_order_flow_creates_ships_and_cancels(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    code, out, _ = run("order", "create", "--customer", "kim@example.com", "--line", "WIDGET=3", data=data)
    assert code == 0 and "Created order #1, total 129.60" in out
    code, out, _ = run("order", "show", "1", data=data)
    assert "Customer: kim@example.com" in out and "[MAIN:3]" in out
    assert run("order", "cancel", "1", data=data)[1].strip() == "Order #1 cancelled"
    assert run("order", "ship", "1", data=data)[0] == 2


def test_errors_are_reported_with_exit_code_two(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    code, out, err = run("order", "create", "--customer", "kim@example.com", "--line", "WIDGET=99", data=data)
    assert code == 2 and out == "" and "insufficient stock for WIDGET" in err
    code, _, err = run("order", "create", "--customer", "kim@example.com", "--line", "WIDGET", data=data)
    assert code == 2 and "SKU=QTY" in err


def test_report_prints_the_three_sections(tmp_path):
    data = tmp_path / "d.json"
    seed(data)
    run("order", "create", "--customer", "kim@example.com", "--line", "WIDGET=4", data=data)
    code, out, _ = run("report", data=data)
    assert code == 0
    assert "Valuation by warehouse:" in out and "MAIN: 80.00" in out and "EAST: 40.00" in out
    assert "Low stock (below 5):" in out and "WIDGET  Widget  qty 2" in out
    assert "placed: 1" in out
