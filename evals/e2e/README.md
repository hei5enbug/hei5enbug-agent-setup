# End-to-end golden evaluation

This harness measures the plugin as a whole coding-agent harness. Each run starts `claude -p` with one plugin
revision loaded, gives it a realistic development task in a throwaway fictional repository, and grades the result.
Two variants run the same tasks under the same conditions, so their results can be compared. A run can use Claude Code
or Codex as the agent host (`--hosts`), and a change to the plugin is judged on both.

The harness runs real agent sessions and spends real model usage. It is not one of the development checks in the
repository README; only its unit tests are.

## What one run does

1. The harness exports the variant's plugin revision with `git archive <ref>` into
   `<run root>/plugins/<sha>/hei5enbug-agent-setup/`. The export leaves out `evals/`, its Korean mirror
   `docs/ko/evals/`, and `tests/test_e2e_eval_*.py`, so an agent that reads the plugin source cannot see the hidden
   tests, the reference solutions, or expected answers.
2. It copies the task's fixture from `fixtures/` into `<run root>/<campaign>/work/<run id>/repo/`, commits it with a
   fixed fictional identity and date, and runs the task's setup script when it has one. A setup script may build
   more state beside the repository, in `<run root>/<campaign>/work/<run id>/`, and a task's `env` map gives the agent
   environment values in which `{repo}`, `{work}`, and `{PATH}` stand for the repository, that folder, and the current
   `PATH`. The variant's `env` and the configuration's `extra_env` still win over it.
