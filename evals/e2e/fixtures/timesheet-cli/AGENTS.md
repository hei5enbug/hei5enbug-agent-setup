# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- Settings live in `config/settings.toml`. Code reads them through `timesheet.settings`.
- Every command that takes a date reads it through `timesheet.dates.parse_date`.

## Documentation

- Write documentation in English. Every English Markdown document has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
- User-visible changes to the commands are described in `README.md`.
