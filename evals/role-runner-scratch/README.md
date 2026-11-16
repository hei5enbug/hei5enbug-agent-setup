# Role runner scratch folder evaluation

This evaluation holds the seeded repository and the deterministic checks for the model runs of the scratch-folder
and `--validation` change of `scripts/role_runner.py`. Starting a run is the only step that costs model calls;
seeding, snapshots, and checks cost none, and `tests/test_role_runner_demo.py` tests them.

## Cases

Each case is one run, with these fixed conditions as its pass or fail criteria.

| Case | Run | Pass when |
|---|---|---|
| 5, validation on Codex | `role_runner.py reviewer --model gpt-6.1-sol --validation` over the seeded repository with no installed environment, assigned to review `pricing.py` | The tool records show a test command and the seeded assertion failing, the review names `test_bulk_discount`, and the repository snapshot is unchanged |
| 6, validation on Claude | `role_runner.py reviewer --model claude-opus-5-5 --validation` over the seeded repository with its environment installed (`seed --with-env`) | The same conditions as the Codex case |
| 7, heredoc scout on Codex | `role_runner.py scout` without `--validation`, assigned to total `quantity * unit_cents` over `data/orders.csv` with a heredoc Python command | The tool records show a heredoc Python command that did not fail on its temp file, the result holds the expected total, no test or install command ran, and the repository snapshot is unchanged |

## Steps by hand

```text
python3 evals/role-runner-scratch/demo.py seed /tmp/work/demo-a
python3 evals/role-runner-scratch/demo.py snapshot /tmp/work/demo-a /tmp/work/before.txt
# run the role runner from /tmp/work/demo-a, then:
python3 evals/role-runner-scratch/demo.py check <validation|scout> /tmp/work/demo-a \
  --records <rollout or transcript> --result <result file> --before /tmp/work/before.txt
```

`check` prints one JSON line with `pass` and the list of failures, and exits 1 when any failure remains. The seeded
defect is a discount that starts at eleven units while the docstring and `test_bulk_discount` say ten.

## Driver

`run_cases.py` performs the three runs: for each case it seeds `<workdir>/demo-<case>` (with `--with-env` for case 6),
snapshots it, writes the case's assignment, runs `scripts/role_runner.py` from the seeded repository, reads the rollout or
transcript path from the verified status line the runner prints, and runs `check` on it. It prints one JSON line per case
with `pass`, `failures`, and `records`, and exits 1 when any case fails or the runner did not verify a run.

```text
python3 evals/role-runner-scratch/run_cases.py --dry-run
python3 evals/role-runner-scratch/run_cases.py 5 6 7 --workdir /tmp/work
```

`--dry-run` prints every command and starts nothing: it creates no folder and calls no model. Case numbers select cases, and
all three run by default. `--runner` names another runner script and `--timeout` passes the runner's own option.
`tests/test_role_runner_run_cases.py` tests the dry run, the status-line parsing, and the whole sequence with a fake runner.
