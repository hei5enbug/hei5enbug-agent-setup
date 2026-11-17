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
`work/<run id>/repo/`. Every other request is allowed. The server logs each request, allowed or
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
`codex exec` with `gpt-6.1-sol` at `high`, with this setup:

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

No role of a measurement may start a model stronger than `claude-opus-5-5` or `gpt-6.1-sol`. The allowed models are
`MODEL_CAP` in `harness/config.py`, and `harness/records.py` validates records against the same set. `run` rejects a
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
`gpt-*-astra` and `gpt-*-terra` id (such as `gpt-6-astra` and `gpt-6.1-terra`) becomes `gpt-6.1-sol`, in `config/model-registry.json`, `agents/`, `.codex/`, `skills/`, and `instructions/` text files
(the revisions in git stay untouched). The harness then scans those files again and rejects the campaign when
any model outside the cap remains, with a message that names the file and the cap. The transform is `apply_cap_transform` in
`harness/plugin_export.py`. Each run's `env.json` records `cap_transform` (the replacements, which model ids were replaced,
and their count), `plugin-export.json` holds it with a digest of the transformed export, and that digest is part of the
campaign's input fingerprint, so a resume on a differently transformed export stops. A revision that an earlier harness
exported without the transform is exported again.

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
| Decide the candidate loop shapes of issue 102 and write their record | `python3 evals/e2e/harness/cli.py record-loop --campaign <name> --issue 102 --variants baseline=<variant>,a=<variant>,b=<variant>,c=<variant>[,a+b=<variant>]` |

`--parallel` sets the number of runs at once (default 3). With several variants the order alternates per task and
repetition (ABAB, then BABA), so time-of-day effects spread evenly.

Running the same `run` command again resumes the campaign. Finished runs are skipped. A run that failed for an
infrastructure reason, hit a usage limit, or was interrupted is started again, and its old records and work folder
move to `attempts/rep<k>/<n>/`. When a run reports a usage limit, the harness starts no new run, lets running ones
finish, and exits with code 75.

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
| `codex_list_cost_usd_estimate` | Codex tokens at OpenAI API list prices (checked 2026-10-25). It is an estimate: Codex runs on a ChatGPT plan, which is not billed per token. |
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

T22 to T24 grade the draft that the agent saves for a separate review run, so their prompts tell the agent not to run
`text_review.py`. T23 and T24 supply the first draft and the finding the first run returned, and the checks read the
saved second draft by sentence patterns. They have no `text-review-clean` check and are not in
`config/writing-surfaces.json`.

T25 to T28 grade texts whose input names a tool that did or checked the work, so their prompts also tell the agent not
to run `text_review.py`, and the checks read the saved text or the last commit message by patterns, with no
`text-review-clean` check and no entry in `config/writing-surfaces.json`. T25 to T27 are required to pass, and the
check `no-other-tool-mark` of T28 is advisory: T25 and T26 must leave the model name, the effort, and wording that an
AI or an agent did it out of the text, T27 must name the model that its diff changes, and T28 must name the model its
request asks for.

T29 to T31 grade texts that refer to a stage or a division of a procedure or plan, so their prompts also tell the
agent not to run `text_review.py`, and the checks read the saved text by patterns, with no `text-review-clean` check and
no entry in `config/writing-surfaces.json`. No model grades them, and every check is required. T29 must name stages 0
and 3 to 8 of a nine-stage procedure by their titles in order, leave no stage named by a number with no title of that
stage beside it, and put no number beside the title of another stage. T30 must keep the values of a depth limit and an
item limit, which are quantities. T31 must name a division that its draft calls `Phase 1` by its title `Rollout`, keep
item 1 with its title and number, and let no number name both the division and an item.

`evals/e2e/candidates/88/` holds a deterministic candidate for the rule that T29 to T31 measure: an advisory that
`text_review.py check` raises for a line that names a stage, phase, division, or item by a number with no title beside it,
such as "step 0" or "steps 3 to 8". `apply.py <checkout>` adds it to that checkout's `scripts/text_review.py` and
`--dry-run` shows the diff; applying it twice changes nothing more. It is not in the shipped script, and a third
variant that holds it without the rule text is cut as one commit of the base revision. A pattern decides the bare
number in the drafts of T29 and T31. It cannot decide a title with the number of another stage or a changed order (T29),
a changed or dropped quantity (T30), or one number naming a division and an item (T31), because each needs the
procedure or the draft before the edit. It covers English keywords only.

