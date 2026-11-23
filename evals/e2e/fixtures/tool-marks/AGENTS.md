# Repository rules

- Python 3.11 or newer, standard library only.
- Run `python3 -m pytest -q` before reporting a change as done. Do not edit existing tests to make a change pass.
- Write finished texts for other readers to `out/<name>.txt`. Do not edit files in `notes/`.
- A text follows the rules of the place it is posted to in `docs/writing-rules.md`.

## Commits

- Use Conventional Commits: `<type>: <description>` with the types feat, fix, refactor, docs, test, chore, perf,
  and ci.
- Write the message in English. Use the imperative mood, keep the subject at most 72 characters, and do not end
  it with a period.
- Do not add trailers such as `Co-Authored-By` or `Signed-off-by`.
- Make one commit for one logical change.
