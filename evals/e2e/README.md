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
     --mcp-config <run>/mcp.json --permission-prompt-tool mcp__eval_approver__approve
     --max-budget-usd <task limit> -- <prompt>
   ```

   The prompt follows `--`, so a prompt that starts with a dash, such as `--version ...`, is not read as an option.

   `settings.json` turns off the installed `hei5enbug-agent-setup@hei5enbug` plugin. Every other part of the user's
   environment stays as it is, including the default permission mode, other plugins, MCP servers, and Codex.
   The harness removes only the `ORCA_*` variables, so a run cannot report to or message the Orca terminal that
   started it. It never passes a bypass mode, `--bare`, or `--permission-mode`.
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
- Stdin is `/dev/null`, and `ZDOTDIR` is an empty folder, so the shell Codex starts reads none of the user's zsh
  startup files and keeps the `PATH` the run set. The harness removes the `ORCA_*` variables here too.
- No approver stands in. Claude Code asks the permission-prompt tool, but Codex runs with `approval_policy` set to
  `never` inside a `workspace-write` sandbox, so a request outside the sandbox fails instead of waiting for an answer.
  The plugin's own guard hooks still run.
- Codex has no spend flag, so only the wall-time limit of the task is enforced.
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
| Check the pilot facts per run | `python3 evals/e2e/harness/cli.py pilot-check --campaign <name>` |
| Print tables | `python3 evals/e2e/harness/cli.py summarize --campaign <name> [--out file.md]` |
| Compare two variants | `python3 evals/e2e/harness/cli.py summarize --campaign <name> --compare baseline,<other>` |
| Export a revision only | `python3 evals/e2e/harness/cli.py export-plugin --ref <ref>` |
| Judge a change and write its record | `python3 evals/e2e/harness/cli.py record --campaign <name> --issue <n> --before <variant> --after <variant> [--claim wall_seconds,cost_usd] [--tasks T08]` |

`--parallel` sets the number of runs at once (default 3). With several variants the order alternates per task and
repetition (ABAB, then BABA), so time-of-day effects spread evenly.

Running the same `run` command again resumes the campaign. Finished runs are skipped. A run that failed for an
infrastructure reason or hit a usage limit is started again, and its old records and work folder move to
`attempts/rep<k>/<n>/`. When a run reports a usage limit, the harness starts no new run, lets running ones finish, and
exits with code 75.

The first `run` stores each variant's resolved revision and a fingerprint per input in `campaign.json`: the variant
file, the task file, the task's prompt file, the task's fixture tree, and the hidden tests and custom checks of the
task, and `scripts/text_review.py`, which grades the text tasks. A resume whose inputs differ stops, unless
`--allow-changed-inputs` is given; then the harness records the change in `campaign.json`.

### Variants

A variant is a JSON file in `variants/`: `{"name", "ref", "settings", "env", "extra_args"}`. `ref` is the plugin
revision under test. `settings` merges into the run's `--settings` file, `env` into the agent's environment, and
`extra_args` into its command line. A variant that adds a bypass flag, `--bare`, `--permission-mode`, or a flag the
harness sets itself is rejected. The installed plugin stays off whatever `settings` says.

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
Codex settings files (never their content), the names of the removed variables, the cap transform of the export, and the
harness revision. A Codex run adds the CLI version, the model, and the effort that its rollout shows.

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
| Spend including attempts, cost per success | Summary only: every attempt of a task, and that spend divided by the successes. |
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

## Comparing a change on both hosts

A change to the plugin is measured with a before variant and an after variant that differ only by that change, on the
cases its issue names, on both hosts. The rule is in `harness/verdict.py`, which holds the exact steps; its summary:

- A run passes when every required check passes. Time is the `wall_seconds` of the run plus those of its archived earlier
  attempts, and cost is the list-price spend of the whole run, including archived earlier attempts: Claude spend as the
  summary computes it plus the Codex estimate. An earlier attempt whose duration no record shows makes the time `not
  measured`.
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
- A case or host with no before run decides quality only, and its after run becomes the baseline for later changes.
- A missing time or cost value gives `not measured`, never a pass, also for a case with no before run and for one whose
  first gap before is above 2.
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
It then judges the cases, validates the record, and writes `records/<issue number>.json`. It prints one line per case,
the `investigate` lines, which cases need repeats, and the claim verdicts. A record holds measurements, run facts
such as models, efforts, and issue numbers, and fictional fixture names only; validation rejects an absolute local
path, a model outside the cap, and a missing field. `tests/test_e2e_eval_record_cli.py` validates every committed
record.

### Records

| Issue | Cases | Verdict |
|---|---|---|

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
