# Repository rules

- Python 3.11 or newer, standard library only.
- Hours are floats printed with one decimal. Dates are `YYYY-MM-DD` strings.
- The current time comes only from `tally.clock.now()`, which tests control through `TALLY_NOW`.
- Raise a subclass of `TallyError` for every failure a user can cause. The CLI turns it into exit code 2.
- Run `python3 -m pytest -q` before reporting a change as done. Existing tests are not edited to make a change pass.
- New behavior needs tests in `tests/`.

## Documentation

- Write documentation in English. Every English Markdown document has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
- User-visible changes to the commands are described in `README.md`.
