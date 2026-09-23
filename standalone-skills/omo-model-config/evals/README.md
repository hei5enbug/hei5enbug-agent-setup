# OmO source fixture and V22 cases

[`source-fixture.json`](source-fixture.json) records the exact upstream paths and SHA-256 hashes used by V22.
Every entry belongs to
`c18ab758961b88bc07f7578ddcbcb286810a524f`. The manifest names all 20 mandatory files plus 13 conditional tests
for the GPT-5.6/GPT-6 candidates and legacy reasoning migration in the current evaluation inputs.

The upstream schema and implementation are not stored in this repository. Use a local checkout at the recorded
revision and materialize only the listed files into a temporary workspace:

```bash
OMO_UPSTREAM_CHECKOUT=/path/to/verified/oh-my-openagent
OMO_EVAL_TEMP="$(mktemp -d)"
python3 standalone-skills/omo-model-config/evals/prepare_fixture.py \
  --source-checkout "$OMO_UPSTREAM_CHECKOUT" \
  --output "$OMO_EVAL_TEMP/source"
```

The setup reads the checkout, verifies its revision and every file hash, then copies the selected subset to the output
path. It does not fetch, modify, or write to the upstream checkout. Keep the temporary output outside the repository.
If the checkout is not at the recorded revision or a hash differs, stop and resolve the fixture source before running a
case. Run V22 with the materialized source directory available as read-only evaluation input.

The evaluation prompts cover full and targeted updates, legacy-field migration, a missing required source, a SHA
mismatch followed by a complete re-fetch, no viable allowlisted model, and declined external sync. The local JSON
cases are synthetic decision inputs; they do not replace the pinned source files.

## Route accounting

The baseline [`SKILL.md`](../SKILL.md) reads all 20 mandatory files for both full and targeted updates.
Targeted scope narrows writes,
not source reads. Relevant conditional tests, `available-models.json`, and the target config are also read. The baseline
does not require batching or same-run reuse, so actual fetch-call counts depend on the host.

The proposed batching/reuse instruction adds 622 bytes to `SKILL.md` (13,595 to 14,217 bytes) while keeping the same
20 mandatory reads. Batching and reuse may reduce tool calls, but no matched full/targeted run measured that reduction
or complete execution time. The runtime skill stays at B0 until native trials show preserved outcomes, fewer total
tool calls, and no slower completion.

No native target-model trial has been run. A live pinned-source behavior trial is unavailable offline, so this fixture
and its cases are prepared for evaluation but do not count as a V22 pass.
