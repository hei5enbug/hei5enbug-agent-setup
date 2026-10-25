# notes-cli

A command-line memo manager. Memos are stored in a single JSON file and listed page by page.

## Usage

```bash
python3 -m notes_cli memo add "Plan trip" --body "book flights" --tag travel
python3 -m notes_cli memo list
python3 -m notes_cli memo show 1
python3 -m notes_cli memo search flights
python3 -m notes_cli memo remove 1
```

- `memo add TITLE [--body TEXT] [--tag TAG ...]` saves a memo and prints its id.
- `memo list [--tag TAG] [--page N]` lists memos in pages. The page size comes from `config/settings.toml`.
- `memo show ID` prints one memo with its tags and creation time.
- `memo search QUERY` finds memos whose title or body contains the text, ignoring case.
- `memo remove ID` deletes a memo.

The memo file is `memos.json` in the current directory. Use `--store FILE` before the command or the
`NOTES_CLI_STORE` environment variable to choose another file. A failing command prints the reason on stderr and
exits with 1.

## Development

```bash
python3 -m pytest -q
```

Contribution rules, including the commit message format, are in [AGENTS.md](AGENTS.md). The Korean mirror of this
file is [docs/ko/README.ko.md](docs/ko/README.ko.md).
