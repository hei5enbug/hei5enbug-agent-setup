"""A daily limiter whose check runs inside a lock, a reviewer's question about it, and the team's writing rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory_common import add_writing_rules, commit, write  # noqa: E402

LIMITER = '''"""A daily cap on how many import runs may start."""

from __future__ import annotations

import threading


class DailyLimit:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def try_take(self) -> bool:
        """Count one run and return True, or return False when the cap is reached."""
        with self._lock:
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        return self._used
'''

TEST = '''from inventory.ratelimit import DailyLimit


def test_runs_beyond_the_cap_are_refused():
    limit = DailyLimit(2)
    assert [limit.try_take() for _ in range(3)] == [True, True, False]


def test_used_counts_only_accepted_runs():
    limit = DailyLimit(1)
    limit.try_take()
    limit.try_take()
    assert limit.used == 1
'''

COMMENT = """inventory/ratelimit.py 17행 리뷰 코멘트

`self._used >= self._limit` 확인을 왜 lock 안에서 하나요? lock은 `self._used += 1`에만 걸어도 충분해 보이는데,
확인까지 넣은 이유가 궁금합니다.
"""


def main(repo: str) -> None:
    root = Path(repo)
    add_writing_rules(root)
    write(root, "inventory/ratelimit.py", LIMITER)
    write(root, "tests/test_ratelimit.py", TEST)
    write(root, "review/comment-1.txt", COMMENT)
    commit(root, "feat: cap the daily import runs")


if __name__ == "__main__":
    main(sys.argv[1])
