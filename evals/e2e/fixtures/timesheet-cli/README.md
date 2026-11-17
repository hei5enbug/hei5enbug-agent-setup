# timesheet-cli

A small command-line tracker for time entries. Entries live in a JSON file, `data/entries.json`.

## Commands

| Command | What it does |
|---|---|
| `add DATE PROJECT MINUTES` | Adds an entry. `DATE` is `YYYY-MM-DD`. |
| `list [--on DATE]` | Prints entries, one per line, oldest date first. |
| `totals` | Prints the minutes of each project. |
| `report` | Prints the list, then the totals. |
| `export [--from DATE] [--to DATE]` | Writes the entries to a CSV file in the export folder. |

Every date option reads `YYYY-MM-DD`.

## Storage

- Adds are safe to run in parallel: the store takes a lock file while it changes the data file, so two adds at once
  never lose an entry.
- `timesheet.store.load_cached()` keeps the parsed file for one hour inside a process, through `timesheet.cache.TtlCache`.
