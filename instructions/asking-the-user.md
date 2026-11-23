# Asking the user

Read this before asking the user anything or proposing to wait. The clarification rule in the common session
instructions decides when to ask.

- Before proposing to wait for a schedule, a later run, or new data, look for a way to check now within the current
  permissions and approvals, such as a manual trigger, a dry run, a replay of recorded input, or a comparison with a
  past window. Propose waiting only when none exists, and give the reason and the earliest time to check. A write
  that the approval rules gate still asks first.
- Use a tool only if host rules permit required, blocking questions; otherwise ask in the final response and end
  the turn. Never use async questions for required decisions.
- List options in recommended order. Under the condition that the host's question tool adds its own free-form row,
  as Claude Code `AskUserQuestion` and Codex `request_user_input` do, rely on that row and never add an option whose
  label asks the user to type, such as "Other", "Custom", or "직접 입력", because it shows no text box. Under the
  condition that the host's tool cannot take a free-form answer, ask in the reply that ends the turn instead.
- Add an ASCII diagram only when it clarifies the choice. Under the condition that a diagram helps and the host's
  question tool has a preview field, such as Claude Code `preview`, put it there; under the condition that the tool
  has none, as on Codex, put it in the question text below the question sentence.
- Word the question, its header, and each option's label and description by the reply rules in the common session
  instructions, for a reader who sees only that dialog. That reader must be able to tell what the decision is about,
  from one line that names the thing it changes; each item the choice affects, quoted or described in plain words,
  never only by its number or position in a text the dialog does not show; and what happens to each item under each
  option. Keep the question to one sentence and put details in the option descriptions or the diagram. Leave out how
  you reached the question, such as a reviewer's findings or earlier attempts, unless it changes which option is
  right. Example: "Delete two unused columns from the demo orders table? A: legacy_code, empty since 2025; B:
  old_status, copied into status", with each option saying which columns remain.
- When a term, abbreviation, internal component name, or code identifier that the user has not used in the
  conversation would appear there, use a plain phrase with the same meaning when one exists, such as "the scheduler's
  own run-history tables" for a meta database, and define the term in the same text only when no such phrase exists.
- When a host question tool takes structured input, such as Claude Code `AskUserQuestion`, write the question, its
  header, and each option's label and description as raw characters, never as JSON unicode escapes such as `\uXXXX`,
  even when the text comes from escaped JSON. For text with multi-byte characters, such as Korean, Japanese, or
  Chinese, reread it once before sending and fix any character that differs from the word you meant.
- When the user reports a wrong or garbled character in a question dialog, read your own tool input as stored in the
  session transcript file first, because the conversation, such as a resumed one, can show an earlier tool input with
  unicode escapes it did not contain. Say whether the reported character is in that stored input before naming any
  other cause, and name the host or a plugin only when that input is correct and the shown text differs.
- Follow host formatting and a skill's own ask or stop rules.
- Offer temporary and root-cause fixes, when both exist, with cost and impact; the user chooses.
- Report a pending user action, such as a login, once.
