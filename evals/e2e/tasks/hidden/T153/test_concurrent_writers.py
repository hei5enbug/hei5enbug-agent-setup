import json
import math
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from inventory.app import create_app, transaction
from inventory.config import Config
from inventory.errors import ConfigError, InventoryError, LockTimeout

REPO = Path(__file__).resolve().parents[2]
HOLDER = """
import sys, time
from pathlib import Path
from inventory.app import transaction
data, ready, go = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
with transaction(data) as app:
    ready.write_text("ready")
    deadline = time.monotonic() + 30
    while not go.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    app.stock.receive("MAIN", "WIDGET", 1)
"""
WRITE_COMMANDS = [
    ["item", "add", "NEWBIE", "New item", "1.00"],
    ["warehouse", "add", "WEST", "West depot"],
    ["stock", "receive", "MAIN", "WIDGET", "1"],
    ["stock", "adjust", "MAIN", "WIDGET", "3"],
    ["order", "create", "--customer", "kim@example.com", "--line", "WIDGET=1"],
    ["order", "ship", "1"],
    ["order", "cancel", "1"],
    ["import", "items", "{csv}"],
    ["import", "stock", "{csv}"],
]
READ_COMMANDS = [
    ["item", "list"],
    ["warehouse", "list"],
    ["stock", "show", "MAIN"],
    ["order", "show", "1"],
    ["order", "list"],
    ["report"],
]


def seed(path, stock=5, with_order=False):
    app = create_app(path, Config(tax_rate=Decimal("0.10")))
    app.warehouses.add_warehouse("MAIN", "Main warehouse", priority=10)
    app.catalog.add_item("WIDGET", "Widget", Decimal("10.00"))
    app.stock.receive("MAIN", "WIDGET", stock)
    if with_order:
        app.orders.create_order("seed@example.com", [("WIDGET", 1)])
    app.save()


