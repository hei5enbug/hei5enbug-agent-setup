# Repository rules

- Python 3.11 or newer.
- Money is whole cents in `int`. The CLI prints cents as `12.34`.
- Raise a subclass of `ShopError` for every failure a user can cause. The CLI turns it into exit code 2.
- Run `python3 -m pytest -q` before reporting a change as done. Existing tests are not edited to make a change pass.
- New behavior needs tests in `tests/`.

## Documentation

- Write documentation in English. Every English Markdown document has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
- User-visible changes to the commands are described in `README.md`.
