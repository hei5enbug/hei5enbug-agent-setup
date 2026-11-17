# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- The site build writes into `build/` and `python3 tools/check_site.py` reads it. Run both after a change to what the
  build writes.

## Documentation

- Write documentation in English. Every English Markdown document has a Korean mirror at
  `docs/ko/<path>.ko.md`, where `<path>` is the document's path in the repository, and the mirror is updated in
  the same change.
- User-visible changes are described in `README.md`, or in the page of `docs/` that it points to for that command, feature, or built file.

## Commits

- Use Conventional Commits: `<type>: <description>` with the types feat, fix, refactor, docs, test, chore, perf,
  and ci.
- Write the message in English. Use the imperative mood, keep the subject at most 72 characters, and do not end
  it with a period.
- Do not add trailers such as `Co-Authored-By` or `Signed-off-by`.
- Make one commit for one logical change.
