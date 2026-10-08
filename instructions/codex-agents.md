# Codex planning and agents

Plan in the main session's plan mode.

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing and worker rules below.

Before dispatching an agent or model runner, read [shared model routing](model-routing.md), following the
instruction-reuse rules in [work efficiency](work-efficiency.md). After a main-model or profile switch or
session resume, apply its effective-settings checks before dispatch.

## Built-in agents

- Never use the built-in `default` or `explorer` agents. Always pass `agent_type`, because an omitted type runs
  `default`.
- The session hook installs the plugin's `scout`, `worker`, `researcher`, `designer`, and `reviewer` roles in
  `~/.codex/agents/` when absent. It replaces only unmodified copies from earlier plugin versions and never overwrites
  a file the user changed. The roles become available in the next Codex session.
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
- For bounded public research, use `researcher` only when public search and fetch tools are exposed. Pass `gpt-6-luna`
  and `xhigh` explicitly on every researcher spawn; its role file sets no model. Before relying on its result, inspect
  the non-secret researcher role/config settings and verify the host rollout record reports `gpt-6-luna` and `xhigh`.
  Otherwise, continue in the main session.

## Skill workers

- For one skill-assigned review role, including a review persona, grader, comparator, or analyzer, run this command
  from the repository root with the assignment on stdin:

  ```text
  claude -p --model claude-opus-5-5 --effort high --output-format json --tools Read Grep Glob --strict-mcp-config --permission-mode dontAsk --allowedTools Read Grep Glob
  ```

  Accept its result only when the JSON `modelUsage` names `claude-opus-5-5`. If `claude` is missing, not logged in,
  fails with an authentication, usage-limit, model, or timeout error, or that evidence is missing, spawn the plugin
  `reviewer` role with `gpt-6.1-sol` and `xhigh` passed explicitly. Verify its rollout record reports those settings
  and report the substitution once. The reviewer returns findings only. The main session reviews the same material
  once and makes the final decision; do not run another review round.
- Send a local-evidence research ticket to `scout` and bounded public research to `researcher` when public tools are
  available and its settings are verified. Keep private or authenticated remote access in the main session.
- For Skill Builder, trial execution and other non-review participants use the host's upper model from its evaluation
  adapter. Do not route a review role through `scout` or a trial-output writer.
- When a skill asks for a worker that writes trial outputs, run a separate `codex exec` process with the model and
  effort that the skill pins.

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
- Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them. The plugin's
  session hook keeps a marked block in `~/.codex/AGENTS.md` that grants this; it is removed when
  `HEI5ENBUG_SUBAGENT_POLICY=off` and takes effect from the next session. When authorization is absent,
  continue in the main session under the session fallback.
- The hook also enables `default_mode_request_user_input`, so `request_user_input` works in Default mode from the
  next session.

## Design work

For UI code, visual design, and diagram work, run a separate process from the repository root with the assignment
on stdin:

```text
claude -p --model claude-opus-5-5 --effort xhigh --output-format json --permission-mode dontAsk --allowedTools Read Grep Glob "Edit(<allowed path>/**)" "Write(<allowed path>/**)"
```

- Request network access through the normal Codex approval flow if the sandbox blocks it.
- Accept the result only when the JSON `modelUsage` names `claude-opus-5-5`.
- When `claude` is missing, the process ends with an authentication, usage-limit, or model error, or that
  evidence is missing, spawn the plugin `designer` role with `gpt-6-astra` and `xhigh` instead. Verify its
  rollout record as for `worker`, and report the substitution.
