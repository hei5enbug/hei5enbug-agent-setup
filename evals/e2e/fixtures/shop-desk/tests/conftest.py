import pytest

from shop import store


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "shop-data.json"
    data = store.load(path)
    data["customers"] = {
        "1": {"name": "Ada Lovelace", "tier": "gold"},
        "2": {"name": "Brian Kernighan", "tier": "basic"},
        "3": {"name": "Carol Shaw", "tier": "silver"},
    }
    store.save(path, data)
    return path
