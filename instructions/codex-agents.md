# Codex agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing and worker rules below.

Read [shared model routing](model-routing.md) before dispatching a skill review role or Skill Builder participant,
selecting an independent reviewer, or dispatching for the first time after a main-model or profile switch or session
resume; in the last case, apply its effective-settings checks first. Other dispatches need only this file.

## Built-in agents

- Never use the built-in `default` or `explorer` agents. Always pass `agent_type`, because an omitted type runs
  `default`.
- The session hook installs the plugin's `scout`, `worker`, `designer`, and `reviewer` roles in
  `~/.codex/agents/` when absent. It replaces only unmodified copies from earlier plugin versions and never overwrites
  a file the user changed. The roles become available in the next Codex session.
- The plugin's agent guard hook denies an omitted type, `default`, `explorer`, and every type without a role
  file in a Codex agents directory, so it also denies the built-in `worker` until the plugin role exists.

## Investigation

- Use the `scout` agent for bounded, read-only investigation whenever the session delegation rule selects it,
  during planning or execution.
- Pass `gpt-5.6-luna` and `xhigh` explicitly on every spawn. Its bundled role file sets no model, so the spawn
  value applies.
- Before relying on its result, verify it under the spawned role verification section below.
- Give it one specific question and a narrow search scope.
- Require file paths, code symbols, and concrete evidence in its result.
- Treat results as leads. Verify critical claims in the main session before planning or deciding.
- If `scout` is unavailable, or its role file in the Codex agents directory sets another model or effort,
  investigate in the main session.
- For bounded public research, run the `researcher` role of the role runner when web search is available:
  `python3 <Source directory>/scripts/role_runner.py researcher --assignment <file> --result <file>`. It uses
  `gpt-5.6-luna` and `xhigh` through web search and verifies them from the session record. Otherwise, continue in the
  main session.

## Skill workers

- For one skill-assigned review role, including a review persona, grader, comparator, or analyzer, run the capability
  runner from the repository root with its role file and the assignment file:

  ```text
  python3 <Source directory>/scripts/role_runner.py review --host codex --instructions <role file> --assignment <file> --result <file>
  ```

  Accept the result file only on exit 0; the runner verifies the model from the host record. On runner exit 3 or 4,
  spawn the plugin `reviewer` role with `gpt-6.1-sol` and `xhigh` passed explicitly. Verify it under the spawned role
  verification section below.
- Send a local-evidence research ticket to `scout` and bounded public research to the `researcher` runner role when
  web search is available and its settings are verified. Private or authenticated remote access, including external
  tool work such as issue trackers and pull request services, goes to the `implementation` capability, and edits go to
  the capability worker a skill names; otherwise keep them in the main session.
- For Skill Builder, trial execution and other non-review participants use the host's upper model from its evaluation
  adapter. Do not route a review role through `scout` or a trial-output writer.
- When a skill asks for a worker that writes trial outputs, run a separate `codex exec` process with the model and
  effort that the skill pins.

## Implementation

Coordinate delegated implementation under [implementation delegation rules](implementation-delegation.md).
This section adds only the Codex worker integration.

- When delegating implementation, use only the plugin `worker` role. Its role file sets no model, so pass the model and
  effort from the session line "Codex worker model" explicitly on every spawn.
- Full-history forks inherit the parent model and effort and reject overrides. Never spawn a worker that way;
  set `fork_turns` to `"none"` or a positive integer, or leave `fork_context` off, and put the bounded task
  context in the assignment.
- Before the first spawn in a run, inspect only the `model`, `model_reasoning_effort`, and relevant `[agents]`
  default fields of the configuration layers, including the `worker` role file in the personal or project Codex
  agents directory. That file may override spawn values; it must still resolve to that model and effort.
- Never overwrite an existing `~/.codex/agents/worker.toml` or `.codex/agents/worker.toml`, and never change
  global model defaults.
- Accept the worker's result only after the spawned role verification section below passes.
- The spawn result does not name the model, so follow the readiness-only path in implementation delegation and
  send the implementation assignment to the same worker thread with a follow-up.
