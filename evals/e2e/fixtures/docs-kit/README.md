# docs-kit

A static documentation site builder. It turns the Markdown pages in `content/` into HTML, a sitemap, and a search
index, and it keeps visit counts in a local database.

## Usage

```bash
python3 -m dockit build
python3 tools/check_site.py
python3 -m dockit visit guide
```

- `build [--out DIR]` writes one HTML file per page, `sitemap.xml`, and `search-index.json` into `build/` (or `DIR`).
  It empties the folder first and refuses to run while another build uses it. The three steps take a few seconds each.
- `python3 tools/check_site.py` reads `build/` and reports every file the build should have written and did not.
- The other commands come from features, see below.

A page is a Markdown file with an optional front matter of `key: value` lines between two `---` lines. The keys are
`title`, `updated` (a `YYYY-MM-DD` date), and `draft` (`true` marks a page that is not ready).

The built files are described in `docs/sitemap.md` and `docs/search-index.md`.

## Features

A feature is one module in `dockit/features/`. The program finds every module there by itself: a module may define
`MIGRATIONS` (pairs of a name and an SQL statement), `register(commands)` to add its subcommands, and
`handle(args, store)` to run them and return whether it did. Each feature has a page in `docs/features/`.

The local database is `data/dockit.db`. Use `--db FILE` before the command or the `DOCKIT_DB` environment variable to
choose another file. Only one process uses the file at a time: a second one stops with an error that names the
process that holds it. The tests use the same file and hold it for the whole test run.

## Development

```bash
python3 -m pytest -q
```
