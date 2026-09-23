# Apply the ten strategies within this repository's quality contract

The ten proposals are useful review dimensions. Adopt their applicable mechanisms, preserve existing safeguards,
and treat the supplied ranking as a hypothesis rather than measured repository performance.
The decisions below extend [the implementation plan](README.md) and its [findings](findings.md).

## Scores and decision rule

All ten supplied totals are arithmetically correct for a 1–5 scale:

`100 × (0.40Q + 0.35V + 0.15S + 0.10A) / 5 = 8Q + 7V + 3S + 2A`.

The resulting totals are `88, 79, 78, 75, 73, 72, 70, 65, 63, 62` in the user's order.
Q measures proposed quality preservation, V evidence strength, S saving potential, and A applicability.
Their values are judgments supplied by the user, not live measurements or calibrated probabilities.
Official documentation proves a mechanism's conditions; it does not assign this repository a V score of 4.

Apply hard quality, authorization, and performance gates first.
Only compare priorities among candidates that can meet those gates.
A higher saving score cannot compensate for a missing requirement, and overlapping strategies must not have their
savings added together. F11 prompt deduplication and F25 prefix ordering therefore receive separate comparisons.

“Strategies 1–5 almost never affect quality” is too broad to use as an acceptance rule.
Caching with identical model input differs from rewriting that input for caching.
Removing instructions, replacing judgments with scripts, delaying tool discovery, and narrowing reads can all
lose required information.
Every changed execution path still needs the Sonnet/Luna criteria in [Validation](validation.md).

## Decision for every proposal

| User rank and total | Disposition | Repository application | Boundary or correction |
|---|---|---|---|
| 1. Prompt cache reuse — 88 | Add F25; high-priority candidate after quality baselines. | Put stable optimizer instructions and unchanged skill context before changing evaluation data; preserve stable session rendering. | Cache reuse reduces recomputation and may lower charges/latency. It does not remove logical input or enlarge context. No artificial padding, stale rules, or unrelated preloads. |
| 2. Minimal persistent instructions — 79 | Preserve existing architecture and protect it from growth. | `CLAUDE.md` is already one `@AGENTS.md` line; repository rules are separate from shipped `instructions/session/`. Existing references load conditionally. | Do not remove required common rules as “generic.” Do not count development-only root files as payload shipped to every plugin user. F04 addresses routing metadata separately. |
| 3. Deterministic mechanics — 78 | Strengthen F11–F14, F19, and F21. | Reuse parsers, aggregators, validators, `rg`, and existing batch image/render tools. Preserve full logs as artifacts while surfacing structured evidence. | A script handles exact predicates, not semantic acceptance. Keep exit status, full failure evidence, unsupported-input handling, and schema scope. No new script unless an existing tool cannot meet the contract. |
| 4. Lazy tool/skill loading — 75 | Keep F04–F10/F20/F22–F23; add F26 for tool discovery. | Use native skill selection and host tool discovery; keep substantial mode-specific references conditional. | Full bodies are already selected on demand. Metadata still costs context. API `defer_loading` is an application setting, not portable SKILL.md frontmatter. No custom loader or MCP replacement. |
| 5. Precise exploration — 73 | Strengthen F14/F19 and shared verification cases. | Search the known path/symbol directly; read the defining contract and relevant callers, configuration, and tests. Use existing code intelligence only when available and useful. | Search hits are an entry point, not proof of complete impact coverage. Expand on evidence; keep full-body/transcript reads when the task requires them. No mandatory new LSP/AST service. |
| 6. Proportionate planning/interview — 72 | Preserve the small-edit route and explicit invocation boundary. | F09 keeps a direct route for clear small corrections. Ordinary ambiguities get only necessary clarification under AGENTS.md. | A vague or risky task does not authorize Deep Interview. Once explicitly invoked, its scoring, milestones, threshold, and closure gates remain intact. Explicitly requested plans still follow the full planning contract. |
| 7. Independent subagent work — 70 | Preserve existing delegation rules; strengthen input and cost accounting. | F07/F22 use bounded evidence packets and required independent perspectives. Disjoint searches can run concurrently when authorized. | Keep high-level decisions in the main session. Count parent, workers, reconciliation, re-reads, and retries; smaller parent context is not proof of lower total cost. No overlapping ownership or fewer required reviewers. |
| 8. Minimal changes and reuse — 65 | Retain as a plan-wide constraint. | Reuse existing schemas, reports, helper scripts, and host capabilities. Candidate rejection remains a valid result. | No universal loader, memory database, semantic regex grader, unrequested refactor, or new dependency for hypothetical future savings. |
| 9. Validated model/effort routing — 63 | Preserve the existing evaluated adapters; do not add automatic routing. | Measure complete execution on the exact required Sonnet(high)/Luna(xhigh) lanes; record failed and recovered runs. | Lower effort, automatic escalation, or a stronger final executor would change the current contract and would not prove that the requested model completes the skill. Honor only already-defined fallbacks; otherwise report unverified. |
| 10. Boundary summaries/new context — 62 | Add conditional F27 within existing state/recovery workflows. | Retain a checked checkpoint with decisions, evidence revisions, permissions, open work, and action state; restore required sources before continuation. | No routine `/clear`, history deletion, active-transaction reset, or replacement of Tiki-taka's exact-session contract. New contexts need reliable recovery evidence and existing authorization. |

