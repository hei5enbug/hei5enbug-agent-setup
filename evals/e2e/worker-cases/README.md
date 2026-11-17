# Worker-model cases

Ten fictional-fixture tasks, `T68` to `T77`, that compare coding-agent models on hard work. They are the cases of
[issue 87](https://github.com/hei5enbug/hei5enbug-agent-setup/issues/87): `claude-sonnet-5-5` and `claude-opus-5-5`
at `high`, one run each per case. Every later comparison of coding-agent models reuses them. They share the task
layout of the [golden tasks](../README.md#golden-tasks), but `run` leaves them out unless `--tasks` names them, so a
default campaign is unchanged.

## Cases

Each task file carries `"worker_case": true` and a `"worker_criteria"` label from five criteria: `components`
(several components), `public-contract` (a public contract), `security`, `concurrency`, and `hook-guard` (a hook or
guard change). A case passes for a model when both required hidden checks pass: `hidden-tests` and `regressions`.
The fixtures and values are fictional; each case is shaped after work this repository's own history of the last 30
days shows, not after any other repository.

| Task | Fixture | Criteria | Request | Shaped after |
|---|---|---|---|---|
| T68 | guard-kit | hook-guard, security | Judge a write by the real path behind a link | Approval guard denying a write that resolves into installed plugin code |
| T69 | guard-kit | hook-guard, public-contract | A hook ends within half its timeout with a clear deny or silence | Hooks finishing in time with a deny that names the hook |
| T70 | guard-kit | security | Scan every commit of an outgoing range | Public boundary scan of each file version a range introduces |
| T71 | job-queue | concurrency | Hold the long lock only while sending; keep state under a short lock | Refresh helper holding the sessions lock only while it sends |
| T72 | job-queue | concurrency, public-contract | Claim each job once across processes, and add a batch claim | Shared-state locks of the refresh and approval code |
| T73 | plugin-host | components, public-contract | Add a value to an option across manifest, context, route text, docs, and mirrors | A new route value added end to end |
| T74 | plugin-host | components | Move conditional rules behind one entry line, with their mirror | Moving how-to-ask details out of the always-loaded rules |
| T75 | plugin-host | public-contract | `-h` and `--help`, unknown options, and exit codes of a tool | A tool printing its usage for `-h` instead of reading it as a path |
| T76 | guard-kit | hook-guard, security | Read the refs a push command sends | Reading redirections and no-ref pushes in the push check |
| T77 | job-queue | concurrency, hook-guard | A grant store that loses no grant, and a hook that never raises | Approval-state locking and hooks that ask instead of failing |

Every criterion is carried by at least one case. `tests/test_e2e_eval_worker_cases.py` proves each task: the
unmodified fixture fails `hidden-tests` and passes `regressions`, and the reference solution in
`tasks/reference/<task>/` passes both.

## How a run delegates

Each prompt is an assignment: allowed paths, the check to run, and the instruction to report instead of widening
scope. The variants `worker-sonnet` and `worker-opus` set `HEI5ENBUG_ASSIGNED_ROLE=worker`, so the plugin gives the
session the assigned-worker context, and set only the Claude Code model. The model under test therefore does the
work itself, from the same start state, plugin revision, checks, and effort, with no delegation of its own.

## Run and record

```text
python3 evals/e2e/harness/cli.py run --campaign worker-models --tasks T68,T69,T70,T71,T72,T73,T74,T75,T76,T77 --variants worker-sonnet,worker-opus --reps 1
python3 evals/e2e/harness/cli.py pilot-check --campaign worker-models
python3 evals/e2e/harness/cli.py worker-results --campaign worker-models
```

`worker-results` reads each run's model and effort from the host records, refuses a case that lacks a finished run,
started a role other than the main session, or ran another model or effort, and writes `results.json` here. The file
holds, per case and model, `passed`, `model`, `effort`, and `cost_usd`, and per model the `cost_usd` of all its
attempts, the number `solved`, and `cost_per_solved_task`, which is `null` for a model that solved nothing. Until the
measurement runs, the file holds only its pending form, `"measured": false`.

## Rule

A criterion counts as hard work only when, among the cases that carry it, Opus passes strictly more than Sonnet.
Hard work goes to `opus-worker`, easy work stays with `worker`, and all other work stays with `sonnet-worker`, also
when the passes tie. `worker-results` prints the criteria the rule returns, and `tests/test_worker_tier_rule.py`
checks that the repository holds the Opus worker definition, its registry entry, and its route text if and only if
the rule returns at least one criterion. When none qualifies, add no Opus tier and write that result here.

Result: not measured yet.

## Opus worker candidate

The candidate is kept out of `agents/`, the registry, and the route text until the measurement decides.
`opus-candidate/` holds `opus-worker.md.candidate`, pinned to `claude-opus-5-5` at `high` with the shared worker body,
and its Korean mirror. `opus_candidate.py` applies it to a checkout for the criteria that qualified, and
`tests/test_worker_tier_rule.py` keeps it equal to the current worker definition:

```text
python3 evals/e2e/worker-cases/opus_candidate.py <repository root> <criterion>[,<criterion>...]
```

It adds the agent and its mirror, registers the agent in `claude_agents` with the runner fallback of `sonnet-worker`,
and rewrites the route sentences of `instructions/claude-agents.md` and `instructions/model-routing.md`. The same
change then updates the Korean mirrors of those sentences, the documents that list the worker agents, the
`AGENTS.md` worker table outside its protected section, the manifest description, and the tests that pin the earlier
sentences.
