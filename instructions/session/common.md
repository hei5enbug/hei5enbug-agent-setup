# Common

- Keep problem definition, planning decisions, trade-offs, complex debugging, and acceptance in the main session.
  A skill may delegate drafting, including a design document, to the capability worker it names; the main session
  approves the decisions and accepts the result.
- When the target is a known symbol, file path, glob, or literal string, search directly in the main session.
- Create every new commit, whether the user asked for it or a task requires it, through the `suggest-commit`
  skill in its commit mode. Only the commands its Modes section names run outside it.
- A skill's workflow is a default the user can narrow: run only the steps asked for, and name skipped ones at the end.
- After a rename, a changed decision, or a rollback, update or report every earlier output of the work that still
  shows the old value, such as code, documents, descriptions, tickets, or comments, and list each in the report.

## Delegation

Choose an owner before substantial work.

- Handle short answers, known-path lookups, tightly dependent work, implementation that changes at most two files,
  and integration fixes in the main session.
- Delegate investigation of more than three files or a long log as independent questions run together; do not
  repeat it yourself.
- Delegate implementation that changes more than two files to the implementation worker when it has a clear scope
  and acceptance check.
- Use parallel subagents unasked when they cut main-session context or elapsed time with little or no
  quality loss, but not for greetings, status checks, or a single small edit. Parallelize only work with independent
  resources. Explicit user and skill assignments take precedence.
- Send UI code, visual design, and diagram work to the host's designer route, except the kinds the host session
  file assigns to the main session.
- If delegation is unavailable, use the fallback route the host rules name; without one, continue authorized work
  in the main session. Report the limitation once.

Independent review is the exception to main-session review. Before finishing a substantial change, read
[independent model validation](../independent-model-validation.md).

## Clarification

On a result-changing ambiguity or conflict, stop edits and external changes, read only what is needed, and
ask one concise question. Check what reading, running, or measuring within your permissions can show instead of
asking about it or waiting for a later run. Resume only on an explicit user answer. Silence, elapsed time, empty or
automatic answers, and defaults are not answers. Before asking the user anything or proposing to wait, read
[asking the user](../asking-the-user.md).

## Conditional instructions

- Before substantial implementation, read [work efficiency](../work-efficiency.md).
- Before repeated model evaluation, read [model evaluation rules](../model-evaluation.md).
- Before retrying a failed command, diagnosing repeated execution failures, or plugin maintenance, read
  [failure and maintenance rules](../failure-and-maintenance.md).
- Before the first implementation change, read [implementation execution rules](../implementation-execution.md).
- Before editing another repository or starting or messaging an Orca session, read [cross-repository work](../cross-repository.md).
- Before ending work in which a user correction or a costly investigation is likely to recur, read
  [repository guidance](../repository-guidance.md).

## Planning and design routing

- Activate a skill for an implementation plan, design document, or RFC only when the user explicitly requests
  that deliverable or directly invokes the skill. Do not infer it from general implementation, diagnosis, code
  review, summarization, or a passing mention, and do not chain another skill from those tasks.
  Task preparation under the implementation execution rules is not such a request.
- `document-to-confluence`, `suggest-commit`, and `technical-design-writer` remain automatic when their own
  descriptions match the user's intent. This is an explicit exception to the preceding trigger boundary.
- Before creating or revising an implementation plan the user requested, read
  [implementation planning](../implementation-planning.md).

## Replies

- Lead with what the reader must act on; for a decision, one recommendation and its reason, then the alternatives.
  Keep only what the reader needs, give each sentence one reading, and define terms a first-time reader would not
  know. In an existing thread, read it first and add only what is new.
- Choose terminology in this order: user or project glossary; literal implementation and contract names;
  official product or established domain terms; established plain wording; the most common existing form.
  Use one term per meaning and one meaning per term, never swapping a precise term for an easier but different one.
- Never put Mermaid or other non-rendering diagram source in a reply. Where it is shorter than prose, use a table,
  list, or inline notation for simple relationships and ASCII art for spatial ones.
- Write every message to the user, including progress updates between tool calls, in the response language,
  even when the surrounding context uses another language. Put text the user asks for in another language in a
  code block or block quote.
