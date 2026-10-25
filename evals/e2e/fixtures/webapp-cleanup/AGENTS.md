# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done.
- Generated output (`build/`, `dist/`, caches, logs) is not committed.
- Local secrets live in `.env`. Never print it, commit it, or copy its values into commands, messages, or files.
- Do not discard or overwrite another person's uncommitted work. Ask first when unsure.
- Write documentation in English. Every English Markdown document has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