- The host limit is `agents.max_concurrent_threads_per_session`, which counts spawned threads but not the main
  thread. Use its current value and open slots; never change it.
- Missing worker tools, a missing `worker` role file, an unavailable model or effort, an incompatible user
  configuration, or unverified effective settings stop the affected delegation. Apply the session fallback.
- Codex spawns sub-agents only when the user, `AGENTS.md`, or skill instructions ask for them. The plugin's
  session hook keeps a marked block in `~/.codex/AGENTS.md` that grants this; it is removed when
  `HEI5ENBUG_SUBAGENT_POLICY=off` and takes effect from the next session. When authorization is absent,
  continue in the main session under the session fallback.
- The hook also enables `default_mode_request_user_input`, so `request_user_input` works in Default mode from the
  next session.

## Design work

For the `design` capability (UI code, visual design, diagrams or images, and technical design document drafting), use
its `codex` entry in the [capability table](model-routing.md#capability-pins). The primary is the plugin `designer` role
with `gpt-6-astra` and `xhigh` passed explicitly on the spawn; verify it under the spawned role verification section
below. When that route fails, run the fallback once through the role runner from the repository root:

```text
python3 <Source directory>/scripts/role_runner.py agent --name designer --fallback --host codex --add-dir <allowed path> --assignment <file> --result <file>
```

- Request network access through the normal Codex approval flow if the sandbox blocks it.
- On runner exit 3 or 4, continue in the main session.

## Spawned role verification

Accept a spawned role's result only after its rollout verifies. When the role finishes, run this from the session
folder, where `<Source directory>` is the line in the session context, and pass the `task_name`, model, and effort
you gave `spawn_agent`, plus the role's `sandbox_mode` from its TOML:

```text
python3 <Source directory>/scripts/verify_spawn.py --parent "$CODEX_THREAD_ID" --agent-path /root/<task_name> --model <model> --effort <effort> --sandbox <sandbox_mode>
```

- Exit 0 verifies the rollout. Use the result.
- Exit 2 means the call was wrong. Fix it and run it again.
- Exit 4 means the rollout is missing or names another model, effort, or sandbox. Do not respawn it with another pair,
  because the agent guard denies a fallback pair in Codex. Run the role's fallback through the runner as the Fallback
  section below describes, or continue in the main session.

## Run a capability

Look up the capability's entry for `codex` in the [capability table](model-routing.md#capability-pins). The five
capabilities are `investigation`, `implementation`, `design`, `language`, and `review`. The fallback rules in the
Fallback section below apply.

- `via: runner`: run the capability runner described below.
- `via: agent`: spawn the agent named in the entry's `agent` field, passing the entry's `model` and `effort`
  explicitly. For the `implementation` capability's `worker`, pass the model and effort from the session line
  "Codex worker model" instead. Then verify it under Spawned role verification above.
- If that route fails, use the capability's fallback entry once, then continue in the main session.

## Capability runner

Codex calls the role runner for a capability whose entry is `via: runner`, such as a Claude model capability:

```text
python3 <Source directory>/scripts/role_runner.py <capability> --host codex --instructions <file> --assignment <file> --result <file>
```

The runner runs the entry that [the capability table](model-routing.md) selects for `--host codex`, and `--fallback`
selects the fallback entry. When that entry is not `via: runner`, the runner exits 2, so use the agent route or the
main session instead. `--resume <session_id>` continues a Codex or Claude run from the `evidence.session` in its status
line. The status line and exit codes match [Claude Code agents](claude-agents.md#role-runner).

## Fallback

Every fallback is the other model family; a fallback that needs the other host's model runs through the role runner, and
one the current host can run in-host uses the named agent. A plugin agent's cross-family fallback runs
`python3 <Source directory>/scripts/role_runner.py agent --name <name> --fallback`, and a capability fallback with
`via: runner` runs `python3 <Source directory>/scripts/role_runner.py <capability> --host codex --fallback`. Pass `--mcp`
only when the assignment needs MCP tools or network. On runner exit 3 or 4, continue in the main session.
