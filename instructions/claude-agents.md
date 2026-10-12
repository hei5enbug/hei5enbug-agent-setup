# Claude Code agents

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

## Role runner

Run the scout, researcher, reviewer, and Codex worker roles through the role runner. Write the assignment to a
file, then run this from the session folder, in the background when other work can continue, where
`<Source directory>` is the line in the session context:

```text
python3 <Source directory>/scripts/role_runner.py <scout|researcher|reviewer|worker> --assignment <file> --result <file>
```

It runs the role on its pinned model, effort, and permissions, verifies the host record, and ends with one JSON
line. Never run `cd` before it. Add `--model <id>` only for `reviewer` and `--add-dir <dir>` only for `worker`.

| Exit | Action |
|---|---|
| 0 | Accept the result file. |
| 2 | Fix the call and run it again. |
| 3 or 4 | Read no result file and use the fallback below. |

| Role | Fallback after exit 3 or 4 |
|---|---|
| `scout` | `hei5enbug-agent-setup:scout` |
| `researcher` | `hei5enbug-agent-setup:researcher`, only when public search and fetch tools are available |
| `reviewer` for a skill review role | `hei5enbug-agent-setup:reviewer` |
| `reviewer` for independent validation | None. Report that independent validation was not performed. |
| `worker` | Inspect the partial diff, then `hei5enbug-agent-setup:worker` |

When the fallback is unavailable too, continue in the main conversation.

## Investigation

- For bounded investigation that the session delegation rule selects, during planning or execution, run the
  `scout` role. Give each scout one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- For bounded public research, run the `researcher` role, which uses the web search tool and no shell network.
  Otherwise, continue in the main conversation.

## Skill workers

- A skill review role is read-only judgment work, including a review persona, grader, comparator, or analyzer. Run
  the `reviewer` role with `--model` set to the model in the session line "Review model".
- Independent validation, after the user approves it under independent model validation, runs the `reviewer` role
  with `--model` set to the reviewer that file selects. For a Claude-authored result, that is the "Review model"
  line.
- Send a local-evidence research ticket to the `scout` role and bounded public research to the `researcher` role.
  Do not use `scout` for a review role. Keep private or authenticated remote access and all edits in the main
  conversation.
- For Skill Builder, trial execution and other non-review participants use the host's upper model in its evaluation
  adapter. When a skill asks for a worker that writes trial outputs, run a separate `claude -p` process with the
  model and effort that the skill pins.

## Implementation

Coordinate implementation under [implementation execution rules](implementation-execution.md). This section
adds only the Claude Code worker integration.

- Delegated implementation follows the route in the session line "Implementation worker route". Use
  `hei5enbug-agent-setup:sonnet-worker` for the Sonnet worker by default, the Codex worker (see "Codex worker"
  below) when the line says `codex`, and `hei5enbug-agent-setup:worker` for the Haiku worker when it says `haiku`. A
  user request for one route applies to that request only. `hei5enbug-agent-setup:designer` still takes UI code,
  visual design, and diagram work, except the kinds the Claude Code session file assigns to the main session. Never
  use any other agent.
- Never pass a per-invocation model to a plugin agent on an invocation or resume, because that overrides its
  definition, which pins the model and effort that shared model routing lists.
- The bullets below apply whenever a plugin agent runs: a runner fallback, the Haiku or Sonnet worker, and the
  designer.
- When the session context has the line `hei5enbug-agent-setup mod: role pinning active`, the registered plugin mod's
  `prompt.context` hook confirms role pinning is active. The mod pins each role's model and effort on every request and
  blocks tool calls from a subagent that answered on another model.
  Once per session, check only forced-model and effort limits: `CLAUDE_CODE_SUBAGENT_MODEL`,
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, effort overrides such as `CLAUDE_CODE_EFFORT_LEVEL`, and effort caps such as
  `maxEffortLevel` or organization limits, in the environment and every settings file. A forced model or a cap
  below the pinned effort stops plugin-agent delegation. Otherwise send each assignment directly. The mod's pinning
  and blocking are the acceptance evidence, so read no settings or subagent record per delegation.
- Without that line, the launch result does not name the model. Before the first invocation in a run, inspect only
  the non-secret inputs above plus the agent definition and any substitution or fallback warning, and follow the
  readiness-only path in implementation execution. Claude Code can reload settings during a session, so recheck
  them before every follow-up that carries implementation work.
- Accept the host's subagent record, such as `/tasks` or the subagent transcript, only when it names the invoked
  definition's pinned model and effort. Provider-internal reasoning telemetry is not required. A different recorded
  model, a cap below the pinned effort, a contradictory override, or unknown effective precedence is insufficient.
- Read that record from the transcripts under the Claude config directory, `CLAUDE_CONFIG_DIR` or `~/.claude`,
  in `projects/<project>/`. The session transcript's launch result names the worker's `agentId` and
  `resolvedModel`, and `<session-id>/subagents/agent-<agentId>.jsonl` names `model` and `effort` on each
  assistant entry.
- The host limit is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main
  session. Use its current value and open slots; never change it.
- A missing plugin worker or a missing subagent record stops the affected delegation. Apply the session fallback.
  Never change user settings.

## Codex worker

- Write the assignment, with the usual assignment fields, to a file and run the `worker` role.
- Add `--add-dir <dir>` only for a directory outside the session folder that the task must write. The plugin mod
  asks once per session for each such directory.
