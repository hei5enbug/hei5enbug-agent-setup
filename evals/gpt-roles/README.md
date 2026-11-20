# GPT role comparison

This evaluation decides which GPT model each role of the registry runs, by the owner's rules of 2026-11-20. Roles that run
`gpt-6.1-sol` compare `gpt-6.1-sol`, `gpt-6.2-sol`, `gpt-6.1-terra`, and `gpt-6-luna`. Roles that run `gpt-5.6-luna` compare
`gpt-5.6-luna` and `gpt-6-luna`. Starting a run is the only step that costs model calls; the decision, the grading, and the
cost reading cost none, and `tests/test_gpt_roles.py` tests them. No candidate is an Astra model.

## Cases

Each case is one run of one candidate at the role's registry effort, graded by a fixed pass or fail rule. A role's decision reads
only that role's cases.

| Role | Cases | Source | Run through |
|---|---|---|---|
| `reviewer` | T89, T90, T91, S5 | `evals/model-roles` cases and scratch case 5 | `role_runner.py reviewer` |
| `text_review` | TR1, TR2 | new: a draft with one planted defect | `text_review.py review --model` |
| `opponent` | T92, T93 | `evals/model-roles` cases, at `xhigh` | `run-opponent.sh --opponent codex` |
| `language` | t1, t3, t5 | `evals/korean-writing` tasks, one Claude grader | `kw_run.py` |
| `worker` | W1, W2, W3 | new: seeded repositories with hidden tests | `role_runner.py worker` |
| `scout` | S7, SC1, SC2, SC3 | scratch case 7 and the scout-demo questions of T103 to T105 | `role_runner.py scout` |
| `researcher` | R1 | new: one web search question | `role_runner.py researcher` |

The role runner starts only the models its registry lists, so every run uses a copy of the plugin that `git archive` exports
and whose `runner.review_models` also lists `gpt-6.2-sol` and `gpt-6-luna`. The repository's registry is not changed.

## Run

```text
python3 evals/gpt-roles/gr_cli.py plan
python3 evals/gpt-roles/gr_cli.py run T89 gpt-6.2-sol --out $WORK
python3 evals/gpt-roles/gr_cli.py language-results --out $WORK
python3 evals/gpt-roles/gr_cli.py decide --out $WORK
```

`run` exits 0 when it wrote a result, whether the case passed or not, and exits 3 when the run could not be graded: no verified
status line, a model other than the candidate in the rollout, or a model without a list price. Cost is the list price of every
request in the run's own Codex rollout (`harness/pricing.py`); wall time is the runner's own duration. A case with several reps
counts as passed only when every rep passed, and by its mean cost and wall time.

The scratch case 7 check compares the total without thousands separators, because a correct answer such as `3,075` failed the
original check.

## Decision

`decide` applies `docs/dev-rules/evaluation.md` per role: pass every case, drop a candidate more than 1.5 times and 60 seconds
slower on a case, take the lowest cost, and let the faster candidate win within 10 percent or $0.05. It then prints the registry
rows to change:

- `gpt-6.2-sol` replaces `gpt-6.1-sol` everywhere only when it passes every case `gpt-6.1-sol` passes in every sol role, is
  dropped on no case, and costs less over all sol-role cases outside the tie band. A role that `gpt-6.1-terra` or `gpt-6-luna`
  wins by the rule takes that model alone.
- `gpt-6-luna` replaces `gpt-5.6-luna` in a role when it passes every case `gpt-5.6-luna` passes, is not dropped, and costs no
  more outside the tie band. `runner.role_model` changes only when every luna role changes.
- A new language winner still needs the owner's blind comparison of its drafts against the current ones.
