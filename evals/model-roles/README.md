# Claude reviewer and debate opponent comparison

This evaluation decides which Claude model and effort three roles pin: the tiki-taka Claude opponent, the stronger
Claude reviewer of GPT-authored work in the independent model validation rules, and the complex GPT-authored row of the
final review table in `AGENTS.md`. Four candidates run five seeded cases once each: `claude-opus-5-5` and
`claude-fable-5-2`, each at `high` and `xhigh`. Starting a candidate run is the only step that costs model calls;
seeding, grading, evidence reading, the record, and the pin check cost none, and `tests/test_model_roles_cases.py` and
`tests/test_model_roles_record.py` test them.

The cases use the ids T89 to T93. The golden harness in `evals/e2e` does not run them: each candidate runs through the
runner its role uses, so the model and effort come from that runner's own host records.

## Cases

Each case is one repository the harness creates from `cases/<id>/` with fixed commits, and each has a fixed list of
real problems in `cases/<id>/case.json`. The candidate sees the repository and its prompt, never `case.json`.

| Case | Role | Seeded material | Planted problem |
|---|---|---|---|
| T89 | reviewer | A GPT-style change that adds `SeatMap.hold_many` to a thread-safe class | `hold_many` checks the held seats and the capacity before it takes the lock |
| T90 | reviewer | A GPT-style change that renames the documented response field `total_cents` | The consumer `reports/export.py` and `docs/API.md` still use the field |
| T91 | reviewer | An issue body | Proposal 2 lets entries expire only after 15 minutes, and acceptance criterion 2 requires 30 seconds |
| T92 | opponent | A design for webhook retries and the host's opening statement that approves it | Every retry gets a new `X-Delivery-Id`, and a subscriber cannot detect a repeated event |
| T93 | opponent | A design that shards the orders table by customer and the host's opening statement that approves it | One customer makes 41 percent of the writes, so one shard exceeds the 400 inserts per second a primary sustains |

A candidate passes a case when both conditions hold:

- Its findings name the planted problem: one finding cites a location of the planted problem, and its text names the
  problem and its effect, by the case's keyword lists.
- No finding falls outside the case's list of real problems. The lists hold the planted problem only, so any other
  finding fails the case, and a failed case lists those findings in `outside` for the coordinator to read.

A reviewer answer or a debate statement ends with one fenced `json` block of findings, each with `location`
(`path:line` or `path:first-last`), `problem`, and `effect`. The grader reads the last block. A missing or malformed block
fails the case with its `error`. The reviewer prompt carries the review checks of the independent model validation
rules, and the debate prompt carries the fixed contract of the tiki-taka skill, each cut to a single exchange.

## Steps

Run every command from the repository root, with `WORK` as an empty folder outside it. Name each run folder by case and
candidate, such as `T89-opus-high`. Every candidate runs every case once: 20 runs.

Reviewer cases T89 to T91, for each of the four candidates, run from the seeded repository folder:

```text
python3 evals/model-roles/mr_cli.py seed T89 --out $WORK/T89-opus-high
# in $WORK/T89-opus-high/repo:
python3 <repository root>/scripts/role_runner.py reviewer --model claude-opus-5-5 --effort high \
  --assignment $WORK/T89-opus-high/prompt.md --result $WORK/T89-opus-high/answer.md > $WORK/T89-opus-high/status.json
python3 evals/model-roles/mr_cli.py result T89 --candidate claude-opus-5-5/high \
  --answer $WORK/T89-opus-high/answer.md --status-line $WORK/T89-opus-high/status.json \
  --out $WORK/T89-opus-high.json
```

Opponent cases T92 and T93. The runner reads the opponent model from `config/model-registry.json` at its plugin root, so
each Claude model runs from a copy of the runner with that model, and `--fast` selects `high`:

```text
python3 evals/model-roles/mr_cli.py opponent-plugin --model claude-opus-5-5 --out $WORK/plugin-opus
python3 evals/model-roles/mr_cli.py opponent-plugin --model claude-fable-5-2 --out $WORK/plugin-fable
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --show-config --fast
python3 evals/model-roles/mr_cli.py seed T92 --out $WORK/T92-opus-high
STATE=$(mktemp -d /tmp/tiki-taka-state.XXXXXX)
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --state-dir $STATE \
  --repo $WORK/T92-opus-high/repo --max-exchanges 1 --fast \
  < $WORK/T92-opus-high/prompt.md > $WORK/T92-opus-high/answer.md
python3 evals/model-roles/mr_cli.py result T92 --candidate claude-opus-5-5/high \
  --answer $WORK/T92-opus-high/answer.md --state-dir $STATE --out $WORK/T92-opus-high.json
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --state-dir $STATE --finish
```

