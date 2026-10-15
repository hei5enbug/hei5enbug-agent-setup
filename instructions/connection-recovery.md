# Codex connection recovery

Use this after an interrupted Codex connection, including `stream disconnected before completion`.
Recover the task's actual state; this instruction cannot prevent a server-side processing failure.

## Before retrying

- An interrupted response does not prove that a tool failed. The backend or command may still be running.
  Check the current thread or terminal status before submitting another turn. Observe active work rather
  than resending its prompt. Stop an owned process only within the user's authorization.
- Read the latest relevant transcript or receipt and inspect the affected state: for local work, the diff,
  files, and owned processes; for an external write, the saved target or transaction receipt. Do not replay
  a write because its response is missing. If the outcome cannot be verified, report the uncertainty and
  hold the dependent action.
- Preserve user changes and the current model, effort, working directory, permissions, and task bounds.
  Apply the [required-question rule](session/common.md#clarification) before continuing a pending decision.

## Safe continuation

Reconnect to the same conversation when supported. Once the runtime is idle, continue from verified
unfinished work. Do not repeat completed edits, commits, pushes, releases, or external writes. Do not
restart the shared daemon, close other sessions, or switch credentials, providers, or network settings as
an unapproved recovery shortcut.

Follow the [retry limits](failure-and-maintenance.md): a transient failure permits at most
one unchanged retry, and only after state inspection establishes that the action is safe. Another failure
requires diagnosis or changed conditions. Record only relevant non-secret diagnostics, such as the CLI
version, time, error category, and privately retained request ID; a request ID is not a local diagnosis.

## Transport limits

The built-in `openai` provider is reserved. Do not assume that a `[model_providers.openai]` override tunes
its retries. Custom-provider retry and idle-timeout controls do not prevent arbitrary server processing
errors, and do not justify changing a user's provider. Verify any proposed setting against the actual CLI
version's schema and feature list; do not add unknown question-timeout or auto-resolution flags, or use
removed transport or compaction switches as fixes.

Local client disconnection, provider stream failure, and server-side request failure are different cases.
Report exactly what a controlled test reproduced. Distinguish instructions being loaded, observed behavior
within a bounded interval, and a runtime guarantee; one successful resume proves no indefinite guarantee.

Sources: [app-server protocol](https://learn.chatgpt.com/docs/app-server),
[configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), and
[configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic).
