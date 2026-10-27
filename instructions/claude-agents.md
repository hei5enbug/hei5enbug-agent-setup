# Claude Code agents

The reviewer invocation governed by [independent model validation](independent-model-validation.md) is an
exception to the timing, agent-selection, and worker rules below.

Read [shared model routing](model-routing.md) before dispatching a skill review role or Skill Builder participant,
selecting an independent reviewer, or dispatching for the first time after a main-model or profile switch or session
resume; in the last case, apply its effective-settings checks first. Other dispatches need only this file.

## Built-in subagents

- Never use a built-in subagent, including `general-purpose`, `Explore`, `Plan`, `claude`, or a fork. The
  exceptions are `claude-code-guide` and `statusline-setup`, which have narrow purposes that do not overlap
  `scout` or `worker`. Always name the subagent type, because an omitted type runs `general-purpose`.
- The denial belongs to the plugin's Claude Code mod. It hides `general-purpose`, `Explore`, `Plan`, and `claude`
  from the agent list and denies them, an omitted type (which runs `general-purpose`), and every fork; every
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
line. Never run `cd` before it. Add `--model <id>` only for `reviewer` and `--add-dir <dir>` only for `worker`, a
writing capability, or a `write` agent. Add `--effort xhigh` only under the effort rule in
[shared model routing](model-routing.md#keep-role-settings-fixed). For several read-only assignments of one target,
repeat `--assignment` and `--result` in one call; the runner runs up to six in parallel and prints one status line
each.

Agent mode runs a plugin agent's cross-family fallback, and takes the agent's registry name, or a role an installed
plugin declares, in place of a role:

```text
python3 <Source directory>/scripts/role_runner.py agent --name <name> --fallback --assignment <file> --result <file>
```

Add `--add-dir <dir>` for each directory a `write` agent may edit, and `--mcp` only when the assignment needs MCP tools
or network.

The same command also takes a capability name from the registry in place of a role. `--instructions <file>` then
supplies the role definition. The runner runs the entry that [the capability table](model-routing.md) selects for
`--host claude|codex`. Without `--host`, the default is `codex` when `CODEX_THREAD_ID` is set and `claude` otherwise.
`--fallback` selects the fallback entry. When that entry is not `via: runner`, the runner exits 2, so use the agent
route or the main session instead. `--resume <session_id>` continues a Claude or Codex run from the `evidence.session`
in its status line, with the same model, effort, and sandbox settings.

| Exit | Action |
|---|---|
| 0 | Accept the result file. |
| 2 | Fix the call and run it again. |
| 3 or 4 | Read no result file and use the fallback below. |

| Role | Fallback after exit 3 or 4 |
|---|---|
| `scout` | `hei5enbug-agent-setup:scout` |
| `researcher` | `hei5enbug-agent-setup:scout`, only when public search and fetch tools are available |
| `reviewer` for a skill review role | `hei5enbug-agent-setup:reviewer` |
| `reviewer` for independent validation | None. Report that independent validation was not performed. |
| `worker` | Inspect the partial diff, then `hei5enbug-agent-setup:worker` |

When the fallback is unavailable too, continue in the main conversation.

## Run a capability

Look up the capability's entry for `claude` in the [capability table](model-routing.md#capability-pins). The five
capabilities are `investigation`, `implementation`, `design`, `language`, and `review`. The fallback rules in the
Fallback section below apply.

- `via: runner`: run the capability through the role runner above, with `--instructions <file>`.
- `via: agent`: spawn the agent named in the entry's `agent` field. The entry's `pin` names the agent pin it uses.
  After a failed run, the next spawn of that agent is denied once, and the denial names the runner fallback command.
- If that route fails, use the capability's fallback entry once, then continue in the main conversation.

## Fallback

Every fallback is the other model family; a fallback that needs the other host's model runs through the role runner, and
one the current host can run in-host uses the named agent. A plugin agent's cross-family fallback runs
`role_runner.py agent --name <name> --fallback`, and a capability fallback with `via: runner` runs
`role_runner.py <capability> --fallback`. Pass `--mcp` only when the assignment needs MCP tools or network. On runner
exit 3 or 4, continue in the main conversation.

## Investigation

- For bounded investigation that the session delegation rule selects, during planning or execution, run the
  `scout` role. Give each scout one question and one narrow search scope.
- Require file paths, code symbols, and concrete evidence in its results.
- Treat results as leads. Verify critical claims in the main conversation before planning or deciding.
- For bounded public research, use the `investigation` capability's route in the capability table. Its Claude
  fallback is the `scout` agent, which has web search and fetch tools. Otherwise, continue in the main conversation.

## Skill workers

- A skill review role is read-only judgment work, including a review persona, grader, comparator, or analyzer. Run
  the `reviewer` role with `--model` set to the model in the session line "Review model".
- Independent validation, when it is due under independent model validation, runs the `reviewer` role with `--model`
  and effort set to the reviewer that file selects. The "Review model" line does not apply to it.
- Send a local-evidence research ticket or bounded public research through the `investigation` capability.
  Do not use `scout` for a review role. Private or authenticated remote access, including external tool work such as
  issue trackers and pull request services, goes to the `implementation` capability, and edits go to the capability
  worker a skill names; otherwise keep them in the main conversation.
- For Skill Builder, trial execution and other non-review participants use the host's upper model in its evaluation
  adapter. When a skill asks for a worker that writes trial outputs, run a separate `claude -p` process with the
  model and effort that the skill pins.

## Implementation

Coordinate delegated implementation under [implementation delegation rules](implementation-delegation.md).
This section adds only the Claude Code worker integration.

- Delegated implementation follows the route in the session line "Implementation worker route". Use
  `hei5enbug-agent-setup:sonnet-worker` for the Sonnet worker when the line says `sonnet`, the Codex worker (see
  "Codex worker" below) when it says `codex`, `hei5enbug-agent-setup:worker` when it says `haiku`, and the Sol
  worker (see "Sol worker" below) when it says `sol`. When it says `auto`, choose per assignment: the `worker`
  agent for easy work (one cohesive change with a stated edit and checks that cover it fully) and the Sonnet worker
  for normal or hard work (a behavioral change, several files, parsing, security, or concurrency). When a Claude
  route fails or stops on a usage limit, use the Sol worker. A user request for one route applies to that request
  only.
  `hei5enbug-agent-setup:designer` still takes UI code,
  visual design, and diagram work, except the kinds the Claude Code session file assigns to the main session. Never
  use any other agent.
- The `worker` agent runs on the model and effort in the session line "Worker agent model" (Haiku at `high` by
  default).
- Never pass a per-invocation model to a plugin agent on an invocation or resume, because that overrides its
  definition, which pins the model and effort that shared model routing lists.
- The bullets below apply whenever a plugin agent runs: a runner fallback, the `worker` or Sonnet worker, and the
  designer.
- When the session context has the line `hei5enbug-agent-setup mod: role pinning active`, the registered plugin mod's
  `prompt.submit` hook, which adds it to the first prompt of each conversation, confirms role pinning is active. The mod pins each role's model and effort on every subagent
  request, from the registry and from installed plugins' declared `model-roles.json` files. It fails a run whose
  response came from another model or carried no model evidence: the run's later turns are refused, and the mod blocks
  tool calls from a subagent that answered on another model. A failed run's result is replaced by a warning, and the
  next spawn of that role is denied once, naming the runner fallback command, before later spawns use the primary pin
  again. A run whose Agent call returns an error,
  or whose final turn ends in an error, is marked failed the same way, but its error result is kept.
  Once per session, check only forced-model and effort limits: `CLAUDE_CODE_SUBAGENT_MODEL`,
  `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, effort overrides such as `CLAUDE_CODE_EFFORT_LEVEL`, and effort caps such as
  `maxEffortLevel` or organization limits, in the environment and every settings file. Read the environment
  variables by name with `printenv <name>...`, never with `env` or a pattern search, which the approval guard asks
  about as a sensitive read. A forced model or a cap below the pinned effort stops plugin-agent delegation. Otherwise send each assignment directly. The mod's pinning
  and blocking are the acceptance evidence, so read no settings or subagent record per delegation.
- Without that line, the launch result does not name the model. Before the first invocation in a run, inspect only
  the non-secret inputs above plus the agent definition and any substitution or fallback warning, and follow the
  readiness-only path in implementation delegation. Claude Code can reload settings during a session, so recheck
  them before every follow-up that carries implementation work.
- Without the mod line, accept the host's subagent record only when it names the invoked definition's pinned model
  and effort. Read it from `projects/<project>/<session-id>/subagents/agent-<agentId>.jsonl` under the Claude config
  directory, `CLAUDE_CONFIG_DIR` or `~/.claude`, where each assistant entry's `model` and `effort` must match.
  Provider-internal reasoning telemetry is not required. A different recorded model, a cap below the pinned effort,
  a contradictory override, or unknown effective precedence is insufficient.
- The host limit is `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main
  session. Use its current value and open slots; never change it.
- A missing plugin worker or a missing subagent record stops the affected delegation. Apply the session fallback.
  Never change user settings.

## Sol worker

- Write the assignment, with the usual assignment fields, to a file and run
  `python3 <Source directory>/scripts/role_runner.py implementation --fallback --instructions
  <Source directory>/agents/worker.md --assignment <file> --result <file>` from the folder that holds the allowed
  paths. It runs the model that the capability table in shared model routing lists as the Claude Code fallback,
  with write access to that folder.
- Add `--add-dir <dir>` only for a directory outside that folder that the task must write. The approval guard asks
  for the session write approval once.

## Codex worker

- Write the assignment, with the usual assignment fields, to a file and run the `worker` role.
- Add `--add-dir <dir>` only for a directory outside the session folder that the task must write. The plugin mod
  asks once per session.