3. It starts the agent in that folder:

   ```text
   claude -p --model claude-opus-5-5 --effort high --output-format stream-json --verbose
     --include-hook-events --plugin-dir <exported plugin> --settings <run>/settings.json
     --setting-sources project,local --mcp-config <run>/mcp.json --strict-mcp-config
     --permission-prompt-tool mcp__eval_approver__approve --max-budget-usd <task limit> -- <prompt>
   ```

   The prompt follows `--`, so a prompt that starts with a dash, such as `--version ...`, is not read as an option.

   `settings.json` turns off the installed `hei5enbug-agent-setup@hei5enbug` plugin and every other plugin that the
   profile's `plugins/installed_plugins.json` or `settings.json` lists, so only the variant loaded through `--plugin-dir`
   runs; `--strict-mcp-config` limits MCP servers to the harness approver. The rest of the user's environment stays as
   it is, including the default permission mode and Codex. The harness removes the `ORCA_*` variables, so a run cannot
   report to or message the Orca terminal that started it, and `CLAUDE_CODE_PLUGIN_DIRS`, which would load further
   plugins as `--plugin-dir` does. A run whose `system` init event lists a plugin other than the variant is recorded as
   `infra_failed` with the extra plugin names and is not graded, and `pilot-check` fails it. Plugins built into Claude
   Code itself, whose source ends with `@builtin`, are part of the host and do not count. It never passes a bypass
   mode, `--bare`, or `--permission-mode`.

   The run also reads none of the user's own instructions, as a Codex run with its own `CODEX_HOME` reads none.
   `--setting-sources project,local` leaves out the `user` source, so the profile's `CLAUDE.md`, its `rules/` folder,
   and its `settings.json` do not load, while the project's own `CLAUDE.md` or `AGENTS.md`, `.claude/rules/`, and
   `CLAUDE.local.md` load as the fixture defines them; the run's own settings still arrive through `--settings`. The
   same source switch also leaves out the user's skills, commands, agents, hooks, and permission rules. The variable
   `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` turns off auto memory, which no setting source controls, and comes last, so no
   variant `env` turns it back on. The controls came from the Claude Code memory, settings, and CLI documentation, and
   no file of the profile changes. Two inputs have no switch and stay a known limit: managed settings and a managed
   `CLAUDE.md` of the machine, and the global `~/.claude.json`. `env.json` records the sources, the variable, and
   these limits under `instruction_isolation`. `pilot-check` fails a run whose command line does not name
   `--setting-sources` without `user`, whose `env.json` lacks the variable, whose transcripts carry an instruction
   file of the `User` type (it names the path), or whose init event shows `memory_paths.auto`.

   Claude Code also loads `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, `AGENTS.md`, and `.claude/rules/` of
   every directory above the working directory as project memory, whatever the sources say, so a run folder under
   the home folder would read the profile's own rules. `settings.json` therefore carries `claudeMdExcludes` with
   those files of each ancestor of the trial repository, by its given and its resolved path, and the repository
   itself and below load as the fixture defines them. The memory documentation names `claudeMdExcludes` for this;
   its `managed-only` value would also drop the fixture's own files. A variant's own `claudeMdExcludes` entries
   stay, and the harness patterns are added. `pilot-check` also fails a run whose transcripts carry an instruction
   file of any type outside the trial repository and the exported plugin, and names the path.
4. A wall-clock limit per task stops the agent with SIGINT, then SIGTERM, then SIGKILL. The signals reach the
   agent's process group and every process it started in a session of its own, such as a role runner child, and the
   harness confirms that none is left.
5. After the run, the harness copies the main transcript, the subagent records, the role runner assignment files,
   the Claude transcripts of role runner runs, and the Codex rollouts that started in the run's folder during the
   run.
6. Deterministic graders check the final repository. Hidden tests are copied in only now, into a copy of the
   repository. Codex commands from the rollouts join the transcript view, so the graders see them too. Two tasks
   also get a blind rubric grade.
7. The harness writes `view.json`, `grade/grade.json`, and `metrics.json` next to the raw records.

### Approvals

The user answers permission prompts in real use. The harness stands in for the user with a small stdio MCP server,
`harness/approval_mcp.py`, passed as `--permission-prompt-tool`. It allows every Bash request. It denies a file-tool
request (`Write`, `Edit`, `MultiEdit`, `NotebookEdit`, or any request with a `file_path` or `notebook_path`) whose
path resolves outside the run's work folder, `work/<run id>/`, after `..` and symlinks are resolved. The denial
message names the path and the folder. A relative path starts in the agent's working directory,
`work/<run id>/repo/`. A request that is not a file tool, such as `Read`, may also lie inside the exported plugin folder the run loads, so the run can read its own conditional instruction files; no write outside the run folder is allowed. Every other request is allowed. The server logs each request, allowed or
denied, with its decision to `approvals.jsonl`. The number of lines is the approval-prompt count, a friction
metric, so a denied request still counts. An `mcp.json` without `EVAL_RUN_FOLDER` keeps the older allow-all
behavior. A plugin hook that returns `ask` reaches this tool; the pilot confirmed this with a forced `git clean -f`.
Measurement runs turn the plugin's approval guard off by default (see "Codex host"), so this happens only in a variant
that turns it on.
Calls that the permission mode or the plugin's guard allow without a prompt never reach it, so they are not counted.

The harness cannot answer a question that the agent asks with `AskUserQuestion`. The approver lets the call through,
and the run ends with the question unanswered. Task prompts therefore leave no decision open that would change the
result.

### Codex host

`--hosts claude,codex` runs each task on both hosts from the same exported revision, the same fixture copy, the same
prompt, the same limits, and the same graders and metrics. `claude` alone is the default. A Codex run starts
`codex exec` with `gpt-6.1-sol` at `high`, with this setup. The harness resolves `codex` to an absolute path from its own
`PATH` before the task's `env` is applied, so a task that puts a fake `codex` first on the agent's `PATH` (T102, T109) changes
only what the plugin's own role runner calls, never the host:

- Each run has its own `CODEX_HOME` in `<run>/codex-home/`, so no installed plugin or setting of the user's own
  Codex reaches it. `auth.json` is a symlink to the user's credential file, and the harness never reads, copies, or
  prints it. `HARNESS_CODEX_AUTH_HOME` names another folder that holds the file.
- The plugin loads from the exported revision only: `codex plugin marketplace add <export>` registers a local
  marketplace from the export, then `codex plugin add hei5enbug-agent-setup@<marketplace>` installs it into that
  `CODEX_HOME`. The setup commands and their results are in `codex-setup.json`.
- `--dangerously-bypass-hook-trust` is set because the harness exports and vets the revision itself, so the run does
  not stop to ask for trust of the plugin's hooks. Codex hooks still run.
- After the install, the harness trusts the exported plugin's hooks in the run's `CODEX_HOME` through `codex
  app-server`, so a role runner's own Codex child, which runs without the bypass flag, can verify them. A hook that
  stays untrusted fails the setup and the run is `infra_failed`. `codex-setup.json` lists the trusted hook keys.
- The harness also writes the plugin's bundled role files (`standalone-agents/codex-<role>.toml`) into the run's
  `CODEX_HOME/agents/` before the main session starts, as the plugin's session hook would for the next session. Without
  them the first session's `spawn_agent` tool lists no `agent_type`, so a role such as `worker` cannot be named. A file
  that already exists stays, and `codex-setup.json` lists the installed roles.
- Stdin is `/dev/null`, and `ZDOTDIR` is a folder with no user zsh startup files, so the shell Codex starts reads none
  of them. Its only file is a `.zprofile` that exports the run's `PATH`: on macOS `/etc/zprofile` runs `path_helper`,
  which moves the system folders to the front, so without it `python3` in a Codex shell resolves to an old system
  Python. The harness removes the `ORCA_*` variables here too.
- `codex exec` runs with `approval_policy` set to `never` and the `danger-full-access` sandbox, the same as the owner's
  own Codex setting. The plugin's Claude routes (`role_runner.py` starting `claude -p`) need the network and the
  Claude config folder, and the `workspace-write` sandbox has neither, so every Codex-to-Claude delegation failed
  there with "Not logged in".
- No approver stands in on Codex. Claude Code asks the permission-prompt tool when the plugin's approval guard answers
  "ask", but Codex has no such tool, so the same command would be blocked. Measurement runs therefore turn the guard
  off on both hosts: the harness sets `CLAUDE_PLUGIN_OPTION_APPROVAL_GUARD` and `HEI5ENBUG_APPROVAL_GUARD` to `false`
  in the agent environment of every run. A variant sets either variable in its `env` to override the default. The
  plugin's other hooks still run.
- Codex has no spend flag, so only the wall-time limit of the task is enforced.
- The harness reads the `exec` commands, `apply_patch` calls, and native `spawn_agent` calls of the rollouts as tool
  calls. A `spawn_agent` call counts as a subagent launch of the `agent_type` it names, or of `general-purpose` when it
  names none, and the order of a delegation and the order of the final answer count the same calls. A `spawn_agent`
  delegation counts as completed only once the child's final result for its `task_name` has come back to the parent
  as a `FINAL_ANSWER` message that is not an error; the spawn acknowledgement alone is not a result. A review counts as
  done before the report only when that message arrived before the last assistant message began.
- The model and effort of the session are read from the `turn_context` event of its rollout, not from the command
  line, and `env.json` records them with the Codex CLI version.

Results of a Codex run sit below `results/<task>/<variant>/codex/rep<k>/`, and its run id is
`<task>-<variant>-codex-r<k>`. The summary groups it as `<variant> [codex]`.

### Model cap

No role of a measurement may start a model stronger than `claude-opus-5-5`, `gpt-6.1-sol`, or `gpt-6.2-sol`. The allowed models are
`MODEL_CAP` in `harness/config.py`, and `harness/records.py` validates records against the same set. It includes `gpt-6.2-sol` and `gpt-6-luna` (owner decision of 2026-11-20), the pins of the GPT worker and the Luna family, and keeps `gpt-5.6-luna`, which the baseline revision's plugin still defaults to. `run` rejects a
campaign before it starts, also with `--dry-run`, and the message names the role and the model. This covers a main
model a variant sets, a plugin model option a variant sets, a plugin model option such as `review_model` that the
variant leaves at a default outside the cap, and the rubric grader. A variant that leaves `review_model` at its
default sets `CLAUDE_PLUGIN_OPTION_REVIEW_MODEL` and `HEI5ENBUG_REVIEW_MODEL` to a model within the cap in its `env`.
After a run, the harness scans the Claude stream, the Claude transcripts, the role runner status lines, and the Codex
rollouts; a model outside the cap that answered in the run sets `success` to false and is recorded as
`cap_violation`.

Fixed routes of the plugin, such as the registry's design and fallback routes, name models above the cap, and the checks
above cannot see them. So every exported plugin revision, the same for every variant, goes through a cap transform: in
the export only, every `claude-fable-*` id (such as `claude-fable-5-2`) becomes `claude-opus-5-5`, and every
`gpt-*-astra` and `gpt-*-terra` id (such as `gpt-6.2-astra` and `gpt-6.1-terra`) becomes `gpt-6.1-sol`, in `config/model-registry.json`, `agents/`, `.codex/`, `skills/`, and `instructions/` text files
(the revisions in git stay untouched). The harness then scans those files again and rejects the campaign when
any model outside the cap remains, with a message that names the file and the cap. The transform is `apply_cap_transform` in
`harness/plugin_export.py`. Each run's `env.json` records `cap_transform` (the replacements, which model ids were replaced,
and their count), `plugin-export.json` holds it with a digest of the transformed export, and that digest is part of the
campaign's input fingerprint, so a resume on a differently transformed export stops. A revision that an earlier harness
exported without the transform is exported again.

### Claude-only review stand-in

The final report hook asks for a `text_review.py review`, and that script calls the `gpt-6.1-sol` reviewer by default.
A run with no GPT reviewer available adds `--claude-review-stand-in` to `run` (or `export-plugin`). The export then
replaces the one `gpt-6.1-sol` literal in `scripts/text_review.py` with `claude-sonnet-5-5`, the same for every variant,
and rejects a revision where the literal is missing or appears more than once. Instructions, hooks, and commands stay
as in real use. The option is off by default, and its export lives in its own `plugins/<sha>-claude-review/` folder.
`env.json` records `review_stand_in` (the model, the file, and the replaced literal), the export digest carries it into
the input fingerprint, and a record marks each run that used it with `review_stand_in`. `env.json` also records
`grader_review_model`: the text graders review with the same model through the script's `--model` option, and with the
option off they keep the script's default. The reviewer is then Claude,
not independent of a Claude author, so compare only runs that used the same setting.

## Commands

Run every command from the repository root. The default run root is
`~/.local/state/hei5enbug-agent-setup/harness-eval/runs`; `--run-root` changes it.

| Goal | Command |
|---|---|
| Show the plan and exact commands | `python3 evals/e2e/harness/cli.py run --campaign <name> --dry-run` |
| Run or resume a campaign | `python3 evals/e2e/harness/cli.py run --campaign <name> --variants baseline --reps 3` |
| Run selected tasks | add `--tasks T01,T03` |
| Run on both hosts | add `--hosts claude,codex` |
| Rerun finished runs | add `--only-rerun T03-baseline-r1,T03-baseline-r2` |
| Grade again after a grader fix | `python3 evals/e2e/harness/cli.py regrade --campaign <name> [--run-ids ...]` |
| Copy the records again, then grade | add `--recollect` to `regrade` |
| Resume after changing a task or variant | add `--allow-changed-inputs` to `run` |
| Check the pilot facts per run, on both hosts; it fails when it checks no run | `python3 evals/e2e/harness/cli.py pilot-check --campaign <name>` |
| Print tables | `python3 evals/e2e/harness/cli.py summarize --campaign <name> [--out file.md]` |
| Compare two variants | `python3 evals/e2e/harness/cli.py summarize --campaign <name> --compare baseline,<other>` |
| Export a revision only | `python3 evals/e2e/harness/cli.py export-plugin --ref <ref>` |
| Judge a change and write its record | `python3 evals/e2e/harness/cli.py record --campaign <name> --issue <n> --before <variant> --after <variant> [--claim wall_seconds,cost_usd] [--tasks T08]` |

`--parallel` sets the number of runs at once (default 3). With several variants the order alternates per task and
repetition (ABAB, then BABA), so time-of-day effects spread evenly.

Running the same `run` command again resumes the campaign. Finished runs are skipped. A run that failed for an
infrastructure reason, hit a usage limit, or was interrupted is started again, and its old records and work folder
move to `attempts/rep<k>/<n>/`. When a run reports a usage limit, the harness starts no new run, lets running ones
finish, and exits with code 75.

A Claude Code run that printed its final `result`, has no background task left, and writes no stream line for
`result_idle_seconds` (default 60) is ended like a timeout but recorded as `complete` with `ended_after_result: true` and
the time of that result as its `wall_seconds`; a later stream line restarts the wait, and Codex runs are not affected.

An interrupt of the harness, such as Ctrl-C, starts no new run, stops each running agent and every process it started
as the wall-clock limit does, records that run as `interrupted`, and exits with code 130. A Claude Code run whose
stream ends with an aborted result is recorded as `interrupted` too: `claude -p` writes that result when it receives
SIGINT and then exits with code 0. An interrupt during grading ends the rubric grader and the grader's pytest runs with
every process they started, without waiting for their time limit, and an interrupt that arrives after an agent run has
ended starts no grading; both record the run as `interrupted`. A subprocess that a custom check starts itself, such as the
`text_review.py` call of the text tasks, is not ended before its own time limit.

The first `run` stores each variant's resolved revision and a fingerprint per input in `campaign.json`: the variant
file, the task file, the task's prompt file, the task's fixture tree, and the hidden tests and custom checks of the
task, and `scripts/text_review.py`, which grades the text tasks. A resume whose inputs differ stops, unless
`--allow-changed-inputs` is given; then the harness records the change in `campaign.json`.

### Measurement lock

Two measurements that run at once contaminate each other's wall time. A real `run` (not `--dry-run`, `summarize`,
`regrade`, or `record`) therefore holds one machine-wide exclusive lock, `measure.lock` in
`~/.local/state/hei5enbug-agent-setup/`, for its whole run, taken with `flock`. The lock file holds the holder's pid,
command, and start time. When another process holds the lock, `run` prints that holder to stderr and exits at once with
code 11, which no failure, usage limit (75), or interrupt (130) uses. `--wait-lock SECONDS` waits that long for the
lock instead. The kernel drops the lock when the process ends, including by a crash or a kill, so a stale lock never
stays. An out-of-repo campaign runner that starts `run` units takes the same lock for its own whole run and sets
`HEI5ENBUG_MEASURE_LOCK_HOLDER_PID` to its pid, so the `run` units it starts pass through; every other process stays
refused. `--lock-file` replaces the path for tests.

### Variants

A variant is a JSON file in `variants/`: `{"name", "ref", "settings", "env", "extra_args"}`. `ref` is the plugin
revision under test. `settings` merges into the run's `--settings` file, `env` into the agent's environment, and
`extra_args` into its command line. A variant that adds a bypass flag, `--bare`, `--permission-mode`, or a flag the
harness sets itself, such as `--setting-sources`, is rejected. The installed plugin and every plugin of the profile
stay off whatever `settings` says, and the user's instruction files and auto memory stay out whatever `env` says.

## Run records

```text
<run root>/<campaign>/
  campaign.json  state.json
  work/<run id>/repo/                      the agent's working folder, kept after the run
  rubric/<opaque id>/                      rubric grading folders whose names reveal no variant
  results/<task>/<variant>/rep<k>/         a Codex run is results/<task>/<variant>/codex/rep<k>/
    run.json  prompt.txt  command.json  settings.json  mcp.json  env.json
    stream.jsonl  stderr.txt  approvals.jsonl
    transcripts/main.jsonl  transcripts/subagents/  transcripts/runner/  codex/  assignments/
    view.json  grade/grade.json  grade/rubric.json  metrics.json
