# Claude Code planning and agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing and agent-selection rules below.

## Investigation

- Never use the built-in `Explore` and `Plan` subagents or the catch-all `general-purpose` and `claude` subagents.
- Use `scout` for investigation, only while planning and only when the session delegation threshold is met.
- Give each `scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- If `scout` is not installed, investigate in the main conversation.

## Implementation

- Use work subagents such as `coder`, `tester`, and `test-runner` only after the plan is settled, except for
  the reviewer invocation above.
- Give them only clearly scoped code changes or tests.
- Run at most 6 subagents concurrently, and only when their tasks share no files and have no build contention.
  Otherwise, run them sequentially.
