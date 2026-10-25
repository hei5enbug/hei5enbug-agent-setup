# Repository rules

- Python 3.11 or newer, standard library only. Do not add runtime dependencies.
- Keep money in `Decimal` and round with `inventory.money.quantize`. Never use `float` for prices.
- Raise a subclass of `InventoryError` for every failure a user can cause. The CLI turns it into exit code 2.
- Time comes from the injected `clock`, never from `datetime.now()` inside a service.
- Run `python3 -m pytest -q` before reporting a change as done. Existing tests are not edited to make a change pass.
- New behavior needs tests in `tests/`.

## Documentation

- Write documentation in English. Design documents live in `docs/design/<topic>.md`.
- Every English Markdown document has a Korean mirror at `docs/ko/<path>.ko.md`, where `<path>` is the document's
  path in the repository. Update the mirror in the same change as the source. For example, `README.md` is mirrored
  at `docs/ko/README.ko.md` and `docs/design/x.md` at `docs/ko/docs/design/x.ko.md`.
- A mirror starts with its title and a quoted line that links the English source and says the mirror is not
  authoritative.
- User-visible changes to the CLI or the configuration are described in `README.md`.
