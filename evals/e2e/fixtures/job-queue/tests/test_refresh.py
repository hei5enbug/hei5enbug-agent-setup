from jobq.refresh import Refresher


def test_each_session_is_sent_a_refresh_and_recorded(tmp_path):
    sent = []
    refresher = Refresher(tmp_path, lambda session, command: sent.append((session, command)) or True)
    assert refresher.run(["a", "b"]) == {"a": "sent", "b": "sent"}
    assert sent == [("a", "refresh"), ("b", "refresh")]
    assert refresher.state() == {"a": "sent", "b": "sent"}


def test_a_failing_send_is_recorded_and_the_run_goes_on(tmp_path):
    def send(session, _command):
        if session == "a":
            raise RuntimeError("boom")
        return True

    refresher = Refresher(tmp_path, send)
    assert refresher.run(["a", "b"]) == {"a": "failed", "b": "sent"}


def test_record_updates_one_session(tmp_path):
    refresher = Refresher(tmp_path, lambda *_: True)
    refresher.record("a", "idle")
    refresher.record("b", "busy")
    assert refresher.state() == {"a": "idle", "b": "busy"}
