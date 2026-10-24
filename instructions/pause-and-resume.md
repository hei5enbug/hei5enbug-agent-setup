# Pause and resume

The [work efficiency](work-efficiency.md) rules link this file. Read it before a planned pause, a handoff, or an
expected compaction of long work, such as a plugin refresh that sends `/compact` to the session.

## Resume note

Write a short note in the host's session temporary folder, or under the operating system's temporary folder when the
host has none, and report its path. Write it into the project only when the user asks. Use these headings:

```markdown
# Resume: <goal>

Continue from "Next action". This note and the records it cites are authoritative; do not redo verified steps.

## Goal
## Current step
## Verified
<each claim with its check: command, result, and the input state it covered>
## Current state
<branch, uncommitted changes, running processes, pending questions>
## Next action
## Key files
## Pitfalls
```

List under "Verified" only what a check proved; put an unchecked belief under "Current state" or "Pitfalls". Never
copy a secret or other protected value into the note.

## Resume

A session that continues from a resume note starts at its next action. Do not rerun completed reproductions or
verified checks; reuse their results under the [check-evidence rules](work-efficiency.md#check-evidence) while
their inputs remain unchanged. Before acceptance, verify each inherited claim the result depends on against the real
artifact, such as the file, diff, or test output, not against the note. When the note and the current state
disagree, trust the state and report the difference.
