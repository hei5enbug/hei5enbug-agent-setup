@AGENTS.md

# Claude Code only

## Subagents

- Never use the built-in `Explore` and `Plan` subagents, and never use the catch-all `general-purpose` and `claude` subagents.
  Use the `scout` subagent for investigation, and keep planning in the main conversation.
- Never launch a subagent when the target is already specified — a known symbol, file path, glob, or literal string.
  Run `rg`, `fd`, or `ast-grep` in the main conversation instead.
- Launch `scout` only while planning, and only when two or more investigation targets are independent:
  they share no file, and each one needs more than one file read.
- Give each `scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat its results as leads, not conclusions. Verify critical claims in the main conversation before making plans or decisions.
- Use work subagents such as `coder`, `tester`, and `test-runner` only after the plan is settled in the main conversation.
  Give them only clearly scoped code changes or tests.
- Run at most 6 subagents concurrently, and only when their tasks are fully independent with no shared files or build contention. Otherwise, run them sequentially.
