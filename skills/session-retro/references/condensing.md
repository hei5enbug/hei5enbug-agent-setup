# Condensing large session records

Use this when the files of a session or group together exceed 1 MB. Run the bundled script into the session
temporary folder, resolving its path from the directory that holds `SKILL.md`:

```text
python3 scripts/condense_records.py <session files> --out <temporary folder> [--since <YYYY-MM-DDTHH:MM> [--until <YYYY-MM-DDTHH:MM>]] [--tz <zone>]
```

Pass the range and zone of step 2; a day runs from its midnight to the next one. It writes one
`L<original line number> <kind> <text>` line per user input, reply, tool call, and error, with `user`,
`reply`, `tool`, and `error` as kinds, and truncates long text with a count of dropped characters. It prints
one JSON object with each output path and the line counts, and exits with 0 on success, 2 for an invalid
argument, and 1 when an input cannot be read. Give the worker the condensed files and the original paths; it
cites original line numbers and opens an original only to check a quote.
