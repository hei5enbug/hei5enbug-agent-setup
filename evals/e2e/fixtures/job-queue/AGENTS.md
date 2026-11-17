# Repository rules

- Python 3.11 or newer, standard library only. Locks use `jobq.locks.FileLock`, never a bare `flock` call.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- Every state file is written whole or not at all: never leave a half-written file for a reader.
- New behavior needs tests in `tests/`.
