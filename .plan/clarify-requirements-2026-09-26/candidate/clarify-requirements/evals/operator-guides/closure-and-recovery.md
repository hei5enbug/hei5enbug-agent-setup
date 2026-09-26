# Operator guide: closure and recovery

Do not attach this file to the agent prompt. Supply the described user action only when the interview reaches it.

- Closure assumption variant: Let one agent-inferred assumption remain unconfirmed while other dimensions reach the
  threshold. Do not confirm it. The workflow must keep the assumption capped and refuse to pass closure on it.
- Early-exit variant: After two unanswered gaps, say “Stop here.” The workflow must preserve gaps and report the
  failed ambiguity gate.
- Round-cap variant: Continue to round 20 with unresolved risks. The workflow must stop questions and produce a
  risk-marked specification.
- Compaction variant: After a question is completed and before the next scoring/UI action, compact or resume the
  session. Check that scoring and UI rules are reloaded when unavailable, the current tool schema is checked, and
  facts/approvals are revalidated.
- No-UI variant: On a non-Codex host with no structured ask tool, check the inline fallback format and that the
  agent stops after one question.
- Native UI variants: Run the Claude Code case with `AskUserQuestion`, the OpenCode case with `question`, and the
  Codex case in Plan mode with `request_user_input`. Check each host's own schema and free-text handling.
- Missing-reference variant: In a disposable skill copy, hide `references/ask-ui.md` and verify that the agent
  reports the missing reference and stops without asking.
- Panel-worker variant: When independent workers are available, verify that the four personas run in isolated
  read-only contexts and only assist the main-session question.
