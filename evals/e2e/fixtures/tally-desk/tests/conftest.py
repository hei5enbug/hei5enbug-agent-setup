import pytest

from tally import rates


@pytest.fixture(autouse=True)
def fresh_rate_cache():
    rates.rate_for.cache_clear()
    yield
    rates.rate_for.cache_clear()
