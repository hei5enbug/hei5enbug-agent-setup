# Codex planning and agents

Plan in the main session's plan mode.

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing and worker rules below.

## Investigation

- Use the built-in `explorer` only for bounded, read-only investigation while planning, and only when the
  session delegation threshold is met.
- Give it one specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat results as leads. Verify critical claims in the main session before planning or deciding.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Codex worker integration.

- Use only the built-in `worker` agent type for implementation, and pass the resolved model and `xhigh`
  explicitly on every spawn.
- The required family is the latest production GPT Luna. Resolve it from the model guidance in the
  [Codex subagent page](https://learn.chatgpt.com/docs/agent-configuration/subagents), the
  [OpenAI model catalog](https://developers.openai.com/api/docs/models), and the Luna model page it links.
  Cross-check the ID and `xhigh` support against the host's model selector or catalog.
- Full-history forks inherit the parent model and effort and reject overrides. Never spawn a worker that way;
  set `fork_turns` to `"none"` or a positive integer, or leave `fork_context` off, and put the bounded task
  context in the assignment.
- Before the first spawn in a run, inspect only the `model`, `model_reasoning_effort`, and relevant `[agents]`
  default fields of the configuration layers, including any user-defined `worker` in the personal or project
  Codex agents directory. Such a definition may override spawn values; it must still resolve to the selected
  model and `xhigh`.
- Never install or overwrite `~/.codex/agents/worker.toml` or `.codex/agents/worker.toml`, and never change
  global model defaults.
- Accept the explicit spawn arguments plus the worker's rollout record as evidence. Find the record in the
  sessions directory under `CODEX_HOME`, which defaults to `~/.codex`: its `session_meta` names the parent
  thread from the coordinator's `CODEX_THREAD_ID` and the worker's agent path, and its `turn_context` names
  the actual `model` and `effort`. A worker's self-report is not this record.
- The spawn result does not name the model, so start each worker with a readiness-only assignment. After its
  record passes, send the implementation assignment to the same worker thread with a follow-up. Use this path
  only when that follow-up keeps its settings. When that continuation is unavailable, skip the two-phase path
  and make no edits. Recheck the settings after any resume.
- The host limit is `agents.max_concurrent_threads_per_session`, which counts spawned threads but not the main
  thread. Use its current value and open slots; never change it.
- Missing worker tools, an unavailable model or `xhigh`, an incompatible user configuration, or unverified
  effective settings block the affected implementation. Report the exact capability and make no edit.
- Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them, and these rules
  arrive through a hook. If you decline to spawn for that reason, ask the user once to authorize worker
  delegation and make no edit until they answer.
