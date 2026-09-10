# Description Optimization

The frontmatter description is the primary routing signal in most skill hosts.
Optimize it only after the skill behavior is stable.
All resource paths below are relative to the skill root; `<skill-builder-path>` is the directory
containing the loaded `SKILL.md`.
Use the evaluation model policy in [Execution methods](execution-methods.md).

## Build a trigger eval set

Create about 20 realistic queries with a balanced mix of `should_trigger: true` and `false`. Include:

- varied phrasings, lengths, detail levels, and mild typos
- uncommon but valid uses
- close competitors where this skill should win
- difficult near-misses that share vocabulary but need another workflow

Avoid trivial positives and obviously unrelated negatives. Save the array as JSON:

```json
[
  {"query": "a realistic user request", "should_trigger": true},
  {"query": "a difficult near-miss", "should_trigger": false}
]
```

Use `assets/eval_review.html` for user inspection and edits when browser or artifact presentation is available.
Fill its single `__EVAL_REVIEW_DATA__` placeholder with one JSON object holding
`skill_name`, `description`, and `evals`.
Write every `<` in that JSON as `\u003c` so a query can never close the script element.
The header comment in the file shows the exact command.

## Configure a portable model runner

The bundled optimizer does not assume a vendor CLI.
Supply a command that reads the full prompt from standard input and writes only the response to standard output:

```bash
python <skill-builder-path>/scripts/run_loop.py \
  --eval-set <trigger-eval.json> \
  --skill-path <path-to-skill> \
  --runner-command '<your-model-command>' \
  --max-iterations 5 \
  --verbose
```

The command may contain `{model}` in an argument; when it does, also pass `--model <model-id>`.
Instead of repeating `--runner-command`, set `SKILL_BUILDER_RUNNER_COMMAND`.
Use `--no-open` in a headless environment.

The loop checks its inputs before calling any model. The eval set must be a non-empty list of
`query` strings with boolean `should_trigger`, and duplicate queries cannot carry conflicting
expectations. Worker count, timeout, runs per query, and iterations must be positive integers.
The trigger threshold must be finite and between 0 and 1, and the holdout must be finite, at least
0, and below 1. The starting description must be non-empty and no longer than 1,024 characters.

Identical queries always land in the same split. Results are matched by case id rather than query
text. A response containing both a true and a false trigger tag counts as a runner error rather
than a decision. A rewritten description that is empty or over 1,024 characters is retried once
and then rejected.

The runner contract uses stdin/stdout and executes without a shell.
A host-specific wrapper can adapt a CLI, local model server, or API client without changing the optimizer.

Trigger evaluation uses a stable routing simulation based only on the skill name, description, and query.
This makes scores comparable across runners, but it is a proxy for a host's private routing implementation.
When native host trigger tests are available, run them as an additional integration check.
Keep the portable benchmark for cross-host comparisons.

Label every reported description-optimization score as a portable routing simulation.
State that native trigger checks are required before claiming equivalent behavior in a specific host.

The loop uses a stratified train/test split, repeated routing decisions, and held-out score selection
to reduce overfitting.
Apply `best_description` from the output and report before/after scores.

Choose the runner for repeated, isolated trials; direct prompt execution is also allowed for small evaluations.
Keep held-out queries hidden from the improving model in either method.
If the same context has already seen them, disclose contamination and use fresh cases before claiming held-out results.
Label direct execution as an inline evaluation and report unavailable capabilities or metrics.
Do not claim a method is faster or cheaper without the comparison required by Execution methods.
