from helpers_orders import SETTINGS, rows, run_cli, seeded_db


def start(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text(SETTINGS.format(extra="max_total_cents_per_customer = 500\n"), encoding="utf-8")
    return seeded_db(tmp_path / "orders.db"), {"ORDERS_SETTINGS": str(settings)}


def place(db, env, customer, line, percent):
    return run_cli("place", customer, line, "--discount", str(percent), db=db, **env)


def order_count(db):
    return rows(db, "SELECT COUNT(*) FROM orders")[0][0]


def test_a_customer_can_reach_the_limit_but_not_pass_it(tmp_path):
    db, env = start(tmp_path)
    assert place(db, env, "c-1", "tea:1000:1", 10).returncode == 0
    assert place(db, env, "c-1", "tea:2000:2", 10).returncode == 0

    refused = place(db, env, "c-1", "tea:100:1", 10)

    assert refused.returncode == 1 and refused.stderr.strip()
    assert order_count(db) == 2


def test_the_limit_is_per_customer_and_leaves_undiscounted_orders_alone(tmp_path):
    db, env = start(tmp_path)
    assert place(db, env, "c-1", "tea:5000:1", 10).returncode == 0

    assert place(db, env, "c-2", "tea:5000:1", 10).returncode == 0
    assert place(db, env, "c-1", "tea:100:1", 0).returncode == 0
    assert order_count(db) == 3


def test_the_discount_of_a_cancelled_order_does_not_count(tmp_path):
    db, env = start(tmp_path)
    assert place(db, env, "c-1", "tea:1000:1", 10).returncode == 0
    assert place(db, env, "c-1", "tea:4000:1", 10).returncode == 0
    assert run_cli("cancel", "ord-0002", db=db, **env).returncode == 0

    assert place(db, env, "c-1", "tea:4000:1", 10).returncode == 0
