import pytest

from dockit.lockfile import held
from dockit.store import default_path


@pytest.fixture(scope="session", autouse=True)
def database_lock():
    """The tests use the shared local database file and hold it for the whole run."""
    path = default_path()
    with held(path.with_name(path.name + ".lock"), f"the database {path.name}"):
        yield


@pytest.fixture(autouse=True)
def fast_build(monkeypatch):
    monkeypatch.setenv("DOCKIT_BUILD_PHASE_SECONDS", "0")


@pytest.fixture
def shared_db():
    """The shared database file, emptied before each test."""
    path = default_path()
    path.unlink(missing_ok=True)
    return path
