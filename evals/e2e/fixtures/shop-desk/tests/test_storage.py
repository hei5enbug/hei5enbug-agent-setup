import json

import pytest

from shop.storage import StorageClient, StorageError


def test_upload_writes_the_named_file(tmp_path):
    StorageClient(tmp_path / "bucket").upload("a.json", b"[]")
    assert json.loads((tmp_path / "bucket" / "a.json").read_text()) == []


def test_an_upload_that_cannot_be_written_raises_storage_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(StorageError):
        StorageClient(blocker / "bucket").upload("a.json", b"[]")
