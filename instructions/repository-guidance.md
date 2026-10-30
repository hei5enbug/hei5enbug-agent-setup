# Repository guidance

Read this before ending work in a repository in which a user correction, or an investigation that took several
steps, is likely to recur. The aim is guidance that keeps later sessions from repeating it while each task reads
only the part it needs.

- At the end of the work, recommend recording it in one line, and change no file until the user approves.
- When a check can enforce the rule, such as a test, a lint rule, or a schema, recommend the `mistake-enforcer` skill
  instead of a written rule.
- Write to the repository's agent instruction file, such as `AGENTS.md` or `CLAUDE.md`, following its own rules.
  Keep in that file only rules that every task needs.
- Put a rule that only some tasks need in a reference file, and leave one entry line in the instruction file in the
  form "Before <task>, read <file>."
- Record a decision reached after an investigation as a short ADR of at most 30 lines with the decision, its reason,
  and the options it rejected, in the repository's ADR folder or `docs/adr/` when it has none, and point to it with
  an entry line of the same form.
- Search the existing guidance first and change the entry that covers the topic. Write each entry in as few lines as
  it takes. Replace or delete an outdated entry instead of appending to it.
