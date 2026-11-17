from dockit.features import visits
from dockit.store import Store


def test_migrate_applies_each_migration_once(shared_db):
    store = Store(shared_db)
    assert "create-visits" in store.migrate()
    assert store.migrate() == []


def test_visits_count_up_per_page(shared_db):
    store = Store.open(shared_db)
    assert visits.record_visit(store, "guide") == 1
    assert visits.record_visit(store, "guide") == 2
    visits.record_visit(store, "index")
    assert visits.visit_counts(store) == {"guide": 2, "index": 1}
