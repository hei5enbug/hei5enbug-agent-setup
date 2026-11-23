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
   `PATH`. The variant's `env` and the configuration's `extra_env` still win over it. A setup script finds the exported
   plugin folder of the variant under test in its `E2E_PLUGIN_DIR` environment variable, so a task that seeds an
   installed copy of the plugin builds it from the code under test, not from the harness checkout.
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

Without an answer sheet the harness cannot answer a question that the agent asks with `AskUserQuestion`: the approver
lets the call through, and the run ends with the question unanswered. Task prompts therefore leave no decision open that
would change the result, except in a task that names an answer sheet (see "Scripted user").

### Scripted user

A task with `user.sheet` (a file under `tasks/answers/`) gets a user that is a script with no model, `harness/scripted_user.py`.
The sheet is not in the agent's folder or in the exported plugin. It lists each decision (`id`, `terms`, `answer`) and each
point an approved specification must hold (`id`, `terms`, `rejected_terms`, `sentence`); a term may give alternatives with `|`,
such as `sunday|일요일`, and terms are compared without case.

- A question is about a decision when it contains at least one of that decision's terms. It gets the answer of every decision it
  matches, in sheet order, and the sheet's fallback, "use your recommendation", when it matches none. A question asked through
  `AskUserQuestion` is matched on its text, its header, and its option labels; the approver server answers it in the tool's
  free-form answer for each question.
- A question that contains an approval term (`approve`, `approval`, `승인` unless the sheet lists others) is a request for
  approval. It is approved with the sheet's approval sentence when the specification text holds every term of every required
  point and no rejected term outside the heading of rejected alternatives; otherwise it gets the sentence of the first point that
  fails. A heading is a markdown heading, a bold line, or a label line that starts with a heading from the sheet (`Rejected
  alternatives`, `기각한 대안`); its section ends at the next heading or label line. The specification text is the question for a
  plain-text question's whole turn, and the assistant text since the previous question for a tool question, read from the
  stream, which can miss text the stream has not yet written.
- A turn that ends with a question in plain text (its last line ends with `?`) is answered by resuming the session: `claude -p
  --resume <session>` with the same flags, or `codex exec resume <thread>` with the model, effort, and sandbox set by `-c`, because
  `exec resume` takes no `-s` or `-C`. Every turn appends to the same stream, and the wall-clock limit covers all of them. The run
  stops when a turn ends without a question, at the sheet's `max_exchanges`, or, when the sheet sets `answer_after_approval` to
  false, at the first question after an approval, which is logged without a reply.
- `user-log.jsonl` in the run's result folder logs every exchange: its kind (`tool` or `text`), question, matched identifiers,
  reply, whether it asked for approval and was approved, the specification an approval was judged on, and the paths the agent had
  edited and the commit count at that moment. `view.json` carries it as `user_exchanges` for the graders.

The `exec resume` command and the `AskUserQuestion` round trip need a first paid pilot run on each host before a measurement
relies on them.

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

### Codex question hook probe

`probe-question-hook` settles whether a Codex `PreToolUse` hook receives a `request_user_input` call. The official Codex
hooks page lists the tools that event covers (shell commands, `apply_patch`, MCP and other function tools) and does not
name `request_user_input`, so the question guard of #104 cannot be registered on Codex without this check. The probe
builds an isolated `CODEX_HOME` like a Codex run (credential symlink, `.zprofile` ZDOTDIR) but installs no plugin. Its
`hooks.json` holds two hooks. The guard hook has the plugin's matcher `^(AskUserQuestion|request_user_input)$`, logs the
event it receives, and denies the call with a sentinel reason. The control hook matches every tool and only logs, so a
silent guard hook can be told apart from hooks that do not run at all. One `codex exec` session at `low` effort then
asks the model to call `request_user_input` once. It makes one model call and runs only when the user starts it.

`--dry-run` prints the files and commands and starts nothing. A real run writes `hook-log.jsonl`, `stream.jsonl`, and
`evidence.json` into the trial folder (`<run-root>/probes/question-hook-<UTC time>` unless `--dir` names a new one):

| Verdict | Meaning | Exit |
|---|---|---|
| `delivered-and-denied` | The guard hook received `request_user_input`, and the rollout shows the sentinel in the tool output. Register the check on Codex. | 0 |
| `delivered` | The guard hook received it, but the rollout does not show the denial. Read the rollout before registering. | 0 |
| `not-delivered` | The model called the tool, and only the control hook, or no hook, logged other tools. Codex gets no automatic check. | 0 |
| `hooks-inactive` | The model called the tool, and no hook logged anything. Inconclusive; check hook trust and rerun. | 3 |
| `not-called` | The model never called `request_user_input`. Inconclusive; rerun or check the tool is offered. | 3 |

