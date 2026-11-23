"""Four commits on tally-demo: memo_count and memo_chars are each added and then renamed to the required note names."""

from __future__ import annotations

import sys
from pathlib import Path

from commit_common import git, write

COUNT_ADDED = '''

def memo_count(notes: list[str]) -> int:
    """Return how many notes the list holds."""
    return len(notes)
'''
CHARS_ADDED = '''

def memo_chars(notes: list[str]) -> int:
    """Return the number of characters over all notes."""
    return sum(len(note) for note in notes)
'''
COUNT_TEST = '''

def test_memo_count_counts_every_entry():
    from tally.counts import memo_count

    assert memo_count(["a", "", "b"]) == 3
'''
CHARS_TEST = '''

def test_memo_chars_adds_the_lengths():
    from tally.report import memo_chars

    assert memo_chars(["ab", "c"]) == 3
'''


def append(root: Path, relative: str, text: str) -> None:
    path = root / relative
    write(root, relative, path.read_text(encoding="utf-8") + text)


def rename(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    write(root, relative, path.read_text(encoding="utf-8").replace(old, new))


def commit(root: Path, subject: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject)


def main(repo: str) -> None:
    root = Path(repo)
    append(root, "tally/counts.py", COUNT_ADDED)
    append(root, "tests/test_counts.py", COUNT_TEST)
    commit(root, "feat: add memo_count helper")
    for relative in ("tally/counts.py", "tests/test_counts.py"):
        rename(root, relative, "memo_count", "note_count")
    commit(root, "fix: rename memo_count to note_count")
    append(root, "tally/report.py", CHARS_ADDED)
    append(root, "tests/test_report.py", CHARS_TEST)
    commit(root, "feat: add memo_chars helper")
    for relative in ("tally/report.py", "tests/test_report.py"):
        rename(root, relative, "memo_chars", "note_chars")
    commit(root, "fix: rename memo_chars to note_chars")


if __name__ == "__main__":
    main(sys.argv[1])