def environment(**extra):
    env = {key: value for key, value in os.environ.items() if not key.startswith("INVENTORY_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra)
    return env


def start_cli(path, *args, **env):
    return subprocess.Popen(
        [sys.executable, "-m", "inventory", "--data", str(path), *args],
        cwd=REPO, env=environment(**env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def run_cli(path, *args, **env):
    process = start_cli(path, *args, **env)
    out, err = process.communicate(timeout=60)
    return process.returncode, out, err


class Holder:
    """A child process that holds the transaction lock until released, then receives one more widget."""

    def __init__(self, path, tmp_path):
        self.ready = tmp_path / "holder-ready"
        self.go = tmp_path / "holder-go"
        self.process = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(path), str(self.ready), str(self.go)],
            cwd=REPO, env=environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        deadline = time.monotonic() + 30
        while not self.ready.exists():
            if self.process.poll() is not None or time.monotonic() > deadline:
                self.process.kill()
                raise AssertionError(f"holder did not start: {self.process.communicate()}")
            time.sleep(0.02)

    def release(self):
        self.go.write_text("go")
        out, err = self.process.communicate(timeout=60)
        assert self.process.returncode == 0, err


@pytest.fixture
def data(tmp_path):
    path = tmp_path / "inventory.json"
    seed(path)
    return path


def test_transaction_saves_on_normal_exit(data):
    with transaction(data) as app:
        app.stock.receive("MAIN", "WIDGET", 4)
    assert create_app(data).stock.total("WIDGET") == 9


def test_transaction_does_not_save_when_the_block_raises(data):
    with pytest.raises(RuntimeError, match="boom"):
        with transaction(data) as app:
            app.stock.receive("MAIN", "WIDGET", 4)
            raise RuntimeError("boom")
    assert create_app(data).stock.total("WIDGET") == 5
    with transaction(data, Config(lock_timeout=0)) as app:
        assert app.stock.total("WIDGET") == 5


def test_transaction_uses_the_configured_data_file_by_default(tmp_path):
    path = tmp_path / "configured.json"
    seed(path)
    with transaction(config=Config(data_file=str(path))) as app:
        app.stock.receive("MAIN", "WIDGET", 2)
    assert create_app(path).stock.total("WIDGET") == 7


def test_lock_file_sits_next_to_the_data_file_and_no_temp_file_is_left(data):
    holder = Holder(data, data.parent)
    try:
        assert Path(str(data) + ".lock").exists()
    finally:
        holder.release()
    assert json.loads(data.read_text(encoding="utf-8"))
    assert list(data.parent.glob(".inventory-*.tmp")) == []


def test_a_waiting_writer_sees_the_change_made_while_it_waited(data, tmp_path):
    holder = Holder(data, tmp_path)
    waiter = start_cli(data, "stock", "receive", "MAIN", "WIDGET", "1")
    time.sleep(0.6)
    assert waiter.poll() is None, "the second writer must wait for the lock"
    holder.release()
    out, err = waiter.communicate(timeout=60)
    assert waiter.returncode == 0, err
    assert create_app(data).stock.total("WIDGET") == 7


def test_transaction_times_out_with_lock_timeout_naming_the_data_file(data, tmp_path):
    holder = Holder(data, tmp_path)
    try:
        started = time.monotonic()
        with pytest.raises(LockTimeout) as caught:
            with transaction(data, Config(lock_timeout=0.4)):
                pytest.fail("the lock is held by another process")
        elapsed = time.monotonic() - started
        assert 0.3 <= elapsed < 5
        assert str(data) in str(caught.value)
        assert isinstance(caught.value, InventoryError)
        started = time.monotonic()
        with pytest.raises(LockTimeout):
            with transaction(data, Config(lock_timeout=0)):
                pytest.fail("the lock is held by another process")
        assert time.monotonic() - started < 1
    finally:
        holder.release()


@pytest.mark.parametrize("command", WRITE_COMMANDS, ids=lambda command: " ".join(command[:2]))
def test_every_write_command_fails_with_exit_2_while_the_lock_is_held(tmp_path, command):
    path = tmp_path / "inventory.json"
    seed(path, with_order=True)
    csv = tmp_path / "rows.csv"
    csv.write_text("sku,name,price\nCSVITEM,Csv item,2.00\n", encoding="utf-8")
    holder = Holder(path, tmp_path)
    try:
        arguments = [argument.replace("{csv}", str(csv)) for argument in command]
        code, out, err = run_cli(path, *arguments, INVENTORY_LOCK_TIMEOUT="0.3")
    finally:
        holder.release()
    assert code == 2, (out, err)
    assert err.startswith("error:") and str(path) in err
    state = create_app(path)
    assert state.stock.total("WIDGET") == 5
    assert "NEWBIE" not in state.db.items and "CSVITEM" not in state.db.items and "WEST" not in state.db.warehouses


@pytest.mark.parametrize("command", READ_COMMANDS, ids=lambda command: " ".join(command[:2]))
def test_read_commands_do_not_wait_for_the_lock(tmp_path, command):
    path = tmp_path / "inventory.json"
    seed(path, with_order=True)
    holder = Holder(path, tmp_path)
    try:
        started = time.monotonic()
        code, out, err = run_cli(path, *command, INVENTORY_LOCK_TIMEOUT="0")
        elapsed = time.monotonic() - started
    finally:
        holder.release()
    assert code == 0, err
    assert elapsed < 20


def test_concurrent_order_creation_never_oversells(tmp_path):
    path = tmp_path / "inventory.json"
    seed(path, stock=5)
    processes = [
        start_cli(path, "order", "create", "--customer", f"c{index}@example.com", "--line", "WIDGET=1")
        for index in range(12)
    ]
    outcomes = [(process, *process.communicate(timeout=120)) for process in processes]
    succeeded = [item for item in outcomes if item[0].returncode == 0]
    rejected = [item for item in outcomes if item[0].returncode == 2]
    assert len(succeeded) == 5 and len(rejected) == 7, [(p.returncode, err) for p, _, err in outcomes]
    assert all("insufficient stock" in err for _, _, err in rejected)
    final = create_app(path)
    assert final.stock.total("WIDGET") == 0
    assert sorted(final.db.orders) == [1, 2, 3, 4, 5]
    assert final.db.next_order_id == 6
    assert len({order.customer for order in final.db.orders.values()}) == 5


def test_concurrent_receives_lose_no_update(tmp_path):
    path = tmp_path / "inventory.json"
    seed(path, stock=1)
    processes = [start_cli(path, "stock", "receive", "MAIN", "WIDGET", "1") for _ in range(10)]
    for process in processes:
        process.communicate(timeout=120)
    assert [process.returncode for process in processes] == [0] * 10
    assert create_app(path).stock.total("WIDGET") == 11


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 10.0), ("", 10.0), ("2.5", 2.5), (" 7 ", 7.0), ("0", 0.0)],
)
def test_config_reads_the_lock_timeout(raw, expected):
    environ = {} if raw is None else {"INVENTORY_LOCK_TIMEOUT": raw}
    value = Config.from_env(environ).lock_timeout
    assert isinstance(value, float) and value == expected


@pytest.mark.parametrize("raw", ["abc", "-1", "-0.5", "nan", "inf", "1e999"])
def test_config_rejects_an_unusable_lock_timeout(raw):
    with pytest.raises(ConfigError):
        Config.from_env({"INVENTORY_LOCK_TIMEOUT": raw})
    assert math.isfinite(Config().lock_timeout)


def test_readme_and_mirror_describe_the_lock_timeout():
    for relative in ("README.md", "docs/ko/README.ko.md"):
        assert "INVENTORY_LOCK_TIMEOUT" in (REPO / relative).read_text(encoding="utf-8"), relative
