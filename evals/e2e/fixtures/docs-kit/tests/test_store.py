from dockit.store import Store


def test_migrate_applies_each_migration_once(shared_db):
    store = Store(shared_db)
    assert "create-visits" in store.migrate()
    assert store.migrate() == []


def test_visits_count_up_per_page(shared_db):
    store = Store.open(shared_db)
    assert store.record_visit("guide") == 1
    assert store.record_visit("guide") == 2
    store.record_visit("index")
    assert store.visit_counts() == {"guide": 2, "index": 1}