```

`env.json` records the Claude Code and Codex CLI versions, the installed plugin list, SHA-256 hashes of the Claude and
Codex settings files (never their content), the names of the removed variables, the cap transform of the export, the
harness revision, and, for a Claude Code run, `instruction_isolation`. A Codex run adds the CLI version, the model,
and the effort that its rollout shows.

## Metrics

Each `metrics.json` separates measured values from estimates.

| Metric | Source |
|---|---|
| Success, correctness, test pass rate, regressions | Graders. Success means every required check passed and, for a rubric task, the rubric mean reached its pass mark. Correctness is the weighted share of passed checks. |
| Tokens by model and source | Main transcript and subagent records, deduplicated by message ID; Codex `token_count` events per rollout. |
| `claude_total_cost_usd` | The result message of `claude -p`, a client-side estimate. |
| `claude_list_cost_usd` | Tokens priced with `harness/pricing.py` (official Claude list prices, checked 2026-10-25). It includes the main session, subagents, and separate Claude role runner processes. |
| `claude_runner_list_cost_usd` | The list cost of the separate Claude role runner processes alone. The stream's total cost leaves them out. |
| Claude spend in the summary | `claude_total_cost_usd` plus `claude_runner_list_cost_usd`; `claude_list_cost_usd` alone when the stream has no total. Subagents are already inside the total, and no process is counted twice. |
| `codex_list_cost_usd_estimate` | Codex tokens at OpenAI API list prices (checked 2026-11-20, including `gpt-6.2-sol` and `gpt-6-luna`). It is an estimate: Codex runs on a ChatGPT plan, which is not billed per token. |
| Wall time, turns, tool calls by tool, subagent launches by type | Harness clock and the stream; Codex tool calls are counted under their own key. |
| Role runner calls by role and exit code | Bash calls of `role_runner.py` and their status lines. |
| Retries | A failing Bash command run again, an agent type launched again after an error, a role runner run again after a non-zero exit. |
| Approval prompts, permission denials | `approvals.jsonl` and the result message. |
| Spend including attempts, cost per success | Summary only: every attempt of a task, and that spend divided by the successes. A cell whose spend leaves out an attempt that holds no cost figure reads `>= <value> (incomplete)`, never a plain total. |
| `grade_error` | Present when grading raised. `metrics.json` still holds usage, cost, and tool counts, and `run.json` records the same error. The summary leaves such a run out of the success and correctness statistics but counts its spend. `regrade` clears the error once grading succeeds. |
| Handoff loss | Task constraints that the main session knew but that a delegation prompt did not mention, and checks that failed because of it. |

## Graders

The graders in `harness/graders.py` check the final repository against its base commit. Check kinds include the
pre-existing tests (the fixture's own test files, restored over any edits), hidden tests, changed-path limits, text
checks, commit checks, line coverage, and forbidden commands or leaked values in the transcript. A task's custom
checks live in `tasks/custom/`.

The rubric grade covers only what a script cannot judge: design quality for T01 and answer quality for T10. The
assignment holds the task prompt, the rubric, and the artifact, but no variant name, revision, or model name. It runs
in `<campaign>/rubric/<opaque id>/`, a folder whose name reveals no variant, through
`python3 scripts/role_runner.py reviewer --model gpt-6.1-sol --effort high --timeout 1500`. When the runner exits
with 3 or 4, `claude-opus-5-5` grades instead, and `rubric.json` records the fallback. The harness stops a grader
that is still running after 1800 seconds, together with every process it started, and the run's grading then fails
with `grade_error`.

The text tasks (T13 to T20) grade a finished text with `scripts/text_review.py`, run from the repository that
holds the harness, not from the exported plugin, with `--reviews 1` so the grade rests on one reviewer whatever
the script's default. The required check `text-review-clean` passes on exit 0. On exit 1 the grader reviews the same
text once more, and the check fails only when both reviews return findings. Its detail and `grade.json` keep the
findings of both reviews, and `record` copies them into the record. Any other exit means the reviewer reached no
verdict, so the check raises and the run records `grade_error`; `regrade` retries it. The informational check
`ran-text-review` records whether the agent ran `text_review.py review`. The shared code is
`tasks/custom/text_review_shared.py`; the unit tests replace the script through a JSON file named by
`E2E_TEXT_REVIEW_STUB`. A custom check can mark an exception `no_verdict = True` to make grading stop with
`grade_error` instead of recording a failed check. The agent's `TMPDIR` lies inside the run's work folder, so the
reviews the agent runs are counted in its cost; the grader's own reviews are not.

A custom check reads the original run folder through `ctx.origin`, the graded copy's source, so a task such as T21
can inspect the Git worktrees and the fake Orca state that its setup script built beside the repository.

The UI tasks (T82 to T84 and T112) render a screen of the `demo-app` fixture with `harness/render.py`: `bun build` bundles the
screen with the fixture's own JSX runtime, and headless Chrome loads it once per width (1280 and 375 px) inside an
iframe of exactly that width, because Chrome's headless window is never narrower than 500 px. A custom check reads
the layout through `ctx.render(module)` (element boxes by `data-testid`, page width, elements past the edge), and
the screenshots stay in `grade/work/screens/` for the owner's blind comparison. `bun` and Chrome are found on `PATH`,
at the macOS application path, or through `E2E_BUN_BIN` and `E2E_CHROME_BIN`; when either is missing the check
raises `no_verdict`, so the run records `grade_error` and `regrade` retries it. The routing checks are not
required, so the hidden-check result of a run stays comparable when a variant routes the case elsewhere. T83 and T84
also require that the designer ran at `high`, and T112 that it ran at `xhigh`; the check reads the efforts that the
designer's subagent record shows for its turns, which the transcript view keeps beside the Agent call's own `effort`.
`tests/test_e2e_eval_ui_tasks.py` proves them, and skips the rendering tests when `bun` or Chrome is absent.

`tests/test_e2e_eval_graders.py` proves each task's graders: the unmodified fixture fails, and the reference
solution in `tasks/reference/` passes.

## Golden tasks

Prompts are in Korean, as the real user writes them. The fixtures are fictional repositories with the conventions a
real one has: a README, an `AGENTS.md` with a Korean mirror rule, tests, and Korean mirrors. T21 runs with
`ORCA_TERMINAL_HANDLE` set and a fake `orca` first on `PATH`, built by `tasks/setup/fake_orca.py`; it keeps its state
in `orca-state/` beside the repository and its tests are in `tests/test_e2e_eval_orca_cleanup.py`.

| Task | Fixture | Path it exercises | Request |
|---|---|---|---|
| T01 | inventory-service | Design skill | Design document for stock reservation |
| T02 | inventory-service | Worker delegation | Shipping fee policy across several files, with tests |
| T03 | inventory-service | Investigation, then fix | Bug fix from a user report, no failing test given |
| T04 | notes-cli | Multi-file edit | Rename memo to note in code, docs, and the Korean mirror |
| T05 | inventory-service | Parallel execution | Two independent changes in one request |
| T06 | inventory-service | Test writing | Tests for an untested module to 90 percent line coverage |
| T07 | ledger-lite | Failure recovery | Tests fail first for an environmental reason |
| T08 | notes-cli | Easy-work route | One-line configuration change |
| T09 | webapp-cleanup | Safety | Cleanup with uncommitted work and a fake secret present |
| T10 | inventory-service | Read-only investigation | Explain how order cancellation restores stock |
| T11 | notes-cli | Commit skill | Small change, then a commit that follows the message rules |
| T12 | inventory-service | Final review | Change, then an independent review before the report |
| T13 | inventory-service | Pull request description | Description for a branch that adds four columns, under rules that forbid a ticket key and diff-visible lists |
| T14 | inventory-service | Review reply | Answer why a check runs inside a lock |
| T15 | ops-notes | Issue body | Issue notes that link a guide and its setup section, which the guide already links |
| T16 | ops-notes | Ticket comment | Finish a comment draft that reports two of three completion criteria |
| T17 | notes-cli | Commit message | One-line setting change, then a commit |
| T18 | ops-notes | Chat message | Release announcement with a paragraph that restates its table |
| T19 | ops-notes | Shared document | Wiki draft of about 1,600 characters for a 1,500-character budget |
| T20 | notes-cli | Final report | Small change with tests, then a report |
| T21 | notes-cli | Orca cleanup at task end | One-line setting change for a ticket, with a fake `orca` and seeded Git worktrees of three repositories |
| T78 | commit-demo | Commit skill, staged-only scope | Korean-subject history, one staged change beside an unstaged edit and an untracked `.env` |
| T79 | commit-demo | Commit skill, required identifier | Commit rules that require a ticket key, and a request that names none |
| T82 | demo-app | UI routing, complete specification | Four named-line edits to a settings panel; routes to the implementation worker |
| T83 | demo-app | UI routing, layout request | Two-column profile screen that stacks at 375 px; routes to the designer |
| T84 | demo-app | UI routing, open breakpoint | Plan cards 320 px wide and 24 px apart in one row, mobile breakpoint left open; routes to the designer |
| T112 | demo-app | UI routing, new screen | A new invoices screen of three rows built from scratch, fitting at 1280 and 375 px; routes to the designer at its pinned `xhigh` |
| T150 | scout-demo | Scout result contract, one function | The error `parse_pair` raises when no delimiter is present; the report starts with `pass`, quotes the function with path and line numbers, and labels the answer direct |
| T151 | scout-demo | Scout result contract, missing path | A question on `demo-lib/docs/missing.md`, which does not exist; the report starts with `blocked`, names the path, and states no conclusion about its content |
| T152 | scout-demo | Scout result contract, partial evidence | Delimiters and a maximum line length across two files where the length is absent; the report starts with `issues`, labels the length unknown, and proposes no fix |
| T153 | inventory-service | Worker model on hard work, forced delegation | Cross-process locking of one data file across the app and the CLI (concurrency, a public contract, several components), handed to the implementation worker by the request; the worker's model comes from the variant's `implementation_worker` route |
| T154 | skill-review-demo | Skill review role, grader | A `release-notes` run that misses one of three expectations, graded through Skill Builder; the grading marks exactly that expectation failed with a quote of the output, and a review-route run exists |
| T155 | skill-review-demo | Skill review role, comparator | Two release-notes outputs where one breaks the stated limit of five bullets, compared blind through Skill Builder; the comparison prefers the other output, names the limit, and a review-route run exists |

The ids T89 to T91 belong to the comparison of Claude reviewer models in
[`evals/model-roles`](../model-roles/README.md); its opponent ids T92 and T93 ended with the removal of their skill.
Those cases run through the role runners instead of this harness, so
they have no task file here.

## Comparing a change on both hosts

A change to the plugin is measured with a before variant and an after variant that differ only by that change, on the
cases its issue names, on both hosts. The rule is in `harness/verdict.py`, which holds the exact steps; its summary:

- A run passes when every required check passes. Time is the `wall_seconds` of the run plus those of its archived earlier
  attempts, and cost is the list-price spend of the whole run, including archived earlier attempts: Claude spend as the
  summary computes it plus the Codex estimate. An earlier attempt whose duration no record shows makes the time `not
  measured`, and a final or archived attempt whose metrics hold no cost figure of its host, such as a killed attempt
  with no `metrics.json`, makes the cost `not measured`; the summary tables count that attempt as 0 and mark the
  spend and cost per success cells `>= <value> (incomplete)`.
- Quality: every after run passes on both hosts, and a case that passed before fails on neither host. A quality
  failure fails the case whatever the time and cost gaps are.
- Gap: for one case and measure, the larger host value divided by the smaller. Run the case once per variant and host
  first. The case passes when its gap after is at most its gap before. When the gap grew, the verdict is `repeat`:
  run four more per variant and host, alternating, and pair the runs by repetition number. Then the case passes when
  the median of the five gaps after is at most the largest of the five gaps before. Each measure follows its own first
  pair, so repeats for one measure never change another measure that passed on its first pair. A repetition that lacks
  a run on a host or a variant is an incomplete pair and gives `not measured`.
- A first gap before above 2 is no pass condition for that measure. The case prints an `investigate` line, and one
  issue investigates that gap unless an open issue already covers it.
- A host with no before run decides quality only when the campaign shows that the before variant cannot run there, and
  its after run becomes the baseline for later changes. `record` takes a before run that no invocation of the campaign ever
  scheduled for that task and host as that evidence: `campaign.json` keeps the cumulative `scheduled` set of every
  (task, variant, host) any invocation scheduled, and a file that stored none falls back to its `order`. A scheduled before run that is missing, such as one a campaign
  stopped before reaching, gives `not measured`.
- A missing time or cost value gives `not measured`, never a pass, also for a case with no before run, for one whose
  first gap before is above 2, and for a case with a host that has no before run when a before value on the other host is
  missing.
- Improvement claim (`--claim`): a change adopted because it lowers time or cost names the claimed measures. Per case
  and host over five alternating runs, every after run passes, the median of each claimed measure after is below the
  lowest value before, and the median of each other measure after is not above the highest value before. One pair
  runs first, and a second pair runs when the first fails; the claim is rejected when the second fails too. A claim that
  is rejected makes its case and the overall verdict `reject`, and one that has not reached its decision leaves them at
  `continue to five` or `second pair`, never `pass`.

`record` reads the runs of both variants on both hosts from a campaign and builds one case per requested task, or per
task the campaign ran when `--tasks` is absent. A run that is unfinished, has no metrics, has no grade, or has a grading
error stays in its case as `not measured`; a task with no run at all stays too. It reads each role's model and effort
from the run's own host records: the Claude stream and command line, the Codex rollout of the main session and of every
child session (its role from `session_meta`, a second session of one role kept as its own invocation), the role runner
status lines, and the rubric result. An effort that no record states reads `not measured`.
The revision of each variant is the plugin revision its own runs stored in `run.json`, not the latest one in
`campaign.json`; runs of one variant at different revisions make `record` refuse, so measure each revision in its own
campaign. The archived earlier attempts of a run count as runs here, because their time and spend enter the record. A run that stored none falls back to the campaign's revision.
It then judges the cases, validates the record, and writes `records/<issue number>.json`. It prints one line per case,
the `investigate` lines, which cases need repeats, and the claim verdicts. A record holds measurements, run facts
such as models, efforts, and issue numbers, and fictional fixture names only; validation rejects an absolute local
path, a model outside the cap, and a missing field. `tests/test_e2e_eval_record_cli.py` validates every committed
record.

### Hook facts

`record --hook-facts` adds an informational `hooks` object to each run of the record. Neither host's records time a hook, so
the time is a replay: every recorded tool call is sent again to the matching PreToolUse and PostToolUse hooks of the run's
exported plugin with the environment of a measurement run, and the wall time of each hook process is measured
(`replayed_hooks`, `replay_total_seconds`, `replay_slowest`). Denials come from the replay's own decisions
(`replay_denials`) and, on Claude Code, from the hook responses in the stream (`stream_denials`, with their counts). The
facts describe the hooks alone and enter no verdict. `harness/hook_facts.py` holds the code.

### Records

| Issue | Cases | Verdict |
|---|---|---|
| [#92](records/92.json) | T02, T08, and T20 before and after; T05, T07, T09, and T12 after, for the item 6 rules | Fail: T08 on Claude Code and T20 on Codex. The owner adopted the change on 2026-11-14 because no plugin file these cases load changed; #105, #86, and #106 follow up. |

## Known limits

- Bash requests are always allowed, so a campaign must run on a machine where an agent may run any shell command.
  The approver denies only file-tool requests that resolve outside the run's work folder.
- The process-tree poll in `harness/process.py` can miss a detached child that starts after the last poll and before
  the agent exits, so such a child is not terminated.
- Calls that need no prompt in the user's permission mode are not counted as approvals, so the approval count
  measures prompts the user would see, not every guarded call.
- The Codex cost is an estimate at API list prices, and the long-context tier is chosen per request from its input
  size. Codex tokens of a rollout that does not start in the run's folder are not collected.
- A handoff constraint counts as missing when none of its keywords appear in a delegation prompt. A paraphrase
  without a keyword counts as missing.
- Runs share the user's Claude and Codex accounts, so usage limits and service load affect every variant.
- Only a usage limit of the agent's own Claude session stops a campaign. A Codex quota failure inside a run is part of
  the agent's outcome and shows up as a role runner exit code.
- A Codex run has no spend limit, because `codex exec` has no budget flag; a runaway Codex run ends only at the wall
  time of its task.
- The effort of a Claude subagent is not in the records the harness copies, so a record shows it as `not measured`.
