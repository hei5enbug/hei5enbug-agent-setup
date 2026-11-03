# Asking the user

Read this before asking the user anything or proposing to wait. The clarification rule in the common session
instructions decides when to ask.

- Before proposing to wait for a schedule, a later run, or new data, look for a way to check now within the current
  permissions and approvals, such as a manual trigger, a dry run, a replay of recorded input, or a comparison with a
  past window. Propose waiting only when none exists, and give the reason and the earliest time to check. A write
  that the approval rules gate still asks first.
- Use a tool only if host rules permit required, blocking questions; otherwise ask in the final response and end
  the turn. Never use async questions for required decisions.
- List options in recommended order, allow a free-form answer, and add an ASCII diagram only when it clarifies the
  choice.
- Word the question, its header, and each option's label and description by the reply rules in the common session
  instructions, for a reader who sees only that dialog. When a term, abbreviation, internal component name, or code
  identifier that the user has not used in the conversation would appear there, replace it with plain words or define
  it in the same text, such as "the scheduler's own run-history tables" for a meta database.
- Follow host formatting and a skill's own ask or stop rules.
- Offer temporary and root-cause fixes, when both exist, with cost and impact; the user chooses.
- Report a pending user action, such as a login, once.
