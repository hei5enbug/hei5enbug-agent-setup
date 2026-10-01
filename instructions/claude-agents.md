# Claude Code planning and agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing, agent-selection, and worker rules below.

## Built-in subagents

- Never use a built-in subagent, including `general-purpose`, `Explore`, `Plan`, `claude`, or a fork. The
  exceptions are `claude-code-guide` and `statusline-setup`, which have narrow purposes that do not overlap
  `scout` or `worker`. Always name the subagent type, because an omitted type runs `general-purpose`.
- The plugin's agent guard hook denies an omitted type and every built-in type except those two exceptions; every
  other type, including a plugin agent or a definition from any user, project, CLI, or managed source, passes.
  When it denies a call, use the plugin agent that fits or work in the main conversation.

## Investigation

- Use `hei5enbug-agent-setup:scout` for investigation, only while planning and only when the session delegation threshold is met.
- Give each `hei5enbug-agent-setup:scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- The plugin bundles `hei5enbug-agent-setup:scout`; if it is unavailable, investigate in the main conversation.
- Its definition pins its model. Never pass a per-invocation model, because that overrides the definition.

## Skill workers

- When a skill asks for an independent read-only worker, such as a review persona, a research ticket, or a
  grader, use `hei5enbug-agent-setup:scout` and give it the role's instructions and output contract. The main
  conversation writes any file the role produces. Run a role that needs web access or edits in the main
  conversation.
- When a skill asks for a worker that writes trial outputs, run a separate `claude -p` process with the model
  and effort that the skill pins instead of a subagent.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Claude Code worker integration.

- Use only `hei5enbug-agent-setup:worker` for implementation. Its definition pins `claude-sonnet-5-5` and
  `high`. Never pass a per-invocation model on an invocation or resume, because that overrides the
  definition. Never switch to another agent.
- Before the first invocation in a run, inspect only these non-secret inputs in the environment and every
  settings file: the worker definition, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  effort overrides such as `CLAUDE_CODE_EFFORT_LEVEL`, effort caps such as `maxEffortLevel` or organization
  limits, and any substitution or fallback warning. Never change user settings.
- Claude Code can reload settings during a session, and a forced subagent model overrides the definition.
  Recheck these inputs before every follow-up that carries implementation work.
- Accept the host's subagent record, such as `/tasks` or the subagent transcript, as evidence when it names
  `claude-sonnet-5-5` as the actual model and `high` as the effort, and configuration cannot lower that
  effort. Provider-internal reasoning telemetry is not required. A different recorded model, a cap below
  `high`, a contradictory override, or unknown effective precedence is insufficient.
- Read that record from the transcripts under the Claude config directory, `CLAUDE_CONFIG_DIR` or `~/.claude`,
  in `projects/<project>/`. The session transcript's launch result names the worker's `agentId` and
  `resolvedModel`, and `<session-id>/subagents/agent-<agentId>.jsonl` names `model` and `effort` on each
  assistant entry.
- The launch result does not name the model, so start each worker with a readiness-only assignment. After its
  record passes, send the implementation assignment to the same worker. Use this path only when that
  follow-up keeps the pinned model. When that continuation is unavailable, skip the two-phase path
  and make no edits. Recheck the settings after any resume.
- The host limit is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main
  session. Use its current value and open slots; never change it.
- A missing plugin worker or a missing subagent record blocks the affected implementation. Report the exact
  capability and make no edit.
