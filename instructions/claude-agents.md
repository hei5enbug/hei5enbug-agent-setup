# Claude Code planning and agents

Keep planning and high-level reasoning in the main conversation.

## Investigation

- Never use the built-in `Explore` and `Plan` subagents or the catch-all `general-purpose` and `claude` subagents.
- Use `scout` for investigation, only while planning.
- For a known symbol, file path, glob, or literal string, run `rg`, `fd`, or `ast-grep` in the main conversation.
- Launch `scout` only when at least two investigation targets share no file and each needs more than one file read.
- Give each `scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- If `scout` is not installed, investigate in the main conversation.

## Implementation

- Use work subagents such as `coder`, `tester`, and `test-runner` only after the plan is settled.
- Give them only clearly scoped code changes or tests.
- Run at most 6 subagents concurrently, and only when their tasks share no files and have no build contention.
  Otherwise, run them sequentially.
