# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- A hook never raises to its caller: it returns an allow, ask, or deny result.
- New behavior needs tests in `tests/`.
