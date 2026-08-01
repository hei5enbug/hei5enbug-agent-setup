# Deep Interview — Cross-Agent Ask UI Routing

This fragment defines how Deep Interview asks the user **every** interview question.
It is the load-bearing contract of this skill: the interview is conducted **through the
host agent's native ask UI**, never as plain prose pretending to be a multiple-choice
question.

Load this fragment whenever you are about to present a question, a confirmation
(Round 0 topology, Refine gate, Closure/Restate gate), or the Phase 5 execution-bridge
choice.

## Contents

- Core principle
- Unified question model
- Per-host routing
- Unknown-host fallback
- Answer handling
- Selection checklist

## Core principle

- **One question per round.** Never batch multiple questions into a single ask, even
  when the host tool technically allows 2–4 questions per call. Deep Interview scores
  ambiguity after each answer, so questions must arrive one at a time.
- **Always use the host's native structured ask tool when one exists.** A clickable /
  selectable UI produces cleaner answers and lets the user pick a custom/free-text reply.
- **Never fake a multiple-choice prompt as ordinary assistant text** when a native tool
  is available. Only the documented inline fallback (below) may render options as text,
  and only when no native ask tool exists in the current runtime.
- **Preserve the user's language.** Translate the question text, the short header, and
  every option `label`/`description` into the user's conversation language (see
  `language` handling in `SKILL.md`). Keep code identifiers, file paths, commands, and
  fixed status tokens in English.
- **Make questions easy to understand.** Write the question and every option description
  in enough detail that a high-school student can understand the choice, what changes if
  they pick it, and the main tradeoff or risk.
- **Order by recommendation.** Sort options from strongest recommendation to weakest, and
  append the exact suffix ` (추천)` to the single most recommended option label.

## The unified question model

Every Deep Interview question maps to this single logical shape, regardless of host:

| Field | Meaning | Constraint (for cross-host safety) |
|-------|---------|------------------------------------|
| `question` | The full question text the user reads. | Prepend the Round/Component/Targeting/Ambiguity line from `SKILL.md` Step 2b. |
| `header` | A short label for the question. | Keep **≤ 12 characters** so it is valid in Claude Code. |
| `options[]` | 2–4 contextually relevant choices. | Each has a short `label` and a detailed `description` explaining the tradeoff in plain language. Order strongest-recommended first and append ` (추천)` to exactly one best label. |
| custom / free-text | The user can always type their own answer. | Guaranteed by Claude ("Other") and OpenCode; for the inline fallback, add an explicit `Custom` option. |
| multi-select | Usually single-select. | Only set multi when the question genuinely accepts several answers. |

Keep `options` to **2–4** entries: that range is valid in every host (Claude requires 2–4).

## Per-host routing

Detect the runtime by which ask tool is present in your available tools, then use it.
If you cannot tell, attempt the native tool first; if it is not in your toolset, use the
inline fallback.

### Claude Code → `AskUserQuestion`

```json
{
  "questions": [
    {
      "question": "Round 2 | Component: Ingestion | Targeting: Constraints | Why now: ... | Ambiguity: 58%\n\nShould the importer accept gzipped CSVs, or only plain .csv?",
      "header": "CSV input",
      "options": [
        { "label": "Plain .csv only (추천)", "description": "Choose this if the first version should stay simple. Users can upload only normal .csv files, and compressed files are rejected with a clear error." },
        { "label": "Also accept .gz", "description": "Choose this if users often have large compressed files. It adds more implementation work because uploads must be decompressed and failure cases must be handled." }
      ],
      "multiSelect": false
    }
  ]
}
```

- 1–4 questions per call (use exactly **1**), 2–4 `options` per question, `header` ≤ 12 chars.
- The user is **always** offered an "Other" free-text choice automatically — do not add a
  manual "Custom" option.
- **Limitation:** `AskUserQuestion` is **not available inside subagents** spawned via the
  Agent/Task tool. Therefore the interview loop (all asks) must run from the **main
  session**. Read-only panels/auto-mode subagents (Phase 3, Steps 2a′/2b′) may still be
  spawned, but they must **return findings to the main session**, which then performs the
  single user-facing ask.

### OpenCode → `question`

