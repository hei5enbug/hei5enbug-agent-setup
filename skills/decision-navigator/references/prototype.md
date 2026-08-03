# Prototype workflow

A prototype is a disposable artifact that answers one design question. Use it to make a decision
easier, not to deliver the destination.

## Choose the branch

- For business logic, state transitions, data shape, or an API surface, read
  [logic prototype](prototype-logic.md).
- For layout, information hierarchy, or interaction appearance, read
  [UI prototype](prototype-ui.md).

If the branch is unclear and the human is available, ask. Otherwise infer it from the surrounding
code and state the assumption.

## Shared rules

1. State the exact question before creating the artifact.
2. Mark the artifact clearly as a prototype and keep it near the relevant code.
3. Reuse the project's runtime, task runner, and conventions.
4. Provide one command or URL that lets the human try it.
5. Keep state in memory unless persistence is the question being tested.
6. Skip production polish, broad abstractions, and unrelated edge handling.
7. Make the relevant state or variation visible after every interaction.
8. Treat human reaction as evidence; do not answer a human-in-the-loop ticket on the human's behalf.

## Capture and cleanup

Record the winning decision and why it won. Put the decision note and pointers to any temporary code
under `.decision-navigator/<effort>/artifacts/prototypes/<ticket>/`, then link that directory from the ticket.
Do not publish prototype results to an external tracker or connected document service.

Only the validated idea may move into production work, and only when the map's Notes explicitly
include execution. Remove prototype scaffolding from the main line after the decision is captured.