Run `result` before `--finish`, because `--finish` removes the state the command reads. Omit `--fast` for an `xhigh`
candidate, and use `$WORK/plugin-fable` for a Fable candidate. `--show-config` must print the candidate's model and effort
before the first paid call.

`result` fails with exit 2 and writes no file when the run record shows another model or effort than the candidate, when
the role runner status line is not a verified Claude run with exit 0, or when the transcript is missing. Fix the cause and
run that candidate and case again. A run that failed before an answer counts as an attempt: pass `--attempts <n>`,
`--earlier-cost <usd>`, and `--earlier-wall <seconds>` from `mr_cli.py evidence --status-line <file>` or `--state-dir
<folder>` of each earlier attempt, so that the record counts every attempt's cost and time. `grade <case> --answer <file>`
prints the grading of an answer and exits 1 when the case fails.

`mr_cli.py build --results <the 20 result files>` writes `record.json` only when every candidate has one result per case.

## Record

`record.json` holds `status` (`pending` until built, then `recorded`), the four candidates, the case-to-role map, and
one result per candidate and case:

| Field | Meaning |
|---|---|
| `passed` | The grading of the final attempt |
| `host_model`, `host_effort` | The model and effort of every answer in the run's own Claude transcript, which must equal the candidate's |
| `cost_usd` | List-price cost of every attempt, from the transcript tokens and `evals/e2e/harness/pricing.py` |
| `wall_seconds` | First to last record of the transcript, plus earlier attempts |
| `attempts` | Runs made for the case |

`roles` holds, for `reviewer` (T89 to T91) and `opponent` (T92 and T93), each candidate's passes, total cost, and total wall time
over its own cases, and the role's decision. Validation recomputes `roles` from the results and rejects any other value, a missing
or doubled result, a host model or effort that differs from the candidate, and a negative cost.

## Decision

The owner's efficiency rule in `AGENTS.md` decides each role, over that role's cases only (reviewer: T89 to T91, opponent:
T92 and T93):

1. Eligible candidates passed every case of the role. When none did, the role has no winner (`none`) and keeps its
   baseline pin.
2. On any case, a candidate that is slower than the fastest eligible candidate on that case by more than 1.5 times and by
   more than 60 seconds is dropped. A 1.5-times gap under 60 seconds, a gap of exactly 60 seconds, and a gap of exactly 1.5
   times do not drop it. When this drops every eligible candidate, the role has no winner.
3. Of the rest, the lowest list-price cost per passing case wins. Costs within 10 percent or within $0.05 of the lowest
   tie, and the candidate with the lowest summed wall time over the role's cases wins the tie. Candidates tied on wall time
   too leave the role `tie`.

`none` and `tie` keep the baseline pin until the owner decides. When Opus wins a role, the role names Opus, and Fable stays
available only when the user asks for it.

`python3 evals/model-roles/mr_cli.py check` validates the record and compares the repository with it, through
`tests/test_model_roles_record.py`:

- While the record is pending, or a role is `tie` or `none`, every pin site holds the baseline: the Claude opponent is
  `claude-fable-5-2` at `xhigh` in `config/model-registry.json` and the tiki-taka skill, and the Claude reviewer row names
  `claude-opus-5-5` and `claude-fable-5-2` in the independent model validation rules, the delegation document, the
  final review table of `AGENTS.md`, and their Korean mirrors. No pin changes before a record exists.
- When a role has a winner, each of its sites names the winner's model and no other Claude model of the comparison, the
  registry holds the winner's model and effort, and the reviewer table rows name the winner's effort alone. The test
  fails until every site agrees, and an anchor that no longer finds its line names the file to fix.

Applying a decision also updates the tests that assert the replaced pin text, and, when the opponent winner's effort is
`high`, gives the opponent registry entry its own effort so that the Codex opponent keeps `xhigh`.

## Checks without model calls

```text
python3 -m pytest -q tests/test_model_roles_cases.py tests/test_model_roles_record.py
python3 evals/model-roles/mr_cli.py check
```
