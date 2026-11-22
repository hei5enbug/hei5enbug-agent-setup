import io
import threading

from shop import store
from shop.cli import main

HEADER = "ref,customer_id,sku,quantity,placed_on\n"
ROWS = [f"R-{index},{1 + index % 3},AB-100,1,2026-03-02" for index in range(1, 7)]
PAUSE_SECONDS = 1.0


def csv_file(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text(HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")
    return path


def run_import(data_file, csv_path):
    main(["--store", str(data_file), "import-orders", str(csv_path)], stdout=io.StringIO(), stderr=io.StringIO())


def assert_each_order_once(data_file):
    orders = store.load(data_file)["orders"]
    assert sorted(order["ref"] for order in orders) == sorted(row.split(",")[0] for row in ROWS)
    assert len({order["id"] for order in orders}) == len(orders)


def test_a_second_run_that_starts_while_the_first_has_read_but_not_written_adds_no_duplicate(data_file, tmp_path, monkeypatch):
    """The first run is held right after its first read of the data file until the second run has finished."""
    csv_path = csv_file(tmp_path)
    real_load = store.load
    paused, release, first_read = threading.Event(), threading.Event(), threading.Lock()
    held = []

    def load(path):
        data = real_load(path)
        with first_read:
            hold = not held
            held.append(True)
        if hold:
            paused.set()
            release.wait(PAUSE_SECONDS)
        return data

    monkeypatch.setattr(store, "load", load)
    first = threading.Thread(target=run_import, args=(data_file, csv_path))
    first.start()
    assert paused.wait(5)
    second = threading.Thread(target=run_import, args=(data_file, csv_path))
    second.start()
    second.join(PAUSE_SECONDS + 5)
    release.set()
    first.join(PAUSE_SECONDS + 5)
    assert not first.is_alive() and not second.is_alive()
    assert_each_order_once(data_file)


def test_runs_that_start_together_add_no_duplicate(data_file, tmp_path):
    csv_path = csv_file(tmp_path)
    barrier = threading.Barrier(4)

    def start_together():
        barrier.wait(5)
        run_import(data_file, csv_path)

    threads = [threading.Thread(target=start_together) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads)
    assert_each_order_once(data_file)
