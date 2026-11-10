# Korean writing evaluation

This evaluation measures which model writes Korean text that people read most naturally, so that the model of the
`language` capability and of `scripts/text_review.py` rests on a recorded comparison instead of an impression. It
answers issue #72. It runs real model sessions and spends real usage, so it is not one of the development checks in
the repository README; only its unit test, `tests/test_korean_writing_eval.py`, is.

## Question

Over five kinds of Korean text built from fictional sources, does one candidate writer produce drafts that graders of
both model families rank first on more than half of the task-runs, with every required fact present and no fact
added? If so, that candidate wins. Otherwise the result is inconclusive and the current models stay.

## Cases

`cases.json` freezes five tasks. Each has a kind, a reader, fictional sources, and required facts in meaning, with
five or six facts per task.

| Task | Kind | Source |
|---|---|---|
| `t1` | Ticket comment | Ticket `ABC-123` about `demo-a` and English dev notes for the fix |
| `t2` | Chat message | Release notes draft of `demo-a` 2.3.0 |
| `t3` | Pull request description | Author's English task notes about webhook retries |
| `t4` | Shared document section | Handbook notes about a review rule for `main` |
| `t5` | Final report | A user request and the agent's work log |

Change a case, a fact, or a seeded pair only as a new frozen set, and rerun the baseline model on it.

## Runner

`kw_run.py` has three commands. Run them from the repository root.

```text
python3 evals/korean-writing/kw_run.py run       --out <folder> [--runs 5] [--tasks t1,t3] [--parallel 4]
python3 evals/korean-writing/kw_run.py seeded    --out <folder>
python3 evals/korean-writing/kw_run.py aggregate --out <folder>
```

`--writer <host>:<model id>` and `--grader <host>:<model id>` replace the defaults and repeat once per model; the host
is `codex` or `claude`. The defaults are the four candidates `codex:gpt-6.1-sol`, `claude:claude-opus-5-5`,
`codex:gpt-6.1-terra`, and `claude:claude-fable-5-2`, and the two graders `codex:gpt-6-astra` and
`claude:claude-opus-5-5`. An existing output folder is resumed: finished drafts and grades are not run again.

| Setting | Value |
|---|---|
| Writing rules | Read at run time from `instructions/shared-text.md`: items 1 and 2 of "Cut and completeness passes" and all of "Readable shared text". The runner keeps no copy, so the rules cannot drift. |
| Claude Code call | `claude -p --model <id> --effort high --output-format json --strict-mcp-config --tools ""` with a settings file that disables the plugin. The result must name the requested model in `modelUsage`, or the draft counts as failed. |
| Codex call | `codex exec -m <id> -c model_reasoning_effort="high" -s read-only --ephemeral --ignore-user-config --ignore-rules` in an empty folder under the output folder. The plugin is not loaded and no command or file is available to the model. |
| Writer input | The same rules, kind, reader, and sources for every candidate; the model cannot run anything or look anything up. |
| Parallelism | Four calls at once, a 900 second limit per call, and a 3 hour limit for the whole run. |
| Failures | A failed call is tried again from a shared budget of 10. A model with two consecutive failures is left out and the reason is recorded in `campaign.json`. A quota message stops the run. |

The output folder holds `drafts/`, `grades/`, `seeded/`, `prompts/` (the exact writer and grader prompts), `raw/`
(CLI output), `run.log`, `campaign.json`, and, after `aggregate`, `summary.json`.

## Blind grading

For every task and run, all candidates' drafts go into one grader prompt under the labels A, B, C, and D. The label
order comes from a seeded shuffle of the task and run, so it differs between runs but is the same when the run is
repeated. The prompt carries the rules, the sources, the required facts, and the drafts; it never names a writer.

Each grader returns, per draft, the missing required facts, the added facts, and every unnatural or translated
phrasing with its quote. It then ranks the drafts that have no missing and no added fact from most to least natural,
and also ranks all drafts by naturalness alone. A draft with a missing fact fails the fact criterion however natural
it reads. The runner starts one grader of each family on every task-run.

