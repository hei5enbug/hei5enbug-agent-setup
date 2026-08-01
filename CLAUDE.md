@AGENTS.md

# Claude Code only

## Subagents

- Use the built-in `Explore` and `Plan` subagents only for bounded, read-only investigation while planning.
- Give them a specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in their results.
- Treat their results as leads, not conclusions. Verify critical claims in the main conversation before making plans or decisions.
- Use other work subagents, including custom subagents such as `coder`, `tester`, and `test-runner`, only after the plan is settled in the main conversation.
  Give them only clearly scoped code changes or tests.
- Run at most 10 subagents concurrently, and only when their tasks are fully independent with no shared files or build contention. Otherwise, run them sequentially.
