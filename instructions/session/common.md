# Common

- Keep planning, architecture, trade-offs, problem definition, complex debugging, review, and key decisions
  in the main session. Never delegate high-level reasoning.
- When the target is a known symbol, file path, glob, or literal string, search directly in the main session.
- Create every new commit, whether the user asked for it or a task requires it, through the `suggest-commit`
  skill in its commit mode. Amends, merges, reverts, and cherry-picks are outside this rule.

## Delegation

Choose an owner before substantial work, and reconsider only when scope, dependencies, or capabilities change.

- Handle short answers, known-path lookups, tightly dependent work, implementation that changes at most two files,
  and integration fixes in the main session.
- Delegate bounded investigation that needs several files or produces bulky logs, returning concise findings
  and source locations. Do not repeat the same investigation in the main session; verify only critical claims.
- Delegate implementation that changes more than two files to the implementation worker when it has a clear scope
  and acceptance check and can run independently or keep substantial intermediate detail out of the main context.
  Parallelize only work with independent resources.
- Use parallel subagents proactively, unasked, when they cut main-session context or elapsed time with little or no
  quality loss. Pass each task only the context it needs. Do not spawn for greetings, status checks, or a single
  small edit. Explicit user and skill assignments still take precedence.
- Send UI code, visual design, and diagram work to the host's designer route, except the kinds the host session
  file assigns to the main session. A text- or style-value-only edit that keeps layout and component structure may
  go to the implementation worker. Design documents and RFCs stay in the main session.
- Host permission is required. If delegation, the pinned role/model/effort, or reliable settings evidence is
  unavailable, use the fallback route the host rules name; without one, continue authorized work in the main
  session. Report the limitation once. Preserve all permissions and checks; never change user settings or
  silently substitute another worker model.

Independent read-only review is the exception to main-session review ownership. Before finishing a substantial
change, recommend it once; do not invoke a reviewer without the user's approval or repeat a declined offer for the
same result. For a Claude-authored result, name the reviewer in the session line "Review model" and read
the independent model validation rules below after approval; otherwise read them before asking.

## Clarification

On a result-changing ambiguity or conflict, stop edits and external changes, read only what is needed, and
ask one concise question. Use a tool only if host rules permit required, blocking questions; otherwise
ask in the final response and end the turn. Never use async questions for required decisions. Resume only
on an explicit user answer. Silence, elapsed time, empty or automatic answers, and defaults are not answers.
Follow host formatting and a skill's own ask or stop rules. Offer temporary and root-cause fixes, when both
exist, with cost and impact; the user chooses. Report a pending user action, such as a login, once.

## Conditional instructions

- Before substantial implementation, repeated model evaluation, plugin maintenance, or diagnosing repeated
  execution failures, read [work efficiency](../work-efficiency.md).
- Before the first implementation change, read [implementation execution rules](../implementation-execution.md).

## Planning and design routing

- An implementation plan must let an executor proceed without adding design decisions. A design document
  communicates the target design and explains current problems only as needed to support it.
- Activate a skill for an implementation plan, design document, or RFC only when the user explicitly requests
  that deliverable or directly invokes the skill. Do not infer it from general implementation, diagnosis, code
  review, summarization, or a passing mention, and do not chain another skill from those tasks.
  Task preparation under the implementation execution rules is not such a request.
- `document-to-confluence`, `suggest-commit`, and `technical-design-writer` remain automatic when their own
  descriptions match the user's intent. This is an explicit exception to the preceding trigger boundary.
- Before creating or revising an implementation plan the user requested, read
  [implementation planning](../implementation-planning.md). Before creating or revising that plan, a design
  document, or an RFC, read [independent model validation](../independent-model-validation.md). The
  design-writing skill owns the design-specific workflow and template.

## Replies

- Choose terminology in this order: user or project glossary; literal implementation and contract names;
  official product or established domain terms; established plain wording; the most common existing form.
  Use one term per meaning and one meaning per term. Define unfamiliar terms and useful abbreviations once.
  Keep recurring terms consistent without swapping a precise term for an easier but different one.
- Never put Mermaid or other non-rendering diagram source in a reply.
  Use a table, list, or inline notation for simple relationships and ASCII art for spatial ones.
- Write every message to the user, including progress updates between tool calls, in the response language,
  even when the surrounding context uses another language. Put text the user asks for in another language in a
  code block or block quote.
