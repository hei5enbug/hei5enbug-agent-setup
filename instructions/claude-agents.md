# Claude Code planning and agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing, agent-selection, and worker rules below.

Before dispatching an agent or model runner, read [shared model routing](model-routing.md), following the
instruction-reuse rules in [work efficiency](work-efficiency.md). After a main-model or profile switch or
session resume, apply its effective-settings checks before dispatch.

## Built-in subagents

- Never use a built-in subagent, including `general-purpose`, `Explore`, `Plan`, `claude`, or a fork. The
  exceptions are `claude-code-guide` and `statusline-setup`, which have narrow purposes that do not overlap
  `scout` or `worker`. Always name the subagent type, because an omitted type runs `general-purpose`.
- The plugin's agent guard hook denies an omitted type and every built-in type except those two exceptions; every
  other type, including a plugin agent or a definition from any user, project, CLI, or managed source, passes.
  When it denies a call, use the plugin agent that fits or work in the main conversation.

## Investigation

- Use `hei5enbug-agent-setup:scout` for bounded investigation whenever the session delegation rule selects it,
  during planning or execution.
- Give each `hei5enbug-agent-setup:scout` one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- The plugin bundles `hei5enbug-agent-setup:scout`; if it is unavailable, investigate in the main conversation.
- Its definition pins its model. Never pass a per-invocation model, because that overrides the definition.
- For bounded public research, use `hei5enbug-agent-setup:researcher` only when public search and fetch tools
  are available. Never pass a per-invocation model; its definition pins `claude-sonnet-5-5` and `medium`.
  Verify that definition, effective non-secret settings, and the host subagent record before relying on its
  result. Otherwise, continue in the main conversation.

## Skill workers

- When a skill asks for an independent read-only worker, such as a review persona, a research ticket, or a
  grader, use `hei5enbug-agent-setup:scout` only when its effective settings match the role's requirements. For
  Skill Builder evaluation, use the required participant table in its evaluation adapter; target-skill metadata
  does not override it. When no native role matches, use a verified Skill Builder-approved runner or its
  unavailable-capability path. Give the role its instructions and output contract. Do not lower the required
  effort or change production scout settings. The main conversation writes any file the role produces. For
  bounded public research, use `researcher` only when the
  skill's contract and any evaluation settings permit its verified profile and public tools are available.
  Private or authenticated remote access and all edits stay in the main conversation.
- When a skill asks for a worker that writes trial outputs, run a separate `claude -p` process with the model
  and effort that the skill pins instead of a subagent.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Claude Code worker integration.

- When delegating implementation, use only `hei5enbug-agent-setup:worker`, or `hei5enbug-agent-setup:designer`
  for UI code, visual design, and diagram work. Their definitions pin `claude-sonnet-5-5` with `high` and
  `claude-opus-5-5` with `xhigh`. Never pass a per-invocation model on an invocation or resume, because that
  overrides the definition. Never switch to an agent outside these two.
- Before the first invocation in a run, inspect only these non-secret inputs in the environment and every
  settings file: the worker definition, `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  effort overrides such as `CLAUDE_CODE_EFFORT_LEVEL`, effort caps such as `maxEffortLevel` or organization
  limits, and any substitution or fallback warning. Never change user settings.
- Claude Code can reload settings during a session, and a forced subagent model overrides the definition.
  Recheck these inputs before every follow-up that carries implementation work.
- Selecting GPT as Claude Code's main model does not change this host, its tools, permissions, agent definitions,
  or execution rules. Preserve the worker's pinned model and effort.
- Accept the host's subagent record, such as `/tasks` or the subagent transcript, as evidence when it names
  `claude-sonnet-5-5` as the actual model and `high` as the effort, and configuration cannot lower that
  effort. For `designer`, the evidence is `claude-opus-5-5` with `xhigh`. Provider-internal reasoning telemetry
  is not required. A different recorded model, a cap below the pinned effort, a contradictory override, or
  unknown effective precedence is insufficient.
- Read that record from the transcripts under the Claude config directory, `CLAUDE_CONFIG_DIR` or `~/.claude`,
  in `projects/<project>/`. The session transcript's launch result names the worker's `agentId` and
  `resolvedModel`, and `<session-id>/subagents/agent-<agentId>.jsonl` names `model` and `effort` on each
  assistant entry.
- When the session context contains `hei5enbug-agent-setup mod: role pinning active`, the plugin mod pins each
  role's model and effort on every request and blocks tool calls from a subagent that answered on another model.
  Send the assignment directly, with no readiness-only call.
- Without that line, the launch result does not name the model, so start each worker with a readiness-only
  assignment. After its record passes, send the implementation assignment to the same worker. Use this path
  only when that follow-up keeps the pinned model. When that continuation is unavailable, skip the two-phase
  path and use the session fallback. Recheck the settings after any resume.
- In both cases, keep the settings inspection before the first invocation and read the subagent record to confirm
  the actual model and effort before accepting delegated work.
- The host limit is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main
  session. Use its current value and open slots; never change it.
- A missing plugin worker or a missing subagent record stops the affected delegation. Apply the session fallback.