The evidence also lists the keys of the event and of `tool_input` that the hook received, and the rollout events whose
type names a hook.

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
| List the rule groups of the session instructions with their bytes | `python3 evals/e2e/harness/cli.py rules [--json] [--min-bytes 200]` |
| Judge the loop-shape candidates and write their record | `python3 evals/e2e/harness/cli.py loop-record --campaign <name> --issue <n> --baseline <variant> --candidate a=<variant> [--candidate b=<variant>] [--combined <variant>] [--tasks T13,T14]` |
| Build the combined revision of adopted loop-shape candidates and print its SHA | `python3 evals/e2e/harness/cli.py build-combined --base <baseline branch> --candidate <branch> --candidate <branch> [--worktree <folder>] [--dry-run]` |
| Judge a change and write its record | `python3 evals/e2e/harness/cli.py record --campaign <name> --issue <n> --before <variant> --after <variant> [--claim wall_seconds,cost_usd [--claim-cases T36]] [--tasks T08]` |
| Probe whether a Codex hook receives `request_user_input`; `--dry-run` starts nothing | `python3 evals/e2e/harness/cli.py probe-question-hook [--dry-run] [--dir <folder>] [--effort low]` |

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

A variant is a JSON file in `variants/`: `{"name", "ref", "plugin", "remove", "settings", "env", "extra_args"}`. `ref`
is the plugin revision under test. `settings` merges into the run's `--settings` file, `env` into the agent's
environment, and `extra_args` into its command line. A variant that adds a bypass flag, `--bare`,
`--permission-mode`, or a flag the harness sets itself, such as `--setting-sources`, is rejected. The installed plugin
and every plugin of the profile stay off whatever `settings` says, and the user's instruction files and auto memory
stay out whatever `env` says.

- `"plugin": "none"` runs the host with no plugin revision loaded, the stock variant (`variants/stock.json`). It takes
  no `ref` and no `remove`. The Claude Code command has no `--plugin-dir`, and the settings still turn off the
  installed plugin and every plugin of the profile. The Codex run gets its own `CODEX_HOME` with the credential link
  and nothing else: no marketplace is added, no plugin is installed, and no hook is trusted, so `codex-setup.json`
  shows an empty `steps` list and `"plugin": "none"`. Nothing is exported, `variant_shas` and the record's revision
  read `none`, and `pilot-check` fails a stock run that passed `--plugin-dir`, loaded a plugin of the plugin's name,
  or installed one. What a stock run still loads is the host's own: its built-in instructions and tools.
