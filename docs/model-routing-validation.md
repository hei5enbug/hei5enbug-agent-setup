# Model routing validation

Validated on 2026-10-07. [Machine-readable receipts](model-routing-validation.json) preserve source hashes,
actual model settings, outputs, disjoint usage totals, and the unresolved acceptance criteria.

## Development checks

| Check | Result |
|---|---|
| Full Python suite | Exit 0; 21,552 collected test items. Orca CLI was available. |
| Skill validation | All 11 skills passed. |
| Node diagram tests | 10 passed. |
| Claude native Mod tests | 6 passed; the no-request capability smoke test also passed. |
| Lock and Claude manifest | Passed. Existing root-context and Korean frontmatter warnings remain. |

The sibling-reference detector now distinguishes a sibling skill path from a repository instruction link
that traverses two or three parent directories. Existing target-existence and path-escape checks remain.

## Recurring token comparison

The valid pair used Codex CLI `0.160.1`, `gpt-6-luna`, `xhigh`, the existing ChatGPT subscription, and read-only
permissions. Only the instruction-reuse paragraph differed. Each side handled an initial worker-routing
decision and then resumed with changed worker settings. Both returned the same routing decisions and passed
five checks for pins, evidence, fallback, freshness, and read-only execution.

| Method | Total input and output tokens | Execution time |
|---|---:|---:|
| Paragraph absent | 254,431 | 64.339 seconds |
| Paragraph present | 235,420 | 49.145 seconds |

The observed token difference was −19,011 (−7.47%). Both sides already reused unchanged routing instructions
on resume. The result therefore does not establish that the paragraph reduced instruction loading. One pair
also leaves execution variance unresolved. The additional `prior_decisions_valid` field had ambiguous
historical/current scope and is not acceptance evidence. No cost optimization was adopted; A9 remains open.

Totals include all coordinator input, output, tool results, and final routing acceptance in this fixture.
There were no trial workers or helper requests. Worker implementation/integration and native Claude costs
remain unmeasured. Cache is included in input and reasoning in output. Per-response usage is summed once:
resume CLI totals are cumulative and cannot be added to the initial CLI total. Times sum the two process runs;
idle gaps and setup/grading are evaluation overhead.

The first pair was excluded after one side read installed-plugin sources before the frozen fixture.
Absolute fixture paths corrected the input boundary without resetting the budget. The closed batch used
2 cases, 6 model starts, and 514.192 seconds through assessment, including the excluded starts. It made no
GPT connection provider requests, changed no authentication, and enabled no extra billing.

## Native GPT connection

A disposable no-request probe generated declarations from Claude Code `2.1.291`. `ToolInfo` still exposes
only `name`, `description`, and `mcp`; `ToolDescribeInput` also omits input schemas. Access to the previously
frozen system prompt after resume remains unverified. The [official Mods reference](https://code.claude.com/docs/en/plugins/mods/create#get-type-definitions-for-your-version)
explains why installed declarations are the authoritative build evidence.

The GPT route remains disabled before profile, network, or inference access. A10 requires supported native
picker/backend routing and a session-bound profile. A11 requires live backend, history, resume, cancellation,
permission, quota, role, usage, and rollback observations. Restored Claude subscription access does not supply
these missing host inputs. See the [GPT component guide](claude-gpt.md) for the current boundary.
