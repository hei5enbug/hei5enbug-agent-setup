# Repository guidance

Read this before ending work in a repository in which a user correction repeated an earlier one or a stated rule, or
an investigation that took several steps reached a decision. The aim is guidance that keeps later sessions from
repeating it while each task reads only the part it needs. Change no repository file until the user approves. Keep
drafts and proofs only in the session's temporary folder.

## Repeated correction

A correction repeats when the same correction came twice in the session, the user says it repeats an earlier one, or
it concerns a rule the repository already states.

- When a check such as a test, a lint rule, a schema, or a hook could enforce it, run the `mistake-enforcer` skill in
  its single-class mode on that one mistake class without being asked, and show the check candidate with the
  instance it fails on.
- When no check can enforce it, draft the written rule under the placement rules below and show it the same way.
  Example: after two corrections about tone in release notes, the draft is the entry line "Before writing release
  notes, read docs/rules/release-notes.md" with the rule in that file.

## Decision after an investigation

When an investigation that took several steps reached a decision, draft the ADR described below and its entry line,
show both, and write them only after the user approves. Example: after comparing two queue libraries, the ADR states
which one stays, why, and which one was rejected.

When neither case applies, record nothing and recommend nothing.

## Placement

- Write to the repository's agent instruction file, such as `AGENTS.md` or `CLAUDE.md`, following its own rules.
  Keep in that file only rules that every task needs.
- Put a rule that only some tasks need in a reference file, and leave one entry line in the instruction file in the
  form "Before <task>, read <file>."
- Record a decision as a short ADR of at most 30 lines with the decision, its reason, and the options it rejected,
  in the repository's ADR folder or `docs/adr/` when it has none, and point to it with an entry line of the same
  form.
- Search the existing guidance first and change the entry that covers the topic. Write each entry in as few lines as
  it takes. Replace or delete an outdated entry instead of appending to it.
