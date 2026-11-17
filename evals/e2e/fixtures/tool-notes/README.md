# tool-notes

A small parser for the key=value lines of a demo settings file, with the notes and writing rules of the team that
maintains it.

## Layout

- `demo_parser/` holds the parser and `tests/` its tests.
- `config/review.yaml` names the model that reviews the demo texts.
- `notes/` holds change notes and thread notes. They are inputs and stay as they are.
- `docs/writing-rules.md` holds the writing rules for each place the team posts to.
- `out/` holds the finished texts, one file per text, ready to be pasted as they are.
