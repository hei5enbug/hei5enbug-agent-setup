import pytest

from jobq.locks import FileLock, LockBusy


def test_a_second_non_blocking_lock_is_busy_until_the_first_is_released(tmp_path):
    path = tmp_path / "a.lock"
    with FileLock(path):
        with pytest.raises(LockBusy):
            with FileLock(path, blocking=False):
                pass
    with FileLock(path, blocking=False):
        pass
