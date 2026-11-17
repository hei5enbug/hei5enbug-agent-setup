import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from jobq import hook
from jobq.grants import GrantStore, GrantStoreError

ROOT = Path(__file__).resolve().parents[2]


def run_code(code, *arguments):
    return subprocess.Popen([sys.executable, "-B", "-c", code, *arguments], cwd=ROOT, stderr=subprocess.PIPE, text=True)


def finish(processes):
    for process in processes:
        _, error = process.communicate(timeout=120)
        assert process.returncode == 0, error


GRANT = "import sys\nfrom jobq.grants import GrantStore\nGrantStore(sys.argv[1]).grant(sys.argv[2], sys.argv[3])\n"
REVOKE = "import sys\nfrom jobq.grants import GrantStore\nGrantStore(sys.argv[1]).revoke_session(sys.argv[2])\n"


def test_concurrent_grants_from_many_processes_all_survive(tmp_path):
    path = tmp_path / "grants.json"
    finish([run_code(GRANT, str(path), "s", f"k{index}") for index in range(14)])
    store = GrantStore(path)
    assert all(store.has("s", f"k{index}") for index in range(14))


def test_a_revoke_running_beside_grants_loses_none_of_them(tmp_path):
    path = tmp_path / "grants.json"
    GrantStore(path).grant("a", "x")
    processes = [run_code(GRANT, str(path), "b", f"k{index}") for index in range(8)]
    processes.append(run_code(REVOKE, str(path), "a"))
    finish(processes)
    store = GrantStore(path)
    assert not store.has("a", "x")
    assert all(store.has("b", f"k{index}") for index in range(8))


def test_a_reader_never_fails_while_a_writer_keeps_granting(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    for index in range(800):
        store.grant("s", f"seed{index}")
    stop = threading.Event()
    errors = []

    def read():
        while not stop.is_set():
            try:
                store.has("s", "seed0")
            except Exception as error:
                errors.append(repr(error))
                return

    reader = threading.Thread(target=read)
    reader.start()
    for index in range(30):
        store.grant("s", f"late{index}")
    stop.set()
    reader.join(10)
    assert errors == []


def test_only_the_store_and_its_lock_remain_in_the_folder(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    store.grant("s", "k")
    store.revoke_session("s")
    assert sorted(os.listdir(tmp_path)) == ["grants.json", "grants.json.lock"]


def test_a_missing_file_is_an_empty_store(tmp_path):
    assert GrantStore(tmp_path / "none.json").has("s", "k") is False


def test_a_corrupt_file_raises_a_store_error_and_is_never_overwritten(tmp_path):
    path = tmp_path / "grants.json"
    path.write_text("{broken")
    store = GrantStore(path)
    assert issubclass(GrantStoreError, ValueError)
    with pytest.raises(GrantStoreError):
        store.has("s", "k")
    with pytest.raises(GrantStoreError):
        store.grant("s", "k")
    with pytest.raises(GrantStoreError):
        store.revoke_session("s")
    assert path.read_text() == "{broken"


def payload(**fields):
    return json.dumps({"session": "s1", "key": "write", **fields})


def test_a_granted_key_is_allowed_with_no_output(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    store.grant("s1", "write")
    assert hook.main(payload(), store) == ""


def test_an_ungranted_key_asks(tmp_path):
    store = GrantStore(tmp_path / "grants.json")
    store.grant("s2", "write")
    assert json.loads(hook.main(payload(), store)) == {"decision": "ask", "reason": "approval needed for write"}


@pytest.mark.parametrize("text", ["not json", "{}", json.dumps({"session": "s1"}), json.dumps({"key": "k"}), "[]"])
def test_unreadable_input_asks_without_raising(text, tmp_path):
    output = json.loads(hook.main(text, GrantStore(tmp_path / "grants.json")))
    assert output == {"decision": "ask", "reason": "approval needed: unreadable hook input"}


def test_an_unreadable_store_asks_without_raising(tmp_path):
    path = tmp_path / "grants.json"
    path.write_text("{broken")
    assert json.loads(hook.main(payload(), GrantStore(path))) == {
        "decision": "ask", "reason": "approval needed: grant store unreadable"}

    class Broken:
        def has(self, *_):
            raise OSError("disk")

    assert json.loads(hook.main(payload(), Broken()))["reason"] == "approval needed: grant store unreadable"


def test_the_default_store_comes_from_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "grants.json"
    GrantStore(path).grant("s1", "write")
    monkeypatch.delenv("JOBQ_GRANTS", raising=False)
    assert json.loads(hook.main(payload()))["decision"] == "ask"
    monkeypatch.setenv("JOBQ_GRANTS", str(path))
    assert hook.main(payload()) == ""
