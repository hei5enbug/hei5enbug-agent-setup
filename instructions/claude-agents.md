# Claude Code planning and agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing, agent-selection, and worker rules below.

## Investigation

- Never use the built-in `Explore` and `Plan` subagents or the catch-all `general-purpose` and `claude` subagents.
- Use `hei5enbug-agent-setup:scout` for investigation, only while planning and only when the session delegation threshold is met.
- Give each `hei5enbug-agent-setup:scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- The plugin bundles `hei5enbug-agent-setup:scout`; if it is unavailable, investigate in the main conversation.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Claude Code worker integration.

- Use only `hei5enbug-agent-setup:worker` for implementation. Pass the `sonnet` alias as the per-invocation
  model on every invocation and resume. Never switch to another agent.
- The required family is the latest production Claude Sonnet. Resolve its full ID from the Sonnet mapping on
  the official [model configuration page](https://code.claude.com/docs/en/model-config) and the model
  information it links.
- Before the first invocation in a run, inspect only these non-secret inputs in the environment and every
  settings file: the worker definition, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  `ANTHROPIC_DEFAULT_SONNET_MODEL`, effort overrides such as `CLAUDE_CODE_EFFORT_LEVEL`, effort caps such as
  `maxEffortLevel` or organization limits, and any substitution or fallback warning. Never change user settings.
- Claude Code can reload settings during a session, and a forced subagent model overrides the per-invocation
  model. Recheck these inputs before every follow-up that carries implementation work.
- Accept the host's subagent record, such as `/tasks` or the subagent transcript, as evidence when it names
  the resolved full ID as the actual model and `xhigh` as the effort, and configuration cannot lower that
  effort. Provider-internal reasoning telemetry is not required. A different recorded model, a cap below
  `xhigh`, a contradictory override, or unknown effective precedence is insufficient.
- The launch result does not name the model, so start each worker with a readiness-only assignment. After its
  record passes, send the implementation assignment to the same worker. Use this path only when that
  follow-up keeps the per-invocation model. When that continuation is unavailable, skip the two-phase path
  and make no edits. Recheck the settings after any resume.
- The host limit is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main
  session. Use its current value and open slots; never change it.
- A missing plugin worker or a missing subagent record blocks the affected implementation. Report the exact
  capability and make no edit.
