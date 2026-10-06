# Remaining GPT connection work in Claude Code

This is the A10–A11 contract linked from [remaining work](model-routing-remaining.md).
Existing components and scoped offline checks are reusable; no working native picker/backend or session-bound profile
has been established.
For helper setup/security details, use the existing [GPT component guide](claude-gpt.md).
Apply the existing [shared routing contract](../instructions/model-routing.md) after model/profile switches
and session resume.

The 2026-10-07 no-request recheck confirmed that the blocker remains on `2.1.291`. The
[validation record](model-routing-validation.md) preserves exact declarations and check results.

## Blocking host prerequisite

The observed Claude Code build `2.1.291` exposes `turn.step` text/tool/input/stop chunks and normalized visible
history through `$.session.messages({ as: "api" })`. Its `ToolInfo` and `ToolDescribeInput` omit input schemas.
`$.prompt.compose()` is not evidence of access to the previously frozen system snapshot after resume.
Actual tool-permission ordering, background requests, and quota independence remain unverified.

The adapter and `launch` refuse before profile/network/inference access. Keep that refusal until complete
required inputs are supported and verified. Do not repeat the same capability probe without changed host or
interface evidence. With changed evidence, main may make one bounded, read-only pass of at most five minutes
using installed declarations and a disposable no-request fixture; no login, install, or model probe.

Record the exact prompt/history/tool-schema access, native stream/result types, cancellation through
`next.signal` and scoped `$.process.spawn`, hook ordering, and managed settings restrictions. Missing access
blocks the affected route. Do not infer schemas from names or TypeScript input declarations, approximate
required system content, substitute a Codex loop, or add a provider daemon, orchestrator, or general gateway.

## Finish the native connection

Only after the host prerequisite is accepted, main freezes the adapter contract and integrates this slice.
Affected paths: `hooks/claude-gpt/register.js`, `protocol.js`, their native tests, `scripts/claude_gpt.py`,
`tests/test_claude_gpt.py`, and GPT/root documentation with Korean mirrors. Change Claude module registration
only if required by verified host types. Preserve default hooks, security guards, and Codex isolation.

| Remaining behavior | Required contract |
|---|---|
| Picker/launcher | Implement `launch` with disposable merged `--settings`, preserving existing Claude rows, permission flags, and managed restrictions. Existing `/model` must route pinned `gpt-6.1-sol` and `gpt-6-luna` to the actual backend. No default or user/project settings write. Unsupported IDs, effort, or managed restrictions fail explicitly. |
| Session/profile | Bind an explicitly selected opaque profile ID to the Claude session, preserve it on resume, and switch only explicitly. Global helper selection must not change an existing session's billing. Authentication offers subscription or API-key usage billing; no active credential is inferred. |
| Native bridge | Pass the version-1 request through helper stdin with session/turn/step IDs, pinned model, supported effort, profile reference, complete system/developer content, visible history, and actually offered schemas. Adapt and test real schema/history representations without dropping required constraints or inventing context. |
| Streaming/tools | Stream native text chunks; buffer executable tool calls until valid provider completion and successful helper exit. Preserve call/result IDs and required private provider state. Claude Code executes tools through normal approval/deny hooks; Python never executes them. Reject malformed, duplicate, unknown, truncated, or mismatched calls. |
| Resume/cancel/failure | Host history is canonical. No second full transcript, signed Claude thinking, incompatible provider cache state, or server conversation ID substitute. Cancel helper/request through the verified host contract, preserve committed context, report failure once, and never replay historical writes or retry after partial output. |
| Quota/host identity | GPT inference must not need a Claude model request, including startup/background/compaction paths. Claude/subagent requests pass unchanged. Switching the main model preserves host permissions, effective pinned roles, main fallback, and author-family review rules in the shared routing contract. |
| Credentials/dependencies | Reuse the protected helper profiles and optional locked JWT/crypto runtime. Do not read or copy Codex/Claude credentials. No ordinary startup/request login, install, billing/model/auth fallback, secret in model-visible text, or permission-hook bypass. |

Native Mod tests and fake-profile helper tests must cover new mapping, picker merge, explicit session binding,
resume, cancellation, and failure boundaries. Reuse unchanged checks and invalidate only affected evidence.
Offline success remains distinct from observed backend, effort, permissions, and account eligibility.

## Essential live evidence

Both acceptance batches are closed; the additional 2026-10-07 batch consumed all six model starts.
Freeze the exact smallest missing request list and obtain specific new model-test authorization before launching.
Real profile login or authentication changes require explicit approval; do not request an API key merely to fill a
second-mode table. Reuse an observed mode where adequate,
retain offline coverage for both modes, and test another live mode only for an unresolved unique behavior.
The shared limits and stop conditions are in [remaining work](model-routing-remaining.md).

| Check | Required observation |
|---|---|
| Backend/authentication | Actual pinned GPT backend, supported effort evidence, explicit selected mode, and retained Claude picker rows. Record unreported effort/account restrictions as unknown. No automatic usage billing. |
| Conversation/tool history | Retain a synthetic fact and earlier tool result during model switch and resume. One bounded scratch code edit succeeds through ordinary host tools and permissions. Restarts do not replay calls. |
| Permissions/stream | Observe actual deny/approval ordering, cancellation, partial failures, and unknown/malformed/duplicate calls without unintended writes. Destructive cases remain offline. |
| Claude quota | Simulated Claude quota rejection leaves GPT usable without a Claude model request. Use a real exhausted-account observation if available; distinguish quota from expired login or startup failures. Do not wait for quota reset. |
| Isolation/roles/usage | Preserve profile/provider state separation, actual worker model/effort after switch/resume, and public/authorized tool boundaries. Report translated history, cache, reasoning, workers, retries, and helper overhead with exact usage coverage. |
| Rollback | Disabling the extra Claude module/session launcher restores ordinary behavior while preserving default hooks, Codex, user settings, sessions, credentials, and guards. |

Record pass/fail/untested with tested build, source hashes, effective model/effort, authentication mode, request
counters, compact output, and usage receipts. A missing required observation leaves A10/A11 incomplete.
A capped or failed batch authorizes no automatic extension, paid route, or authentication change.
