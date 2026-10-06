# Remaining required work

Updated: 2026-10-07. This document retains only unresolved requirements.
Completed implementation was committed in `a833d1a` and pushed to `origin/main`.
Earlier plans, raw validation archives, and the original evidence record are preserved in an external backup.
The [backup manifest](model-routing-backup.json) records its location, files, and verified SHA-256 values.
Use the [latest validation record](model-routing-validation.md) and its [usage receipts](model-routing-validation.json).

## Open acceptance criteria

| Criterion | Current status | Evidence needed |
|---|---|---|
| A9: output quality and total recurring token cost | Inconclusive; no cost optimization adopted. | A discriminating matched workload preserving quality, reducing total recurring tokens, and satisfying elapsed-time limits. |
| A10: actual GPT connection in Claude Code | Still blocked on `2.1.291`: offered input schemas are absent. | Native picker/backend, complete request inputs, explicit authentication, and a session-bound profile. |
| A11: live GPT compatibility | Offline checks pass; required live observations are unavailable. | Backend, history, resume, cancellation, permissions, quota, effective role pins, usage, and rollback evidence. |

Keep the [GPT connection contract](claude-gpt-remaining.md). Claude quota recovery does not resolve missing
host inputs. Do not replace the native route with a Codex loop, gateway, daemon, inferred schemas, or incomplete
system context. Keep refusal before profile/network/inference access until the prerequisite is verified.

## A9: next comparison

The 2026-10-07 valid pair measured 254,431 versus 235,420 tokens (−7.47%) and 64.339 versus 49.145 seconds.
Both outputs passed five routing checks. Both methods already reused unchanged routing instructions on resume,
so the difference cannot establish a loading reduction caused by the candidate paragraph. Actual worker
implementation/integration and native Claude costs remain outside coverage. The ambiguous
`prior_decisions_valid` field is not acceptance evidence. Reuse the receipts; do not promote an optimization.

Before a new comparison, freeze one workload that actually distinguishes the proposed methods, its expected
outputs and unambiguous quality rubric, source versions, permissions, model/effort, and complete cost scope.
Use Skill Builder's [existing adapters](../skills/skill-builder/references/execution-methods.md) and formats.
Keep production pins and unqualified candidates unchanged. No evaluator framework or E1 effort trial is required.
Measure core/catalog/body/read results, briefs, workers, retries, and acceptance/integration without double
counting. Resume CLI usage is cumulative. Missing coverage or mixed results keeps A9 open.

Startup baseline at the same checkout root remains Codex 7,668 bytes and Claude 7,747 bytes, below 9,000 bytes.
Source-byte changes alone cannot prove runtime token savings.

## Closed budgets and resume

Both batches are closed. The 2026-10-06 batch used 1 case, 3 model starts, and 436.890 seconds. The user authorized
an additional batch on 2026-10-07; it used 2 cases, all 6 model starts, and 514.192 seconds through assessment.
Its first pair was excluded for mixed source context but still counts. Both made 0 GPT connection provider requests.
Neither authentication nor extra billing changed. Additional real-model work requires new specific approval;
these closed allowances cannot be reused. A new allowance remains capped at 3 cases, 6 model starts, 15 minutes,
and 6 GPT connection provider requests unless the user explicitly changes it.

Main owns decisions, integration, and final checks. Reuse unchanged completed worker implementation and valid
check evidence. Preserve user settings, installed caches, credentials, permission guards, default hooks, and
main/role pins. Do not install or run OpenCode. Release baseline is `v1.3.0`; planned version is `2.0.0`.
The user authorized commit and push on 2026-10-07. Neither action closes unresolved acceptance criteria.

The local `.plan` folder was removed after moving its detailed contracts here and verifying the external backup.
This migration leaves A9, A10, and A11 open. Keep these requirements until accepted evidence completes them or the
user explicitly cancels or reduces their scope.
