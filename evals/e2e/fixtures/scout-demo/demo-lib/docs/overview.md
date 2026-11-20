# demo-lib overview

demo-lib turns `key=value` and `key: value` lines into pairs.

- `parse_pair` handles one line.
- `parse_many` handles a list of lines and skips empty ones.
- Lines that start with the comment prefix are not special-cased yet.