T32 and T33 measure the review itself, so their prompts ask the agent to run the plugin's `text_review.py review` on a
seeded draft it must not edit. The checks read the result of that run from the transcript: the review must reach the
reviewer (`stage` is `review`, with no `error`) on the named draft. In T32, whose rules file requires the names of the
added tests, no `removable` finding may quote the list item of those names; in T33, whose rules ask for no names, a
`removable` finding must quote the list item of the changed files. They have no `text-review-clean` check and are not in
`config/writing-surfaces.json`.

T78, T93, and T94 measure what the agent does when the reviewer of the text review cannot run. Their prompts ask for a
text to be posted with `python3 tools/post_demo.py`, which copies it into `posted/`, after an independent text review
that runs with `--runner tools/limit_runner.py`, a stub whose call is counted in `stub-calls.log` beside the repository.
The stub prints a usage-limit message (T78 and T94, mode `usage_limit`) or `authentication failed` to its error output
(T93, mode `auth`), and exits 1, so no model runs. No model grades them, and the checks read the posted files, the
transcript, and the log. In T78 the draft must be posted as written, the run must not ask whether to post, its final
answer must hold exactly one line saying that the review did not run because of the usage limit, and no other reviewer
may start (no `role_runner.py`, `claude -p`, or `codex exec` call and no subagent). In T93 nothing may be posted, the
final answer or an `AskUserQuestion` call must hold a question and the text `authentication failed`, and the failure
must not be called a usage limit. In T94, with two drafts, both must be posted as written without a question and with
one such line; the informational check `reviewer-called-once` records whether the reviewer stub was called only once.
Every other check is required.

T97 is T08 with its prompt, fixture, and reference solution, plus a check on the final report: when the report is under the
length threshold, no Bash call may run `text_review.py review` or `check` through Python. The threshold is read from
`MINIMUM_REPORT_CHARACTERS` in `scripts/final_report_hook.py` of the repository that holds the harness, so the task
never keeps its own copy; the instruction sentence that exempts a short final report names the same number, and
`tests/test_final_report_threshold.py` keeps the two equal. A report at or above the threshold passes the required check
`short-report-not-reviewed` without being judged, because the rule does not apply to it, and the informational check
`report-is-short` records which case the run was. A command that only searches for the words, such as `rg "text_review.py
review"`, is not a run. No model grades it, and every check but `report-is-short` is required.

`evals/e2e/candidates/108/` holds the other side of the threshold choice of issue 108, no threshold on both hosts:
`apply.py <checkout>` removes the exemption sentence for a short final report from `instructions/shared-text.md` and sets
`MINIMUM_REPORT_CHARACTERS` in `scripts/final_report_hook.py` to 0, so the Claude Code hook asks for the review of every
final report that follows a change, as the Codex session does. It changes both files or neither, `--dry-run` shows the
diffs, and applying it twice changes nothing more. A variant that holds it is cut as one commit of the revision that
holds the threshold, and `record --before <that variant> --after <the threshold variant>` judges the threshold against none.

`evals/e2e/candidates/111/` holds a deterministic candidate for where the usage-limit handling of issue 111 lives:
`apply.py <checkout>` moves the action text out of the exit-4 paragraph of `instructions/shared-text.md`, which keeps
one line telling the agent to follow the result's `next`, and puts it into that field of the usage-limit result of the
checkout's `scripts/text_review.py`. It changes both files or neither, `--dry-run` shows the diffs, and applying it
twice changes nothing more. It is not in the shipped files; a variant that holds it is cut as one commit of the revision
that holds the rule text.

T98 to T100 measure the loop of the independent text review on one draft each, in `loop-notes`. Their prompts ask for a
pull request description to be posted with `python3 tools/post_demo.py` after a text review that repeats until no finding
is left and runs with `--runner tools/loop_runner.py`, a stub that raises seeded `removable` findings and logs every call
as one JSON line in `stub-calls.log` beside the repository, so no model reviews. A review run is the set of stub calls
that received one assignment. In T98 (mode `split`) the stub lets an odd call see the first and third seeded sentences and
an even call the second, as two reviewers with different attention would, so one reviewer needs four runs and two need
three. In T99 (mode `stale`) it raises one seeded sentence and then, once, a sentence no run changed. In T100 (mode
`sequence`) it raises one seeded sentence per run. The required checks are `reviewer-attempted`, `reviewed-text-posted`
(no seeded sentence left, the opening sentence and both bullets kept), `last-review-clean`, and `no-question`; T100 also
requires `loop-run-by-worker`: no `text_review.py review` call in the main session and a `role_runner.py language`
delegation. The informational checks `review-runs` and `reviewer-calls` record how many runs and calls the loop took, and
T99's `late-sentence-kept` records whether the sentence raised only late stayed. No model grades them. They are not in
`config/writing-surfaces.json`.

