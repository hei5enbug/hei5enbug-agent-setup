# Writing test cases for a skill

## Test cases

Create 2–3 realistic prompts for the first iteration.
Vary the input types the skill will actually meet rather than testing one shape repeatedly.
When output behavior is inferred from examples, history, documentation, or other context, include a contrastive pair:
hold the task and primary input constant, change one decisive context signal, and assert that the intended output
dimension changes while unrelated dimensions remain stable. Trace every critical inferred dimension from "Capture
intent" to at least one case or assertion.
When the user reports an intermittent or model-specific defect, use the reported configuration when it matches the
required evaluation model adapter and repeat the affected old/new pair 2–3 times within a frozen trial budget. One
passing baseline run does not disprove the report. If the exact configuration is unavailable or conflicts with the
required adapter, mark that validation unverified instead of substituting settings. Do not repeat unrelated cases.
As the set grows, include at least one case where the correct behavior is minimal or no change at
all. An overaggressive skill rewrites acceptable input and fails this case.
Share them for confirmation when user judgment is needed; if the user has already authorized execution and the expected behavior is clear, proceed and report the chosen cases.

Save cases to `evals/evals.json` when filesystem access is available:

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "A realistic user task",
      "expected_output": "A concise description of success",
      "files": []
    }
  ]
}
```

Read `references/schemas.md` when assertions or benchmark artifacts are needed.