The repository implications in this table are author conclusions from the cited sources and the audited code.
They are not vendor recommendations specifically tested against this plugin.

## Distinguish four effects

| Effect | Evidence | What does not prove it |
|---|---|---|
| Fewer logical tokens | Complete comparable input/output/reasoning usage. | A larger cached-input count. |
| Smaller active context | Actual loaded material and, when exposed, peak retained context. | A smaller bill or parent-only context. |
| Lower monetary cost | Reported applicable charges or a labeled estimate from verified rates and disjoint usage categories. | Raw token totals, an API list-price estimate presented as subscription spend, or a vendor's maximum discount. |
| Faster completion | Complete request-to-usable-artifact time, including discovery, cache creation, repairs, and recovery. | Cache-hit latency for one successful call. |

OpenAI documents prefix reuse and cheaper/faster cached processing; Claude documents that cached input still
counts toward context capacity. These support treating cache economics and context reduction separately.
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching),
[Claude context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows).

Keep stable content stable only while it remains correct.
Mandatory source refreshes, permission changes, and corrected instructions take precedence over cache reuse.
Tool discovery through a supported host can coexist with caching; manually mutating the early tool list is a different
operation and may invalidate a prefix. [OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search),
[Claude Code prompt caching](https://code.claude.com/docs/en/prompt-caching).

## What this repository controls

| Control owner | Available surface | Plan treatment |
|---|---|---|
| This repository | Instruction wording, reference routing, skill metadata, prompt assembly, local output and existing helpers. | Implement measured F01–F27 candidates here. |
| Agent host | System context, skill catalog limits, tool-schema discovery, installed MCP connections, automatic compaction. | Detect and measure the available behavior; use its existing supported path. No installation/settings changes in this task. |
| API application/provider | Cache keys, retention/breakpoints, deferred-tool registration, compaction endpoints, pricing and usage semantics. | Consult only for an application that actually owns those requests. `model_runner.py` currently forwards stdin to an external command; it does not own the provider payload. |

The host already owns substantial lazy loading.
Codex selects full skill bodies after routing, and its catalog can shorten descriptions when space is limited.
Current Claude Code documentation distinguishes initial skill descriptions/tool names from later bodies/schemas.
Preserve a discoverable, precise trigger at the start of descriptions and test loaded versus merely advertised data.
[Build skills](https://learn.chatgpt.com/docs/build-skills),
[Extend Claude Code](https://code.claude.com/docs/en/features-overview).

Tool search adds discovery work and can be inappropriate for a small tool set.
Its lower initial schema load must be assessed together with misses, retries, and total latency.
[Anthropic advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).

Do not copy every generic cost tip into this repository.
For example, preferring CLIs over MCP or filtering test output with `grep`/`head` does not override the repository's
service-access rule or its requirement to retain exact failures and exit status.
[Claude Code cost guidance](https://code.claude.com/docs/en/costs) supplies candidates, not an exception to local contracts.

## Evidence scope and freshness

Sources were searched and opened on **2026-09-23**.
Documentation without a visible revision date has an unknown publication/update date; access date is not a release date.
Engineering reports describe their own systems. Their cost ratios and benchmark maxima are not expected plugin savings.

| Official source | Visible date | Supported use and limitation |
|---|---|---|
| [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Unknown | Exact prefix, cache usage, model-dependent controls; does not guarantee a hit or define Claude Code behavior. |
| [Claude Code prompt caching](https://code.claude.com/docs/en/prompt-caching) | Unknown | Host-specific invalidation and recovery costs; version/provider differences must be recorded. |
| [Claude context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows) | Unknown | Cached input remains within the context count; not a source for OpenAI's detailed accounting. |
| [Build skills](https://learn.chatgpt.com/docs/build-skills) | Unknown | Skill metadata/body loading and catalog limits in ChatGPT/Codex. |
| [Extend Claude Code](https://code.claude.com/docs/en/features-overview) | Unknown | Current host loading behavior; not proof that every installed version behaves identically. |
| [OpenAI tool search](https://developers.openai.com/api/docs/guides/tools-tool-search) | Unknown | API deferred schemas and discovery; not a field supported by this repository's skill schema. |
| [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use) | 2025-11-24 | Deferred tools and search overhead; reported benchmarks remain specific to that setup. |
| [Claude Code costs](https://code.claude.com/docs/en/costs) | Unknown | Candidate cost controls and host observability; examples still need local-contract review. |
| [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 2025-09-29 | Retrieval, context curation, and summaries have task-dependent trade-offs. |
| [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | 2025-06-13 | Isolation can help independent work; shared dependencies and total agent cost limit applicability. |
| [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction) | Unknown | API-managed compact state; not a lossless or cross-host recovery guarantee. |
| [Skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) | 2026-09-11 | Recent advice about lean instructions explicitly has a model context and acknowledges other models' different needs. |

The latest Astra article supports evaluating unnecessary instructions, but it does not justify deleting the concrete
decision steps needed by Sonnet/Luna. Retain selection cues, exceptions, worked contrasts, and completion checks until
the target-model trials establish that a proposed reduction is safe.
[Astra guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).

Summarization and independent agents likewise remain conditional methods.
Recovery must preserve the current task's full obligations, and delegation must justify its total work rather than
only a smaller parent prompt. [Context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents),
[Multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system),
[OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction).

No model benchmark, cache saving, lower-context result, or host installation change is claimed by this source review.
