# Codex planning and agents

Plan in the main session's plan mode.
Keep high-level reasoning and decisions in the main session.

## Investigation

- Use the built-in `explorer` only for bounded, read-only investigation while planning.
- Give it one specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat results as leads. Verify critical claims in the main session before planning or deciding.

## Implementation

- Use other built-in multi-agent threads only after the plan is settled in the main session.
- Give them only clearly scoped code changes or tests.
- Run at most 6 agents concurrently, and only when their tasks share no files and have no build contention.
  Otherwise, run them sequentially.
