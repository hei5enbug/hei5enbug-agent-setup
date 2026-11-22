import io
import json
from datetime import date

import pytest

from shop.cli import main
from shop.orders import place_order
from shop.storage import StorageClient, StorageError

DAY = date(2026, 3, 2)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    try:
        code = main(list(argv), stdout=out, stderr=err)
    except Exception as exc:  # a failure that surfaces as an exception is a failure that is reported
        return exc, out.getvalue(), err.getvalue()
    return code, out.getvalue(), err.getvalue()


def test_the_export_uploads_every_order_and_says_how_many(data_file, tmp_path):
    place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)
    place_order(data_file, 2, [("CD-200", 1)], placed_on=DAY)
    code, out, _ = run("--store", str(data_file), "export-orders", "--to", str(tmp_path / "bucket"))
    exported = json.loads((tmp_path / "bucket" / "orders.json").read_text(encoding="utf-8"))
    assert (code, out) == (0, "exported 2 orders\n")
    assert [order["id"] for order in exported] == [1, 2]


@pytest.mark.parametrize("failure", [StorageError("disk full"), OSError("quota exceeded"), RuntimeError("timeout")])
def test_a_failed_upload_ends_the_command_and_is_reported(data_file, tmp_path, monkeypatch, failure):
    place_order(data_file, 1, [("AB-100", 4)], placed_on=DAY)

    def refuse(self, name, data):
        raise failure

    monkeypatch.setattr(StorageClient, "upload", refuse)
    code, out, err = run("--store", str(data_file), "export-orders", "--to", str(tmp_path / "bucket"))
    assert "exported" not in out
    if isinstance(code, Exception):
        assert code is failure
    else:
        assert code != 0
        assert str(failure) in err