```json
{
  "questions": [
    {
      "question": "Round 2 | Component: Ingestion | Targeting: Constraints | Why now: ... | Ambiguity: 58%\n\nShould the importer accept gzipped CSVs, or only plain .csv?",
      "header": "CSV input",
      "options": [
        { "label": "Plain .csv only (추천)", "description": "Choose this if the first version should stay simple. Users can upload only normal .csv files, and compressed files are rejected with a clear error." },
        { "label": "Also accept .gz", "description": "Choose this if users often have large compressed files. It adds more implementation work because uploads must be decompressed and failure cases must be handled." }
      ],
      "multiple": false
    }
  ]
}
```

- Field for multi-select is `multiple` (not `multiSelect`).
- The call **pauses the task until the user answers**; custom/free-text answers are
  enabled in the UI by default.
- `question` is a first-class permission key — if it is denied, fall back to the inline
  format below.

### Codex → Plan mode + `request_user_input`

- Run the interview in **Plan mode**, where Codex provides the supported structured-question
  workflow. If the current conversation is not in Plan mode, tell the user to switch with
  `/plan` (or the equivalent Plan mode control in their Codex surface), then **end the turn**.
  Resume the interview only after the user returns in Plan mode.
- Do not recommend or enable `features.default_mode_request_user_input`; it is an
  under-development feature and is not required for this skill.
- In Plan mode, prefer the `request_user_input` tool — prompt the user with 1–3 short
  questions (use exactly **1**); options carry `label` + `description`, and each question
  carries `id` / `header` / `question` / `options`.
- If an MCP server exposes structured elicitation (`form` / `openai/form` / `url`), that
  is also an acceptable structured primitive.
- Use the **inline fallback** only when Plan mode is unavailable, the user declines to
  switch modes, or no structured primitive is available after the switch. Do not silently
  fall back merely because the interview started in Codex Default mode.

### Any other / unknown host → inline fallback

When no native structured ask tool is available, render exactly one clearly delimited question
block in this format, then **end the turn** and wait for the user's next message:

```md
## Question {N}: {Topic}        <!-- or localized: ## 질문 {N}: {주제} -->

{3–10 lines of substantive context written plainly enough for a high-school student: why this
decision matters, what changes depending on the answer, the tradeoff between options, the risk of
leaving it ambiguous, and why option A) is the recommended default.}

- A) {strongest recommended option} (추천)
- B) {second option}
- C) {third option}
- D) 직접 입력 / Custom

**답변 / Your answer:**
<!-- Enter your choice (e.g. "A") or type your own answer below this line. -->
```

Rules for the inline fallback:
- Options ordered strongest-recommended first; exactly one ` (추천)` marker, always at the end of
  the `A)` label.
- Option descriptions must be detailed enough for a high-school student to understand what the
  choice means, what changes if they pick it, and the main tradeoff or risk.
- Always include `D) 직접 입력 / Custom`.
- After emitting the block, **stop** — do not score ambiguity or continue until the user
  replies in the next turn.

## Answer handling (all hosts)

- Read the selected option `label` and any free-text. If the user supplied custom text,
  prioritize it over a predefined option.
- A custom/free-text answer that carries reasoning or constraints triggers the **Refine
  gate** (SKILL.md Step 2b″) before scoring.
- If the user opts out / asks you to decide, trigger **auto-answer** (SKILL.md Step 2b′ via
  `auto-answer-uncertain.md`).
- Never infer missing detail from an option label alone — collect the exact text with one
  follow-up ask.

## Quick selection checklist

1. Is this Codex outside Plan mode? Ask the user to switch to Plan mode and end the turn.
   Otherwise, use the native structured ask tool (Claude `AskUserQuestion` / OpenCode
   `question` / Codex `request_user_input` / MCP elicitation).
2. Exactly one question, `header` ≤ 12 chars, 2–4 options each `{label, description}`,
   single-select unless genuinely multi.
3. Translate question/header/options to the user's language.
4. Sort options by recommendation strength and append ` (추천)` to exactly one best option label.
5. Make the question and descriptions detailed enough for a high-school student to understand.
6. No native tool (or `question` permission denied)? Apply the host-specific mode/setup
   gate first. Use the inline fallback only when that gate cannot provide a structured UI.
7. Never run interview asks from a spawned subagent (Claude's `AskUserQuestion` is
   main-session only) — collect subagent findings, then ask from the main session.
