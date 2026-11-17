import pytest

from timesheet import store


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMESHEET_HOME", str(tmp_path))
    store.clear_cache()
    yield tmp_path
    store.clear_cache()
