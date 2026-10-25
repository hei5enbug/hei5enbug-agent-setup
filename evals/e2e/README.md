# End-to-end golden evaluation

This harness measures the plugin as a whole coding-agent harness. Each run starts `claude -p` with one plugin
revision loaded, gives it a realistic development task in a throwaway fictional repository, and grades the result.
Two variants run the same tasks under the same conditions, so their results can be compared.

The harness runs real agent sessions and spends real model usage. It is not one of the development checks in the
repository README; only its unit tests are.

## What one run does

1. The harness exports the variant's plugin revision with `git archive <ref>` into
   `<run root>/plugins/<sha>/hei5enbug-agent-setup/`. The export leaves out `evals/` and `tests/test_e2e_eval_*.py`,
   so an agent that reads the plugin source cannot see the hidden tests, the reference solutions, or expected answers.
2. It copies the task's fixture from `fixtures/` into `<run root>/<campaign>/work/<run id>/repo/`, commits it with a
   fixed fictional identity and date, and runs the task's setup script when it has one.
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
`harness/approval_mcp.py`, passed as `--permission-prompt-tool`. It approves every request and logs it to
`approvals.jsonl`. The number of lines is the approval-prompt count, a friction metric. A plugin hook that returns
`ask` reaches this tool; the pilot confirmed this with a forced `git clean -f`. Calls that the permission mode or the
plugin's guard allow without a prompt never reach it, so they are not counted.

The harness cannot answer a question that the agent asks with `AskUserQuestion`. The approver lets the call through,
and the run ends with the question unanswered. Task prompts therefore leave no decision open that would change the
result.

## Commands

Run every command from the repository root. The default run root is
`~/.local/state/hei5enbug-agent-setup/harness-eval/runs`; `--run-root` changes it.

| Goal | Command |
|---|---|
| Show the plan and exact commands | `python3 evals/e2e/harness/cli.py run --campaign <name> --dry-run` |
| Run or resume a campaign | `python3 evals/e2e/harness/cli.py run --campaign <name> --variants baseline --reps 3` |
| Run selected tasks | add `--tasks T01,T03` |
| Rerun finished runs | add `--only-rerun T03-baseline-r1,T03-baseline-r2` |
| Grade again after a grader fix | `python3 evals/e2e/harness/cli.py regrade --campaign <name> [--run-ids ...]` |
| Copy the records again, then grade | add `--recollect` to `regrade` |
| Resume after changing a task or variant | add `--allow-changed-inputs` to `run` |
| Check the pilot facts per run | `python3 evals/e2e/harness/cli.py pilot-check --campaign <name>` |
| Print tables | `python3 evals/e2e/harness/cli.py summarize --campaign <name> [--out file.md]` |
| Compare two variants | `python3 evals/e2e/harness/cli.py summarize --campaign <name> --compare baseline,<other>` |
| Export a revision only | `python3 evals/e2e/harness/cli.py export-plugin --ref <ref>` |

`--parallel` sets the number of runs at once (default 3). With several variants the order alternates per task and
repetition (ABAB, then BABA), so time-of-day effects spread evenly.

Running the same `run` command again resumes the campaign. Finished runs are skipped. A run that failed for an
infrastructure reason or hit a usage limit is started again, and its old records and work folder move to
`attempts/rep<k>/<n>/`. When a run reports a usage limit, the harness starts no new run, lets running ones finish, and
exits with code 75.

The first `run` stores each variant's resolved revision and fingerprints of the variant and task inputs in
`campaign.json`. A resume whose inputs differ stops, unless `--allow-changed-inputs` is given; then the harness
records the change in `campaign.json`.

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
  results/<task>/<variant>/rep<k>/
    run.json  prompt.txt  command.json  settings.json  mcp.json  env.json
    stream.jsonl  stderr.txt  approvals.jsonl
    transcripts/main.jsonl  transcripts/subagents/  transcripts/runner/  codex/  assignments/
    view.json  grade/grade.json  grade/rubric.json  metrics.json
```

`env.json` records the Claude Code and Codex CLI versions, the installed plugin list, SHA-256 hashes of the Claude and
Codex settings files (never their content), the names of the removed variables, and the harness revision.

## Metrics

Each `metrics.json` separates measured values from estimates.

| Metric | Source |
|---|---|
| Success, correctness, test pass rate, regressions | Graders. Success means every required check passed and, for a rubric task, the rubric mean reached its pass mark. Correctness is the weighted share of passed checks. |
| Tokens by model and source | Main transcript and subagent records, deduplicated by message ID; Codex `token_count` events per rollout. |
| `claude_total_cost_usd` | The result message of `claude -p`, a client-side estimate. |
| `claude_list_cost_usd` | Tokens priced with `harness/pricing.py` (official Claude list prices, checked 2026-10-25). |
| `codex_list_cost_usd_estimate` | Codex tokens at OpenAI API list prices (checked 2026-10-25). It is an estimate: Codex runs on a ChatGPT plan, which is not billed per token. |
| Wall time, turns, tool calls by tool, subagent launches by type | Harness clock and the stream; Codex tool calls are counted under their own key. |
| Role runner calls by role and exit code | Bash calls of `role_runner.py` and their status lines. |
| Retries | A failing Bash command run again, an agent type launched again after an error, a role runner run again after a non-zero exit. |
| Approval prompts, permission denials | `approvals.jsonl` and the result message. |
| Spend including attempts, cost per success | Summary only: every attempt of a task, and that spend divided by the successes. |
| Handoff loss | Task constraints that the main session knew but that a delegation prompt did not mention, and checks that failed because of it. |

## Graders

The graders in `harness/graders.py` check the final repository against its base commit. Check kinds include the
pre-existing tests (the fixture's own test files, restored over any edits), hidden tests, changed-path limits, text
checks, commit checks, line coverage, and forbidden commands or leaked values in the transcript. A task's custom
checks live in `tasks/custom/`.

The rubric grade covers only what a script cannot judge: design quality for T01 and answer quality for T10. The
assignment holds the task prompt, the rubric, and the artifact, but no variant name, revision, or model name. It runs
in `<campaign>/rubric/<opaque id>/`, a folder whose name reveals no variant, through `python3 scripts/role_runner.py reviewer --model gpt-6-astra --effort xhigh`. When the runner exits with 3 or
4, `claude-opus-5-5` grades instead, and `rubric.json` records the fallback.

`tests/test_e2e_eval_graders.py` proves each task's graders: the unmodified fixture fails, and the reference
solution in `tasks/reference/` passes.

## Golden tasks

Prompts are in Korean, as the real user writes them. The fixtures are fictional repositories with the conventions a
real one has: a README, an `AGENTS.md` with a Korean mirror rule, tests, and Korean mirrors.

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

## Known limits

- Calls that need no prompt in the user's permission mode are not counted as approvals, so the approval count
  measures prompts the user would see, not every guarded call.
- The Codex cost is an estimate at API list prices, and the long-context tier is chosen per request from its input
  size. Codex tokens of a rollout that does not start in the run's folder are not collected.
- A handoff constraint counts as missing when none of its keywords appear in a delegation prompt. A paraphrase
  without a keyword counts as missing.
- Runs share the user's Claude and Codex accounts, so usage limits and service load affect every variant.
- Only a usage limit of the agent's own Claude session stops a campaign. A Codex quota failure inside a run is part of
  the agent's outcome and shows up as a role runner exit code.