## Seeded checks

`seeded.json` holds two pairs of drafts that differ in one planted flaw. `kw_run.py seeded` runs every grader on each
pair in both draft orders and counts a check as caught only when the grader behaves as follows.

| Pair | Planted flaw | The grader must |
|---|---|---|
| `s1_missing_fact` | The ticket comment leaves out the staging verification (`t1`, fact `f4`) | Report `f4` missing in that draft and nothing missing in the other, and rank only the other |
| `s2_calque` | The handbook section writes 계약 where 규칙 is meant (`t4`) | Report no fact problem, rank the fixed draft first, and list more unnatural phrasings for the flawed one |

Run the seeded checks before a full run; a grader that misses one cannot be trusted for the ranking.

## Decision rule

A candidate wins only when the graders of both families rank it first on more than half of the graded task-runs and no
grader reports a missing or added fact in any of its drafts. Otherwise the result is inconclusive and the current
`language` and review models stay. `aggregate` applies this rule. A result from fewer than five drafts per candidate
is marked unconfirmed.

Elapsed time and the cost the host reported are recorded for each candidate but do not decide the winner. Quality
comes first: the rule never trades a fact failure or a less natural draft for speed or price.

## Results

Run on 2026-11-10: four candidate writers, two graders, five tasks, five runs each, so 100 drafts and 25 graded
task-runs per grader. No call failed or needed a retry, and no candidate was left out. The seeded checks were
caught in all 8 grader runs (2 pairs, 2 orders, 2 graders). Each grader found no fact-clean draft in one task-run
and ranked none first there, so its first places add up to 24 of 25.

| Candidate | First places, `gpt-6-astra` | First places, `claude-opus-5-5` | Drafts with a missing fact, astra / opus | Drafts with an added fact, astra / opus | Unnatural phrasings, astra / opus | Median writer time |
|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | 13 | 6 | 6 / 5 of 25 | 0 / 1 of 25 | 21 / 73 | 99 s |
| `claude-opus-5-5` | 4 | 4 | 3 / 0 of 25 | 10 / 11 of 25 | 55 / 65 | 53 s |
| `gpt-6.1-terra` | 4 | 4 | 13 / 10 of 25 | 0 / 1 of 25 | 24 / 67 | 75 s |
| `claude-fable-5-2` | 3 | 10 | 2 / 0 of 25 | 6 / 5 of 25 | 45 / 55 | 41 s |

The Claude Code CLI reported 0.84 USD for the 25 `claude-opus-5-5` drafts and 2.24 USD for the 25 `claude-fable-5-2`
drafts. The Codex CLI reports tokens but no cost, so no cost is recorded for the two GPT candidates. The graders
agreed on the first place in 12 of 25 task-runs.

Verdict: inconclusive, language and review models unchanged. No candidate was ranked first on more than half of the
task-runs by both graders (13 of 25 is the most any candidate reached, and only from one grader), and every candidate
had drafts with a missing or an added fact.

### Limits

- The result is one pass of 25 task-runs per grader. It does not show which candidate is better, only that this
  measurement did not produce a winner.
- Each grader favoured its own family: `gpt-6-astra` ranked the GPT candidate `gpt-6.1-sol` first most often, and
  `claude-opus-5-5` ranked the Claude candidate `claude-fable-5-2` first most often. The rule of both families
  exists for this reason.
- Other evaluations ran at the same time, so writer times are confounded and show only an order of magnitude.
- The count of unnatural phrasings depends on how many each grader lists: `claude-opus-5-5` lists more than
  `gpt-6-astra` for every candidate, so compare the counts within one grader only.
- Owner pick between disagreeing graders, which issue #72 proposes, was not used: it cannot change a verdict that
  needs a majority from both graders.
- Drafts are kept in the output folder and are not reproduced here.
