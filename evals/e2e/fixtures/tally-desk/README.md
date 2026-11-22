# tally-desk

Hours per team, read from `data/entries.json`. `TALLY_DATA` names another entries file.

## Commands

- `tally totals` prints `<team> <hours>` for every team, all dates together, sorted by team name.
- `tally rate TEAM` prints the hourly rate of a team from `data/rates.json`.
- `tally cost TEAM` prints the team's total hours times its hourly rate, in whole currency units.

## Time

`tally.clock.now()` returns the current time. `TALLY_NOW` (`YYYY-MM-DDTHH:MM`) overrides it, which the tests use.

## Rates

`tally.rates.rate_for` keeps each rate it reads for one hour with `tally.cache.ttl_cached`.
