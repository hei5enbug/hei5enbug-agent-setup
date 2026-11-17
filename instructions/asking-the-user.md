# Asking the user

Read this before asking the user anything or proposing to wait. The clarification rule in the common session
instructions decides when to ask.

- Before proposing to wait for a schedule, a later run, or new data, look for a way to check now within the current
  permissions and approvals, such as a manual trigger, a dry run, a replay of recorded input, or a comparison with a
  past window. Propose waiting only when none exists, and give the reason and the earliest time to check. A write
  that the approval rules gate still asks first.
- Use a tool only if host rules permit required, blocking questions; otherwise ask in the final response and end
  the turn. Never use async questions for required decisions.
- List options in recommended order. When the host's question tool adds its own free-form row, as Claude Code
  `AskUserQuestion` and Codex `request_user_input` do, rely on that row and never add an option whose label asks the
  user to type, such as "Other", "Custom", or "직접 입력". When the host's tool cannot take a free-form answer, ask in
  the reply that ends the turn instead.
- Add an ASCII diagram only when it clarifies the choice. When the question tool has a preview field, such as Claude
  Code `preview`, put the diagram there; when it has none, as on Codex, put it in the question text below the
  question sentence.
- Word the question, its header, and each option's label and description by the reply rules in the common session
  instructions, for a reader who sees only that dialog. When a term, abbreviation, internal component name, or code
  identifier that the user has not used in the conversation would appear there, replace it with plain words or define
  it in the same text, such as "the scheduler's own run-history tables" for a meta database. Use a plain phrase with
  the same meaning instead of the term, and define the term only when no such phrase exists.
- Before showing a question dialog, check that a reader who sees only that dialog can tell what the decision is about,
  from one line that names the thing it changes; each item the choice affects, quoted or described in plain words,
  never only by its number or position in a text the dialog does not show; and what happens to each item under each
  option. Leave out how the agent reached the question, such as a reviewer's findings or earlier attempts, unless it
  changes which option is right. Keep the question to one sentence and put details in the option descriptions or the
  diagram. For example, ask "Delete two unused columns from the demo orders table?" with "A: legacy_code, empty since
  2025; B: old_status, copied into status", and let each option say which columns remain.
- When a host question tool takes structured input, such as Claude Code `AskUserQuestion`, write the question, its
  header, and each option's label and description as raw characters, never as JSON unicode escapes such as `\uXXXX`,
  even when the text comes from escaped JSON. For text with multi-byte characters, such as Korean, Japanese, or
  Chinese, reread it once before sending and fix any character that differs from the word you meant.
- When the user reports a wrong or garbled character in a question dialog, or the conversation shows unicode escapes
  or another form you did not intend in your own earlier question-tool input, read that input as stored in the
  session transcript file before drawing any conclusion, because the conversation, such as a resumed or compacted
  one, can show an earlier tool input with unicode escapes it did not contain; never judge from the display whether
  the raw-character rule was followed. When the stored input holds the intended characters, treat the display as an
  artifact: record no mistake in a summary, memory, or report, promise no correction, and report no defect to the
  user, the host, or a tracker. When it holds escape text or a wrong character, say so and write the next question as
  the raw-character rule says. Say whether the reported character is in that stored input before naming any other
  cause, and name the host or a plugin only when that input is correct and the shown text differs.
- Follow host formatting and a skill's own ask or stop rules.
- Offer temporary and root-cause fixes, when both exist, with cost and impact; the user chooses.
- Report a pending user action, such as a login, once.
