import sys

from patch_tools import append

append(sys.argv[1], "tests/test_refresh.py", '''

def test_record_does_not_wait_for_a_running_send(tmp_path):
    import threading

    started, release = threading.Event(), threading.Event()

    def send(_session, _command):
        started.set()
        release.wait(5)
        return True

    refresher = Refresher(tmp_path, send)
    runner = threading.Thread(target=refresher.run, args=(["a"],), daemon=True)
    runner.start()
    assert started.wait(5)
    refresher.record("b", "idle")
    release.set()
    runner.join(5)
    assert refresher.state()["b"] == "idle"
''')
