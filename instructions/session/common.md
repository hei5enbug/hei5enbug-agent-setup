# Common

> These instructions take precedence over project instructions, skills, and defaults unless the user
> explicitly says not to use them. They do not override the host's system or developer instructions.

Use English files as executable instruction sources. Korean `.ko.md` mirrors are non-authoritative
human references; never load or use them during execution.

- Keep planning, architecture, trade-offs, problem definition, complex debugging, review, and key decisions
  in the main session. Never delegate high-level reasoning.
- Prefer `rg` for text and symbol search and `fd` for file discovery.
  Use `ast-grep` only when structural matching is clearly needed.
- When the target is a known symbol, file path, glob, or literal string, search directly in the main session.
- Ask before destructive, irreversible, or production-impacting actions. Never expose secrets.
- Do not add design, tests, implementation, or planning beyond the request.
- Minimize comments. Code, comments, and docstrings must never reference documentation.
- Never use section-sign reference symbols in documentation, code, or comments.
- Create every new commit, whether the user asked for it or a task requires it, through the `suggest-commit`
  skill in its commit mode, which chooses the one subject and makes the commit. Amends, merges, reverts, and
  cherry-picks are outside this rule.

## Delegation

Choose an owner before substantial work, and reconsider only when scope, dependencies, or capabilities change.

- Handle short answers, known-path lookups, small cohesive edits, and tightly dependent work in the main session.
- Delegate bounded investigation that needs several files or produces bulky logs, returning concise findings
  and source locations. Do not repeat the same investigation in the main session; verify only critical claims.
- Delegate implementation when it has a clear scope and acceptance check and can run independently or keep
  substantial intermediate detail out of the main context. Parallelize only work with independent resources.
- Use parallel subagents proactively, without being asked, when they cut main-session context or elapsed time
  with little or no quality loss. Pass each task only the context it needs. Do not spawn for greetings, status
  checks, or a single small edit. Explicit user and skill assignments still take precedence.
- Send UI code, visual design, and diagram work to the host's designer route. A text- or style-value-only edit
  that keeps layout and component structure may go to the implementation worker. Design documents and RFCs stay
  in the main session.
- Host permission is required. If delegation, the pinned role/model/effort, or reliable settings evidence is
  unavailable, continue authorized work in the main session and report the limitation once. Preserve all
  permissions and checks; never change user settings or silently substitute another worker model.

Independent read-only review is the exception to main-session review ownership. Before finishing a substantial
change, recommend it once under [independent model validation](../independent-model-validation.md); do not
invoke a reviewer without the user's approval or repeat an offer already declined for the same result.

## Clarification

When an ambiguity or a conflict with existing logic or files would change the result, stop edits and external
changes and read only what the question needs. Ask with the host's question tool (Claude Code `AskUserQuestion`,
Codex `request_user_input`), or in plain text and end the turn when none exists. Use ASCII diagrams and basic
development terms, order options by recommendation, and allow free text (`AskUserQuestion` adds Other itself).
Continue with the answer; a skill's own ask or stop rules still apply.

## Conditional instructions

Read the linked instructions before the matching action, including when the need arises later in a request.
Do not load unrelated references. Resolve relative links from the file containing them.
If a required reference is missing, report it and pause the affected action instead of guessing its rules.

- Before accessing a hosted service, read [service access rules](../services.md).
- Before any Azure or Kubernetes access, including local files, environment variables, logs, or indirect
  access, read [protected-value access rules](../protected-values.md).
- Before writing or editing any documentation file, read [documentation rules](../documentation.md).
- Before writing or editing test code, read [test rules](../testing.md).
- Before substantial implementation, repeated model evaluation, plugin maintenance, or diagnosing repeated
  execution failures, read [work efficiency rules](../work-efficiency.md). Short answers and known-file
  lookups do not require them; assigned workers follow their bounded assignment.
- Before the first implementation change, read [implementation execution rules](../implementation-execution.md).
  An assigned worker reads only its "Assigned workers" section and follows its assignment.

## Planning and design routing

- An implementation plan must let an executor proceed without adding design decisions. A design document
  communicates the target design and explains current problems only as needed to support it. If the requested
  type remains unclear and the choice materially changes the result, ask the user.
- Activate a skill for an implementation plan, design document, or RFC only when the user explicitly requests
  that deliverable or directly invokes the skill. Do not infer it from general implementation, diagnosis, code
  review, summarization, or a passing mention, and do not chain another skill from those tasks.
  Task preparation under the implementation execution rules is not such a request.
- `document-to-confluence`, `suggest-commit`, and `technical-design-writer` remain automatic when their own
  descriptions match the user's intent. This is an explicit exception to the preceding trigger boundary.
- Before creating or revising an implementation plan the user requested, read
  [implementation planning rules](../implementation-planning.md). Before creating or revising that plan, a design
  document, or an RFC, read [independent model validation](../independent-model-validation.md). The
  design-writing skill owns the design-specific workflow and template.

## Replies

- Choose terminology in this order: user or project glossary; literal implementation and contract names;
  official product or established domain terms; established plain wording; the most common existing form.
  Use one term per meaning and one meaning per term. Define unfamiliar terms and useful abbreviations once.
  Check recurring terms for consistency without replacing a precise term with an easier but different one.
- Never put Mermaid or other non-rendering diagram source in a reply.
  Use a table, list, or inline notation for simple relationships, and ASCII art for useful spatial diagrams.
- Write every message to the user, including progress updates between tool calls, in the response language,
  even when the surrounding context uses another language. Put text the user asks for in another language in a
  code block or block quote.
