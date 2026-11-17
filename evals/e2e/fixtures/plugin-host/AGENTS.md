# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- The session context is built from `instructions/session/*.md` and must stay within its byte budget. Details that
  only some runs need go into a reference file under `instructions/`, and the session file keeps one entry line:
  "Before <action>, read <reference>."

## Documentation

- Write documentation in English. `README.md` and every Markdown document in `docs/` and `instructions/`, except the
  files in `instructions/session/`, has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
- A mirror starts with its title and a quoted line that links the English source and says the mirror is not
  authoritative.
- A new document is listed in the documentation map of `README.md`.