`evals/e2e/candidates/102/` holds the three candidate loop shapes of issue 102 as `apply.py <checkout> --candidate a|b|c`,
or several joined with `+`: `a` adds the worker-run loop paragraph to `instructions/shared-text.md`, `b` makes 2 the
default of `--reviews`, and `c` adds `--history <file>` to `scripts/text_review.py` with one rule sentence. With a history
file the script lists the sentences changed since the previous run of the draft, drops a `removable` finding in a
sentence that no run changed and no earlier run flagged, and keeps a finding of any other type, and it records the draft
and the flagged sentences after every run that reached the reviewer. `--dry-run` shows the diffs, an edit already there
changes nothing, and no file changes when one anchor is missing. None of them is in the shipped files; a variant that
holds one is cut as one commit of the baseline revision. The record of issue 102 holds the candidate whose text stays,
and `tests/test_loop_adoption_text.py` keeps the repository equal to it.

`record-loop` reads the variants of one campaign by label, writes `records/102.json`, and prints each candidate's decision.
Each run carries `passed`, `review_runs` (the `text_review.py review` runs that reached the reviewer, counted in the main
session, the subagents, and the Claude role runner transcripts), `main_turns` (the main session's model requests from the
one that ran the first review to the end of the session, 0 without a review), and `main_tokens` (the main session's input,
output, and cache tokens over the whole run). The decision is in `harness/loop_decision.py`: a candidate is adopted when,
against the baseline on both hosts, no writing task of T13 to T20 whose `text-review-clean` passes on the baseline fails
on it and its number of passing tasks does not fall, the claim on the list cost is accepted on T13, T15, and T20, and the
host comparison above passes on them; otherwise it is rejected, or undecided while a run is missing or a claim has not
reached its decision. Candidates adopted alone are then measured together as `a+b`; a combined variant that fails drops the
candidate adopted last, and the next combination runs. `validate_record` recomputes the decisions from the runs.

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
| T22 | review-rounds | Ticket comment, first draft | Comment whose work item requires each step's time before and after and whose proposal the result replaced |
| T23 | review-rounds | Ticket comment, second draft | Revise a draft after a finding that it dropped the work item's exception for a first run without a cache |
| T24 | review-rounds | Ticket comment, second draft | Revise a draft after a finding that "the check deletes a loose cache" can mean before or after the cache runs |
| T25 | tool-notes | Pull request description | Notes that say a model at a stated effort reviewed the description, found 3 problems, and the final text was not reviewed again |
| T26 | tool-notes | Commit message | Parser fix whose notes name the reviewing model and suggest a subject that carries its name |
| T27 | tool-notes | Commit message | Change of the `reviewer_model` setting from one demo model to another |
| T28 | tool-notes | Chat message | Thread announcement whose request asks to say that a named model reviewed it |
| T29 | stage-notes | Ticket comment | Draft that says "Run step 0 first, then steps 3 to 8 in order." for a procedure whose stages carry titles |
| T30 | stage-notes | Review reply | Draft that states a depth limit of 2 levels and an item limit of 3 |
| T31 | stage-notes | Ticket comment | Draft that calls a division titled Rollout "Phase 1" and begins with item 1 of the list whose first item is Schema extension |
| T32 | identifier-lists | Review reply, review run | Review of a reply whose rules require the names of the added tests and whose draft lists three of them in one item |
| T33 | identifier-lists | Pull request description, review run | Review of a description, under rules that ask for no names, whose draft lists the three files its diff changes in one item |
| T78 | limit-notes | Pull request description, usage limit | Post a description after a text review whose reviewer stub reports a usage limit |
| T93 | limit-notes | Pull request description, reviewer failure | The same request with a stub that fails with `authentication failed` |
| T94 | limit-notes | Pull request description and ticket comment, usage limit | Post two drafts after a text review whose reviewer stub reports a usage limit |
| T97 | notes-cli | Short final report, no text review | The one-line setting change of T08, graded on whether a final report under the threshold got a text review |
| T98 | loop-notes | Pull request description, review loop with two reviewers | Post a description after a review loop whose stub shows each reviewer a different part of the seeded sentences |
| T99 | loop-notes | Pull request description, late finding | Post a description after a review loop whose stub raises a finding in a sentence no run changed |
| T100 | loop-notes | Pull request description, review loop by a worker | Post a description after a review loop that a `language` worker, not the main session, runs |

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
