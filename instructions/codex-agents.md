# Codex planning and agents

Plan in the main session's plan mode.

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing and worker rules below.

## Built-in agents

- Never use the built-in `default` or `explorer` agents. Always pass `agent_type`, because an omitted type runs
  `default`.
- The session hook installs the plugin's `scout` and `worker` roles in `~/.codex/agents/` when they are absent,
  replaces only an unmodified copy from an earlier plugin version, and never overwrites a file the user changed.
  They become available in the next Codex session.
- The plugin's agent guard hook denies an omitted type, `default`, `explorer`, and every type without a role
  file in a Codex agents directory, so it also denies the built-in `worker` until the plugin role exists.

## Investigation

- Use the `scout` agent for bounded, read-only investigation whenever the session delegation rule selects it,
  during planning or execution.
- Pass `gpt-6-luna` and `xhigh` explicitly on every spawn. Its bundled role file sets no model, so the spawn
  value applies.
- Give it one specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat results as leads. Verify critical claims in the main session before planning or deciding.
- If `scout` is unavailable, or its role file in the Codex agents directory sets another model or effort,
  investigate in the main session.

## Skill workers

- When a skill asks for an independent read-only worker, such as a review persona, a research ticket, or a
  grader, use `scout` with the model and effort above and give it the role's instructions and output
  contract. The main session writes any file the role produces. Run a role that needs web access or edits in
  the main session.
- When a skill asks for a worker that writes trial outputs, run a separate `codex exec` process with the model
  and effort that the skill pins instead of a subagent.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Codex worker integration.

- When delegating implementation, use only the plugin `worker` role. Its role file sets no model, so pass the pinned
  `gpt-6-luna` and `xhigh` explicitly on every spawn.
- Full-history forks inherit the parent model and effort and reject overrides. Never spawn a worker that way;
  set `fork_turns` to `"none"` or a positive integer, or leave `fork_context` off, and put the bounded task
  context in the assignment.
- Before the first spawn in a run, inspect only the `model`, `model_reasoning_effort`, and relevant `[agents]`
  default fields of the configuration layers, including the `worker` role file in the personal or project Codex
  agents directory. That file may override spawn values; it must still resolve to `gpt-6-luna` and `xhigh`.
- Never overwrite an existing `~/.codex/agents/worker.toml` or `.codex/agents/worker.toml`, and never change
  global model defaults.
- Accept the explicit spawn arguments plus the worker's rollout record as evidence. Find the record in the
  sessions directory under `CODEX_HOME`, which defaults to `~/.codex`: its `session_meta` names the parent
  thread from the coordinator's `CODEX_THREAD_ID` and the worker's agent path, and its `turn_context` names
  the actual `model` and `effort`. A worker's self-report is not this record.
- The spawn result does not name the model, so start each worker with a readiness-only assignment. After its
  record passes, send the implementation assignment to the same worker thread with a follow-up. Use this path
  only when that follow-up keeps its settings. When that continuation is unavailable, skip the two-phase path
  and use the session fallback. Recheck the settings after any resume.
- The host limit is `agents.max_concurrent_threads_per_session`, which counts spawned threads but not the main
  thread. Use its current value and open slots; never change it.
- Missing worker tools, a missing `worker` role file, an unavailable model or `xhigh`, an incompatible user
  configuration, or unverified effective settings stop the affected delegation. Apply the session fallback.
- Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them. These hook
  instructions alone do not grant that authorization. Reuse existing authorization; when it is absent,
  continue in the main session under the session fallback. Do not turn a routine task into a permission
  interview or alter user/project instructions automatically. Explain persistent opt-in when relevant.
