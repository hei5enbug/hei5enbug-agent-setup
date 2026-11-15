# Role runner scratch folder evaluation

This evaluation holds the seeded repository and the deterministic checks for the model runs of the scratch-folder
and `--validation` change of `scripts/role_runner.py`. Starting a run is the only step that costs model calls;
seeding, snapshots, and checks cost none, and `tests/test_role_runner_demo.py` tests them.

## Cases

Each case is one run, with these fixed conditions as its pass or fail criteria.

| Case | Run | Pass when |
|---|---|---|
| Validation on Codex | `role_runner.py reviewer --model gpt-6.1-sol --validation` over the seeded repository with no installed environment, assigned to review `pricing.py` | The tool records show a test command and the seeded assertion failing, the review names `test_bulk_discount`, and the repository snapshot is unchanged |
| Validation on Claude | `role_runner.py reviewer --model claude-opus-5-5 --validation` over the seeded repository with its environment installed (`seed --with-env`) | The same conditions as the Codex case |
| Heredoc scout on Codex | `role_runner.py scout` without `--validation`, assigned to total `quantity * unit_cents` over `data/orders.csv` with a heredoc Python command | The tool records show a heredoc Python command that did not fail on its temp file, the result holds the expected total, no test or install command ran, and the repository snapshot is unchanged |

## Steps

```text
python3 evals/role-runner-scratch/demo.py seed /tmp/work/demo-a
python3 evals/role-runner-scratch/demo.py snapshot /tmp/work/demo-a /tmp/work/before.txt
# run the role runner from /tmp/work/demo-a, then:
python3 evals/role-runner-scratch/demo.py check <validation|scout> /tmp/work/demo-a \
  --records <rollout or transcript> --result <result file> --before /tmp/work/before.txt
```

`check` prints one JSON line with `pass` and the list of failures, and exits 1 when any failure remains. The seeded
defect is a discount that starts at eleven units while the docstring and `test_bulk_discount` say ten.
