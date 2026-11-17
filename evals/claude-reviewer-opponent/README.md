# Claude reviewer and opponent evaluation

This evaluation measures whether `claude-fable-5-2` reviews and debates better than `claude-opus-5-5`, so that the
Claude model and effort of the tiki-taka opponent and of the reviewer of GPT-authored work rest on a recorded
comparison instead of a version bump. It answers issue #84. It runs real model sessions and spends real usage, so it
is not one of the development checks in the repository README; only its unit test,
`tests/test_reviewer_opponent_eval.py`, is.

## Question

For each role, which of four candidates, `claude-opus-5-5` and `claude-fable-5-2` each at `high` and `xhigh`, passes
the most of that role's fixed cases? Among candidates tied on passes, the one with the lowest list-price cost on that
role's cases wins. The reviewer role counts only the three review cases and their cost; the opponent role counts only
the two debate cases and their cost.

## Cases

`cases.json` freezes five cases. Each has a fixed list of real problems, built from fictional sources.

| Case | Role | Deliverable | Planted problem |
|---|---|---|---|
| `r1` | Review | GPT-written diff | `JobStore.claim_next` reads and updates shared state without the lock that every other method holds |
| `r2` | Review | GPT-written diff | `export_report` returns `bytes` where `docs/api.txt` and the CLI consumer require `str` |
| `r3` | Review | Issue body | The Proposal limits retries to 3 at a fixed wait while acceptance criterion 2 requires unlimited retries with a doubling wait |
| `d1` | Debate | Design proposal | Idempotency keys live in a per-process set while the service runs 3 replicas behind a round-robin balancer |
| `d2` | Debate | Design proposal | Rate limits load once at start while requirement R2 needs a change to apply within 60 seconds |

Each case folder under `cases/` holds the material the candidate sees: a `workspace/` that the candidate may read, and
for a review case `change.diff` or `issue.txt`. `accepted_related` lists true related observations that do not count
against a candidate; any finding outside `real_problems` and `accepted_related` does. Change a case or a list only as
a new frozen set, and rerun every candidate on it.

## Runner

`cr_run.py` has three commands. Run them from the repository root. Every candidate is a Claude model, so the run needs
the Claude Code CLI and no Codex CLI.

```text
python3 evals/claude-reviewer-opponent/cr_run.py run     --out <folder> [--candidates opus-high,fable-xhigh] [--cases r1,d1] [--parallel 4]
python3 evals/claude-reviewer-opponent/cr_run.py summary --out <folder>
python3 evals/claude-reviewer-opponent/cr_run.py decide  --out <folder>
```

The candidate ids are `opus-high`, `opus-xhigh`, `fable-high`, and `fable-xhigh`. An existing output folder is resumed:
a finished run is not run again.

| Setting | Value |
|---|---|
| Review call | `scripts/role_runner.py reviewer --model <id> --effort <effort>` in a copy of the case workspace, with the case's intent, evidence, complete draft, and the "Review checks" of `instructions/independent-model-validation.md`, read at run time |
| Debate call | The unchanged `skills/tiki-taka/run-opponent.sh --opponent claude --max-exchanges 1` from a copy of the skill whose registry names the candidate, with the exchange 1 prompt of the skill and a host statement that finds no issue |
| Verification | The runner checks the model and effort in the Claude Code records; a run whose model or effort differs is not verified and decides nothing |
| Cost | List price from the session transcript, by the price table of `evals/e2e/harness/usage.py` |
| Limits | A 900 second limit per call; each candidate runs its cases in order and the candidates run in parallel |
| Budget | 20 runs, 4 candidates on 5 cases once each; retries count and an unverified run is not replaced silently |

The output folder holds, per candidate and case, `assignment.txt` for a review, `answer.txt`, `runner.log`, and
`status.json` with the verified model, effort, seconds, and cost.

## Grading

Read each `answer.txt` against the case's fixed lists, then write `<folder>/grades.json` as
`{"<candidate id>": {"<case id>": true or false}}`.

- A review case passes when a finding names the planted problem with its location and its effect and no finding falls
  outside `real_problems` and `accepted_related`.
- A debate case passes when the candidate's first statement names the planted flaw and raises no objection outside
  `real_problems` and `accepted_related`.

## Decision rule

`decide` ranks the candidates per role by passes, then by the lowest cost on that role's cases, and names the first as
the role's winner. A role has no winner while any of its runs is missing, unverified, off its model or effort, without
a cost, or ungraded: an infrastructure failure is neither a pass nor a fail. When Opus wins a role, the role names Opus
and Fable stays available only when the user asks for it.

## Results

Not run yet.
