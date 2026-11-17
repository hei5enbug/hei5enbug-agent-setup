from timesheet.cache import TtlCache


def test_value_is_loaded_once_until_it_expires():
    now = [0.0]
    cache = TtlCache(ttl_seconds=10, clock=lambda: now[0])
    calls = []

    def loader():
        calls.append(1)
        return len(calls)

    assert cache.get_or_load("k", loader) == 1
    now[0] = 9.0
    assert cache.get_or_load("k", loader) == 1
    now[0] = 10.0
    assert cache.get_or_load("k", loader) == 2


def test_clear_forgets_every_value():
    cache = TtlCache(ttl_seconds=10)
    cache.get_or_load("k", lambda: 1)
    cache.clear()
    assert cache.get_or_load("k", lambda: 2) == 2
