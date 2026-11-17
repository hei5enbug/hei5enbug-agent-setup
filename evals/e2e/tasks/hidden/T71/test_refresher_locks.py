import json
import threading

from jobq.locks import FileLock, LockBusy
from jobq.refresh import Refresher


def test_record_is_not_blocked_while_a_send_is_running(tmp_path):
    started, release = threading.Event(), threading.Event()

    def send(_session, _command):
        started.set()
        release.wait(10)
        return True

    refresher = Refresher(tmp_path, send)
    runner = threading.Thread(target=refresher.run, args=(["a"],), daemon=True)
    runner.start()
    try:
        assert started.wait(5)
        writer = threading.Thread(target=refresher.record, args=("other", "idle"), daemon=True)
        writer.start()
        writer.join(3)
        assert not writer.is_alive(), "record waited for the send to finish"
    finally:
        release.set()
        runner.join(10)
    assert refresher.state()["other"] == "idle"


def test_the_sessions_lock_is_free_while_a_result_is_being_recorded(tmp_path):
    in_record, go = threading.Event(), threading.Event()

    class Slow(Refresher):
        def record(self, session, status):
            in_record.set()
            go.wait(10)
            super().record(session, status)

    refresher = Slow(tmp_path, lambda *_: True)
    runner = threading.Thread(target=refresher.run, args=(["a"],), daemon=True)
    runner.start()
    try:
        assert in_record.wait(5), "run did not record through record()"
        try:
            with FileLock(tmp_path / "sessions.lock", blocking=False):
                pass
        except LockBusy:
            raise AssertionError("sessions.lock was held while recording")
    finally:
        go.set()
        runner.join(10)
    assert refresher.state() == {"a": "sent"}


def test_the_sessions_lock_is_held_during_a_send_and_the_state_lock_is_not(tmp_path):
    seen = {}

    def send(_session, _command):
        for name in ("sessions.lock", "state.lock"):
            try:
                with FileLock(tmp_path / name, blocking=False):
                    seen[name] = "free"
            except LockBusy:
                seen[name] = "held"
        return True

    Refresher(tmp_path, send).run(["a"])
    assert seen == {"sessions.lock": "held", "state.lock": "free"}


def test_concurrent_records_lose_no_update(tmp_path):
    refresher = Refresher(tmp_path, lambda *_: True)
    barrier = threading.Barrier(16)

    def work(index):
        barrier.wait()
        refresher.record(f"s{index}", f"status{index}")

    threads = [threading.Thread(target=work, args=(index,)) for index in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert refresher.state() == {f"s{index}": f"status{index}" for index in range(16)}


def test_a_reader_never_sees_a_half_written_state_file(tmp_path):
    refresher = Refresher(tmp_path, lambda *_: True)
    for index in range(1500):
        refresher.record(f"session-{index}", "x" * 40)
    stop = threading.Event()
    errors = []

    def read():
        while not stop.is_set():
            try:
                json.loads(refresher.state_path.read_text())
            except Exception as error:
                errors.append(repr(error))
                return

    reader = threading.Thread(target=read)
    reader.start()
    for index in range(25):
        refresher.record(f"late-{index}", "y" * 40)
    stop.set()
    reader.join(10)
    assert errors == []
    assert not [path.name for path in tmp_path.iterdir() if path.name.endswith(".tmp")]


def test_a_failing_send_is_recorded_the_lock_is_released_and_the_next_session_goes_on(tmp_path):
    def send(session, _command):
        if session == "a":
            raise RuntimeError("boom")
        return True

    refresher = Refresher(tmp_path, send)
    assert refresher.run(["a", "b"]) == {"a": "failed", "b": "sent"}
    assert refresher.state() == {"a": "failed", "b": "sent"}
    with FileLock(tmp_path / "sessions.lock", blocking=False):
        pass