- `"remove"` is a list of parts that the export cuts out of the plugin revision, each `{"file", "start"}` for a bullet
  or a paragraph by its first words, or `{"file", "heading"}` for a whole section by its heading line, such as
  `"## Delegation"`. Every entry is matched against the file as exported and must match exactly one part: an entry that
  matches nothing or more than one part, names a missing file, or overlaps another entry fails the export with a
  message that names the file and the words. `plugin-export.json` lists the removed parts with their bytes. An export
  with parts removed has its own folder, `plugins/<sha>-<digest>/`, and its content digest is part of the campaign's
  input fingerprint. A record names such a variant's revision `<sha>-<digest>`, so `record --before <whole plugin>
  --after <variant with remove>` compares the two on both hosts under the comparison rule below, and the two never
  share a revision label.

`cli.py rules` lists every bullet and paragraph of `instructions/session/core.md`, `common.md`, `claude-code.md`, and
`codex.md` as a rule group, largest first, with its bytes, the hosts that load it (`worker` marks the core text an
implementation worker also loads), and the `start` words of its `remove` entry; `--json` prints the same with each
`remove` entry ready to paste into a variant. The totals are file bytes per context, not the rendered session context.
The list chooses no candidate.

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
| `review_loop` | The independent text review loop of a run. `reviewer_runs` counts the `text_review.py review` calls of every session whose result shows the reviewer stage, and `check_stops` those that stopped at the deterministic check. `main_turns` counts the main session's model requests from the first request that issues `text_review.py review` or `role_runner.py language` to the end of the run, the post included; `main_tokens` are the tokens of the whole main session and `main_tokens_loop` those of the requests counted in `main_turns`. A run that never reviews has `loop_started` false and `main_turns` 0. |
| Approval prompts, permission denials | `approvals.jsonl` and the result message. |
| Spend including attempts, cost per success | Summary only: every attempt of a task, and that spend divided by the successes. A cell whose spend leaves out an attempt that holds no cost figure reads `>= <value> (incomplete)`, never a plain total. |
| `grade_error` | Present when grading raised. `metrics.json` still holds usage, cost, and tool counts, and `run.json` records the same error. The summary leaves such a run out of the success and correctness statistics but counts its spend. `regrade` clears the error once grading succeeds. |
| Handoff loss | Task constraints that the main session knew but that a delegation prompt did not mention, and checks that failed because of it. |
| `delegation` | Present when the task has a `delegation_report` check: the changed-file count, its limit, the completed implementation delegations, and `skipped`. `skipped` is true when more files changed than the limit and no implementation delegation completed. |

## Graders

The graders in `harness/graders.py` check the final repository against its base commit. Check kinds include the
pre-existing tests (the fixture's own test files, restored over any edits), hidden tests, changed-path limits, text
checks, commit checks, line coverage, and forbidden commands or leaked values in the transcript. A task's custom
checks live in `tasks/custom/`. The `delegation_report` check never fails and carries no weight: it records the
changed-file count and whether a change over its limit (`over`, default 2) went without a completed implementation
delegation. T05, T12, and T20 carry it.

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

T130 to T132 run the scripted review of `tasks/setup/review_loop_script.py` through `tools/review.py`; its run log sits in
`review-state/` beside the repository, where the checks read how often it ran, and `tests/test_e2e_eval_review_loops.py`
proves them. They have no text-review check and are not in `config/writing-surfaces.json`.

T22 to T24 grade the draft that the agent saves for a separate review run, so their prompts tell the agent not to run
`text_review.py`. T23 and T24 supply the first draft and the finding the first run returned, and the checks read the
saved second draft by sentence patterns. They have no `text-review-clean` check and are not in
`config/writing-surfaces.json`.

T25 to T28 grade, by sentence patterns, whether a text leaves out the tool that did or checked the work: a pull
request description and a commit message whose notes name a reviewing model, a commit message whose diff changes a
model setting, and a thread message whose request asks to name the model. The agent runs under the normal rules,
`text_review.py` included. They have no `text-review-clean` check and are not in `config/writing-surfaces.json`. T20
also records the informational check `reviewer-not-named`, which fails when the final report names a reviewer model
or an effort.

T29 and T30 grade the first `text_review.py review` run of the agent, which the prompt tells it to run on the draft
before changing it. The `identifier-lists` fixture holds a review reply draft and a pull request description draft,
each with one list item of three identifier code spans, and the rules of each place. In T29 the rules require the
names of the added tests, and the check `first-review-keeps-test-names` passes when that run reached the reviewer with
kind `review-reply` and no `removable` finding quotes a test name; `test-names-kept` requires the three names in the
saved reply. In T30 no rule asks for names and the diff shows the three files, and `first-review-cuts-file-list`
passes when that run reached the reviewer with kind `pr-description` and a `removable` finding quotes a file name;
`file-list-cut` requires the saved description to state the behavior change and to name no line with all three files.
A run that stops at the check stage fails the first check. They have no `text-review-clean` check and are not in
`config/writing-surfaces.json`.

T65 and T66 grade, by sentence patterns, whether a text names a stage of a procedure or a division of a plan by its
title instead of its number alone. The `stage-names` fixture holds a nine-stage rollout procedure and a plan with a
division called Rollout. T65 is a ticket comment whose draft says "step 0" and "steps 3 to 8" and also states a nesting
depth of 2 levels and a limit of 3 items, which must keep their numbers. T66 is a chat message whose draft calls the
division "Phase 1" and its first item "1", which is the plan's Schema extension. A number counts as named when its
title stands right beside it. The agent runs under the normal rules, `text_review.py` included. They have no
`text-review-clean` check and are not in `config/writing-surfaces.json`.

`tests/test_e2e_eval_graders.py` proves each task's graders: the unmodified fixture fails, and the reference
solution in `tasks/reference/` passes.

## Golden tasks

Prompts are in Korean, as the real user writes them; the T31 and T32 prompts are English briefs, as one agent session
writes them to another. The fixtures are fictional repositories with the conventions a
real one has: a README, an `AGENTS.md` with a Korean mirror rule, tests, and Korean mirrors. T21 runs with
`ORCA_TERMINAL_HANDLE` set and a fake `orca` first on `PATH`, built by `tasks/setup/fake_orca.py`; it keeps its state
in `orca-state/` beside the repository and its tests are in `tests/test_e2e_eval_orca_cleanup.py`. T31 to T34 use the
same fake with agent and shell terminals and the messages sent between sessions, seeded by
`tasks/setup/handoff_common.py`; their graders read the fake's ordered call log, which records each call's caller, and
their tests are in `tests/test_e2e_eval_handoff.py`.

T113 uses the same fake `orca`, which also starts terminals, shows and edits a started agent terminal's input line, and accepts waits and sends, and a fake `gh` that answers only from seeded repositories and refuses and logs anything else, so the trial reaches no real service; its checks read the call log for the model and effort each session start names, and its tests are in `tests/test_e2e_eval_session_model.py`.

T67 judges the worktree removal of `scripts/orca_status_hook.py` and its detached run `scripts/orca_cleanup_run.py`. The
fake `orca` also makes a real Git worktree for `worktree create` and `orchestration worker-start`; a started worker
commits, pushes its branch, reports `worker_done`, and has its terminal released at once, and `worker-list` and
`ports` read the `dispatches` and `ports` of the state file. The task sets `ORCA_USER_DATA_PATH`, which the harness removes from a trial and the hook's run requires, and
`HEI5ENBUG_CLEANUP_RUN_SECONDS` to 45, the
time after which a detached run ends itself and every process it started, so no run outlives a trial by more than 45
seconds and the 60-second wait below always covers it. The session ends its turn with a question, so the removal
can only come from the hook's run, which starts at that turn's end in a process session of its own. The checks wait up
to `E2E_CLEANUP_WAIT_SECONDS` (60 by default) for a successful removal, and a removal from the session's own folder
instead of the run's folder `/` fails `removed-by-hook`, so a session that removes the worktree itself, as the written
rule allowed before, does not pass. Its tests are in `tests/test_e2e_eval_worktree_cleanup_hook.py`.

T81 runs with a fake
`orca`, `claude`, and `codex` first on `PATH`, built by `tasks/setup/T81.py`, an installed copy of the plugin, and two
seeded sessions; it keeps its state in `orca-state/` and `plugin-state/` beside the repository and its tests are in
`tests/test_e2e_eval_refresh_reload.py`. The fake commands cannot start a real session or a detached helper's
long wait, so the task covers only what the call log and the final answer show.

T180 and T181 run in
the fictional plugin repository `skill-gap-plugin` with the stateful `gh` stub that `skills/skill-issue-creator/evals/`
ships, first on `PATH` and seeded by `tasks/setup/gh_stub_common.py`; its log and kept issues sit in `gh.log` and
`gh-state/` beside the repository, and their tests are in `tests/test_e2e_eval_skill_issue_cases.py`. Because the
harness cannot answer a question, T180 passes when the undecided choice is asked and the tracker is not written. T110 and T111 give the
answers in the prompt so the run reaches the write and the read-back; their informational check `check-filed-ran-after-write`
shows whether the run read the filed issue back with `check_filed.py`. T160 puts a fake `aside` first on `PATH`
(`tasks/setup/fake_aside.py`; its call log is `aside.log`, and `FAKE_ASIDE_MODE=fail` makes `aside exec` fail), and its
informational checks show whether the lookup went to the `browser-reader` agent. T161 reviews a Korean design document, and its
informational checks show which translationese reference the review read and whether it ran `check_format.py`; their tests are
`tests/test_e2e_eval_skill_issue_filing.py`, `tests/test_e2e_eval_aside_lookup.py`, and `tests/test_e2e_eval_design_review.py`.

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
| T81 | notes-cli | Orca plugin refresh | Apply the installed plugin version to running sessions, one of which waits only on a background task, with fake `orca`, `claude`, and `codex` |
| T35 | inventory-service | Delegated route that fails every time | A `--forecast` report option that the prompt hands to a role runner worker, with a seeded `claude` and `codex` that fail every child run with a different error; the launches must stop at the retry cap |
| T36 | inventory-service | Eight independent read-only questions | One question each about money, pricing, validators, importer, audit, clock, serialization, and formatting; wall time is the claimed measure |
| T31 | notes-cli | Handoff terminal that belongs to the handoff | A brief for one result: clean up a finished child worktree, report, then close the session's own terminal |
| T32 | notes-cli | Handoff brief to a terminal that already ran an agent | The same brief without the closing sentence, with a child worktree that holds an uncommitted change: close nothing, name the kept worktree |
| T33 | notes-cli | Agent start in a never-used shell terminal | Hand one result to a workspace whose only terminal is a never-used shell: send the host command there and create no terminal |
| T34 | notes-cli | First-prompt terminal cleanup | Read one setting while the plugin's hook closes the never-used shell terminal and leaves the one with typed input |
| T67 | notes-cli | Hook removal of a finished worker's worktree | A setting change, a worktree of demo-b created without an agent, and a worker started there; the turn ends with a question, and the worktree and its local branch must be removed by the hook's detached run, not by the session |
| T76 | notes-cli | Question dialog wording | Ask whether to delete two lines of an issue draft's five-line done-checklist that repeat other lines, for a user who asked to see it as a picture |
| T77 | notes-cli | Question dialog wording | Ask whether to drop two unused columns of `demo.orders`, for a user who asked to see the table as a picture |
| T22 | review-rounds | Ticket comment, first draft | Comment whose work item requires each step's time before and after and whose proposal the result replaced |
| T23 | review-rounds | Ticket comment, second draft | Revise a draft after a finding that it dropped the work item's exception for a first run without a cache |
| T24 | review-rounds | Ticket comment, second draft | Revise a draft after a finding that "the check deletes a loose cache" can mean before or after the cache runs |
| T25 | tool-marks | Pull request description | Notes say a document review by a named model at a stated effort found 3 problems, all applied, and the final text was not reviewed again |
| T26 | tool-marks | Commit message | Parser fix whose change note suggests a subject that names the reviewing model |
| T27 | tool-marks | Commit message | One-line change of a reviewer model setting from `demo-model-x` to `demo-model-y` |
| T28 | tool-marks | Chat message | Thread message that the request tells to say a named model reviewed the document |
| T29 | identifier-lists | Review reply | Draft whose rules require the names of the added tests and whose item names three added tests |
| T30 | identifier-lists | Pull request description | Draft whose diff shows three changed files and whose item lists the three files, under rules that ask for no names |
| T65 | stage-names | Ticket comment | Draft that runs "step 0" and "steps 3 to 8" of a nine-stage procedure and states a depth of 2 levels and 3 items |
| T66 | stage-names | Chat message | Status draft that calls a division "Phase 1" and its first item "1", which are Rollout and Schema extension in the plan |
| T78 | commit-demo | Commit skill, staged-only scope | Korean-subject history, one staged change beside an unstaged edit and an untracked `.env` |
| T79 | commit-demo | Commit skill, required identifier | Commit rules that require a ticket key, and a request that names none |
| T82 | demo-app | UI routing, complete specification | Four named-line edits to a settings panel; routes to the implementation worker |
| T83 | demo-app | UI routing, layout request | Two-column profile screen that stacks at 375 px; routes to the designer |
| T84 | demo-app | UI routing, open breakpoint | Plan cards 320 px wide and 24 px apart in one row, mobile breakpoint left open; routes to the designer |
| T101 | notes-cli | Built-in agent request is refused | One request for a `general-purpose` agent; the plugin must refuse it, no such agent may do any work, and nothing is changed |
| T112 | demo-app | UI routing, new screen | A new invoices screen of three rows built from scratch, fitting at 1280 and 375 px; routes to the designer at its pinned `xhigh` |
| T113 | notes-cli | Orca session start model | A skill issue for another plugin's repository, which the delegation rules hand to a new session there; a fake `orca` and a seeded plugin repository, and the run passes only when every session start names a model and effort and none names Fable or Astra |
| T37 | notes-cli | Worker delegation with a failure condition and a compatibility decision | `memo import FILE` that exits with code 3 and prints nothing on a missing file, and a new file format that keeps reading the old one |
| T38 | parcel-desk | Existing assertions beside a new behavior | Zone C billed in 250 g steps, where changing the shared step constant breaks the existing assertions about the other zones; edits in three or more files |
| T39 | parcel-desk | A stated behavior change that one assertion follows | `round_cents` changes from rounding down to rounding half up, and one existing test asserts rounding down |
| T40 | parcel-desk | Boundary and failure-path tests | A 40-parcel limit on `pickup_fee_cents` with a named error; the agent's own tests must pass on a reference and fail on four seeded faulty copies |
| T41 | shop-desk | Fewest new parts | A per-customer discount limit that the prompt confines to three named code files and one setting key; edits in three or more files |
| T42 | shop-desk | Reuse of an existing value | A `statement` command whose tax must follow the rate that `sales` uses, changed through `SHOP_TAX_PERCENT`; edits in three or more files |
| T43 | shop-desk | Explicit failure | An `export-orders` command that calls `StorageClient.upload`; the hidden test makes the client fail; edits in three or more files |
| T44 | shop-desk | Callers and consumers | `lookup_customer` returns a `Customer` instead of a dict; a second caller in another module and a file stored by the previous version must keep working; edits in three or more files |
| T45 | shop-desk | Evidence before assumption | A `top-customers` command built on `customers_by_spend`, whose docstring promises sorted output that the code does not give; the final report must name the function; edits in three or more files |
| T46 | shop-desk | Root cause of a reported defect | `shop place 1 ab-100:2` fails on a lowercase SKU; the broken rule lives in `catalog.price_cents`, which the `price` command and `place_order` also use |
| T47 | shop-desk | Repeat safety | An `import-orders` command that is rerun after a failure; a hidden test holds a first run after its read until a second run has finished, and starts four runs together; edits in three or more files |
| T48 | shop-desk | Real environment | Week labels that count from Sunday, which the README says the reporting database (SQLite) also computes, with `scripts/engine_check.py` as the local engine check |
| T62 | notes-cli | Worker delegation: named skill | A `memo count` command, with a changelog line that only the repository skill `changelog-entry` describes |
| T49 | tally-desk | Requirements agreement | `weekly DATE` and `archive OUT_DIR` with two open decisions; the sheet's week start, Sunday, contradicts the likely Monday |
| T50 | tally-desk | No agreement | `busiest DATE` and `archive OUT_DIR` with every decision stated in the prompt; no question may be asked |
| T51 | tally-desk | One question | A new rate cache that repeats `rate_for`'s `ttl_cached` cache; exactly one question, which names it |
| T140 | notes-cli | Stored question input | Summarize a resumed session whose earlier question input shows as `\uXXXX` escapes in the conversation while the stored transcript holds the kana |
| T141 | notes-cli | Stored question input | The same, with escape text in the stored transcript itself, then ask the question again |
| T180 | skill-gap-plugin | Issue filing, questions first | A gap note with one undecided Proposal choice, filed through `skill-issue-creator` |
| T181 | skill-gap-plugin | Issue filing, duplicate search | A gap note that an open issue of the same account already covers |
| T110 | skill-gap-plugin | Issue filing, answers given up front | T180 with both undecided choices answered in the prompt, so the run files the issue and reads it back |
| T111 | skill-gap-plugin | Issue filing, covered gap with the answer given | T181 with the answer given in the prompt, so the run merges it into the open issue and reads it back |
| T160 | notes-cli | Aside lookup, read only | A ticket status looked up through a stub `aside` that prints tool-trace noise; the answer must carry the status and the source only |
| T161 | design-review-demo | Design review, Korean | A review of a Korean design document seeded with a long line, a fourth-level heading, a trailing space, and one translationese phrase |
| T120 | tally-demo | Repository guidance, repeated correction | Wrap-up after the same naming correction came twice; a check candidate for that one class is shown, proven on a seeded earlier commit, and not written |
| T121 | tally-demo | Repository guidance, investigation decision | Decide between two queue libraries after a three-step investigation; an ADR draft of at most 30 lines and its entry line are shown, not written |
| T122 | tally-demo | Repository guidance, no trigger | One first-time unstated correction with no investigation; no recording recommendation and no `mistake-enforcer` run |
| T150 | scout-demo | Scout result contract, one function | The error `parse_pair` raises when no delimiter is present; the report starts with `pass`, quotes the function with path and line numbers, and labels the answer direct |
| T151 | scout-demo | Scout result contract, missing path | A question on `demo-lib/docs/missing.md`, which does not exist; the report starts with `blocked`, names the path, and states no conclusion about its content |
| T152 | scout-demo | Scout result contract, partial evidence | Delimiters and a maximum line length across two files where the length is absent; the report starts with `issues`, labels the length unknown, and proposes no fix |
| T153 | inventory-service | Worker model on hard work, forced delegation | Cross-process locking of one data file across the app and the CLI (concurrency, a public contract, several components), handed to the implementation worker by the request; the worker's model comes from the variant's `implementation_worker` route |
| T154 | skill-review-demo | Skill review role, grader | A `release-notes` run that misses one of three expectations, graded through Skill Builder; the grading marks exactly that expectation failed with a quote of the output, and a review-route run exists |
| T155 | skill-review-demo | Skill review role, comparator | Two release-notes outputs where one breaks the stated limit of five bullets, compared blind through Skill Builder; the comparison prefers the other output, names the limit, and a review-route run exists |
| T130 | ops-notes | Repeated review, no convergence | Fix `docs/guide.md` until a scripted `tools/review.py` reports nothing; it returns 5, 4, 6, and more new low findings |
| T131 | ops-notes | Repeated review, convergence | The same request; the scripted review returns 2, 3, then 0 findings |
| T132 | ops-notes | Repeated review, fix must spread | Three documents state a retry limit of 5 that `docs/decisions.md` sets to 3; the first run flags only one |

T62 measures the worker rule that loads a named skill. Its setup script commits `CHANGELOG.md` and the skill under both
`.claude/skills/` and `.agents/skills/`, and the prompt names the skill. The required check `skill-loaded` passes when a
worker loaded the skill (a `Skill` call on Claude Code, a read of its `SKILL.md` on Codex), or, when the run delegated no
implementation, when the main session did; `changelog-entry` passes only for a line in the skill's format, which hand work
cannot guess; the informational check `result-lists-skill` reads whether a worker result names the skill.
`scripts/skill_load_check.py` applies the same load rule to a host record, and `tests/test_worker_named_skill.py` seeds it.

T37 to T48 carry a marking that names what each case measures, and no harness code reads it: `handoff` on T37 and the
`field` of its constraints (an assignment field), `rule_test` on T38 to T40 and T07 (a testing rule item), and
`code_rule` on T41 to T48 and T02 and T08 (an implementation rule), and `agreement` on T49 to T51 (the requirements
agreement). Each lists the required checks that decide the case.

The ids T89 to T91 belong to the comparison of Claude reviewer models in
[`evals/model-roles`](../model-roles/README.md); its opponent ids T92 and T93 ended with the removal of their skill.
Those cases run through the role runners instead of this harness, so
they have no task file here.

T76 and T77 grade the last question dialog a run showed, from `AskUserQuestion` on Claude Code and `request_user_input`
on Codex; a call that the plugin's question guard denied for a self-made free-form option is not counted. Both fail a
dialog that holds a free-form option such as "Other" or "직접 입력". T76 also requires the key words of both flagged
lines and none of "acceptance criteria", "regression", "criterion", "reviewer", or their Korean equivalents; a delete
option and a keep option whose descriptions each name both flagged lines by key word or by a label that the dialog
gave them; and a diagram with all five lines, in an option's `preview` on Claude Code and below the first line of the
question text on Codex. T77 requires both column names in the dialog, in every option description, and in a drawn line
of the diagram. The only text the setup scripts seed is fictional, and `files-untouched` records, without failing the
run, whether the agent edited a file.

T140 and T141 give the stored transcript path and grade what the run read and said. T140 requires that the run read the
transcript and that no line says the model wrote escapes or broke the raw-character rule, drafts a defect report, or
notes to write raw characters next time; a line that denies it does not count. T141 requires that the run read the
transcript, say the stored input holds escape text, and ask the next question with the raw kana and no `\uXXXX`
sequence, in the dialog or, on a host without one, in the final answer. Both use the fictional file
`session/demo-session.jsonl`.

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
  `continue to five` or `second pair`, never `pass`. `--claim-cases` applies the claim to the named cases only.

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

### Request caps and the parallel limit

The cases of the request-budget rules are T35 (a route that fails every time), T05 (two independent changes), and T36
(eight independent read-only questions). One revision carries both variants, and they differ only by `env`. The before
variant sets `request_run_cap` and `request_retry_cap` to `0` (`CLAUDE_PLUGIN_OPTION_REQUEST_RUN_CAP` and
`CLAUDE_PLUGIN_OPTION_REQUEST_RETRY_CAP` on Claude Code, `HEI5ENBUG_REQUEST_RUN_CAP` and `HEI5ENBUG_REQUEST_RETRY_CAP` on
Codex) and `HEI5ENBUG_PARALLEL_LIMIT_MAX` to `6`, which behaves as before the change. The after variant leaves both caps at
their defaults and sets `HEI5ENBUG_PARALLEL_LIMIT_MAX` to `0`, which removes the maximum so the computed limit applies. The
`env` of T35 sets both retry-cap variables to `2` so that the check and the cap agree; a variant's `env` wins over the
task's, so the before variant's `0` replaces it and the after variant keeps `2`.

- T35: `tasks/setup/T35.py` puts a `claude` and a `codex` on `bin/` beside the repository. A call with
  `HEI5ENBUG_ASSIGNED_ROLE` set, which only a role runner child has, exits with the next of eight different errors; every
  other call goes to the next program of that name on `PATH`. The route is the Sol worker, `implementation_worker=sol`.
  `stops-at-cap` needs the message that starts with `Request cap reached` in a tool result after at most the retry cap plus
  one launches, `no-launch-after-denial` needs no delegation after it, `names-unfinished-deliverable` needs the report to
  name the forecast and say the work stopped, and `no-completion-claim` needs none of the seeded completion phrases in
  `seeded.completion_phrases`.
- T05: the added required check `no-launch-denied` fails when a tool result or the final answer holds `Request cap reached`
  or `Parallel limit reached`.
- T36: eight required `answer_contains` checks, one per question, and `no-changes`. Run it on a machine where
  `python3 scripts/parallel_limit.py` prints at least 8; the check of that number is not part of the grade.

`record --issue 97 --tasks T35,T05,T36 --claim wall_seconds --claim-cases T36` writes one record: quality and the host
comparison for the three cases, and the improvement claim of "Comparing a change on both hosts" for T36 only.
`tests/test_parallel_limit_record.py` reads `records/97.json`: the shipped maximum in `config/parallel-limit.json` is `6`
unless the claim of T36 is `accept`, and then it is `null`.

### Loop-shape candidates

Issue 102 compares changes to the shape of the independent text review loop on the writing tasks T13 to T20: (a) a worker
of the `language` capability runs the loop, (b) every run passes `--reviews 2`, (c) a run after the first drops a
`removable` finding outside the sentences changed since the previous run, and (d) the reviewer assignment asks for every
problem found in the run instead of an empty list for a careful draft. `variants/loop-baseline.json` and
`variants/loop-a.json` to `loop-d.json` name the revisions, the branches `p4-h-text` and `p4-h-text-102-a` to
`p4-h-text-102-d`. Run
the campaign from a checkout of the baseline revision: the text tasks grade with that checkout's `scripts/text_review.py`,
while the agent runs the `scripts/text_review.py` of its exported variant.

`loop-record` reads both hosts' runs of the baseline and of each `--candidate`, in the order they are adopted, and writes
`records/<issue number>.json` with every run's `loop` measures (`review_loop` of `metrics.json`) and `passed`, and a
`candidates` list with the verdict of each candidate and the step that decided it. `harness/loop_verdict.py` holds the
steps. A candidate is adopted only when all three hold; the first failing one rejects it, and an unfinished one leaves it
`undecided`:

- Writing rule: on each host, over the first run of T13 to T20, no task whose `text-review-clean` check passed on the
  baseline fails on the candidate, and the number of passing tasks does not fall.
- Improvement claim: on T13, T15, and T20 the claim of the comparison rule above is accepted on both hosts with `cost_usd`
  as the claimed measure.
- Host comparison: on T13, T15, and T20 the case verdict of the comparison rule above passes.

Two or more adopted candidates are then run together as `--combined` against the baseline in the same three steps; a
combined revision that is rejected drops the candidate adopted last (`dropped` in its entry), and the combined revision of
the rest runs again.

`build-combined` creates that combined revision: it adds a detached scratch worktree at `--base` (default folder
`<run-root>/combined/<base>+<candidates>`), merges each `--candidate` branch in the order given with `git merge --no-ff`, and
prints the SHA of the resulting commit as its only output line (progress goes to stderr). The merge commits have a fixed
identity and date, so the same inputs give the same SHA. It needs two or more distinct candidates that each descend from
the base. A candidate that conflicts aborts that merge, removes the scratch worktree, and fails with the candidate and the
conflicting files; an existing worktree folder is never overwritten. `--dry-run` prints the commands and creates nothing.
Put the printed SHA in `ref` of the `loop-combined` variant file. Nothing but the worktree's detached HEAD refers to the
commit, so run `git branch <name> <sha>` before removing the worktree with `git worktree remove`, or the commit can be
collected by Git. `tests/test_e2e_eval_loop_record.py` finds the text of each candidate in the repository only when the
record adopts it: `role_runner.py language` in `instructions/shared-text.md` for (a), `DEFAULT_REVIEWS = 2` for (b), and the
changed-sentence section of `scripts/text_review.py` with its sentence in `instructions/shared-text.md` for (c).

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
