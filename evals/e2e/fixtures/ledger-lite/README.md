# ledger-lite

A tiny double-entry journal. It loads entries from CSV, answers balance questions, builds month-end reports, and
matches a bank statement against the journal.

## Concepts

- **Entry**: a dated amount on one account. Debits are positive and credits are negative, so the entries of a
  consistent journal add up to zero.
- **Journal**: the date-ordered list of entries. `Journal.balance(account, as_of)` returns the balance on a day.
- **Reconciliation**: `reconcile(journal, lines)` pairs each statement line with a bank entry of the same amount
  dated within a few days and reports what is left over on either side.

## Files

Entry files have the columns `date,account,amount,memo`. Statement files have `date,description,amount`. Dates use
the ISO format `YYYY-MM-DD`.

## Development

The tests read their sample files from a directory named by `SAMPLE_DATA_DIR`. See [docs/testing.md](docs/testing.md)
for how to run them.

Project rules are in [AGENTS.md](AGENTS.md). The Korean mirror of this file is
[docs/ko/README.ko.md](docs/ko/README.ko.md).
