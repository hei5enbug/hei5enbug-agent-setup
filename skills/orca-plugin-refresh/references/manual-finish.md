# Finish a skipped session by hand

Use this only for a session whose result is `skipped` or `failed` because the script judged it wrongly, for example
`not_a_claude_session` on a terminal that plainly runs Claude Code. Do it only with the user's approval for that
session in the current request, and never for a `blocked` or `deferred` session.

## Checks before any command

Run every check that the script runs. If one fails, send nothing and tell the user which check failed.

1. The turn record is idle: the transcript named by the session marker ends its newest turn, and no background task,
   subagent, or scheduled wakeup owes a notification.
2. The screen shows no open question or approval prompt.
3. The input line holds nothing typed. A grey suggestion counts as empty: type `x` once and delete it with one
   backspace only when the draft shows exactly that `x`; typed text extends instead of being replaced. Never delete
   input you did not type. If an `x` stays on the line, report its position.

## Send and confirm

Send only the actions the run lists for that session, one at a time: `/reload-plugins` first, `/compact` only when the
session reports a `compact_reason`. Confirm each result from the transcript records appended after the send or, without
a transcript, from the screen, as the script does. To end and resume a session, follow `references/resume.md` by hand.

## Record each result

Run `python3 <script> record-manual --run-id <run_id> --terminal <handle> --action <reload|compact|clear|resume>
--result <done|failed> [--detail <code>] --json` once per finished action, with the full terminal handle. A `failed`
result takes a lowercase `--detail` code and marks the session `failed`, and that action and every other unfinished
one stay outstanding. A `done` result removes only its action from the session's remaining ones; while actions remain,
the session shows its status from before the failure, or `failed` while another failed action remains, and it is
marked `done` once none is left, so `status` and `not_refreshed` show it. The remaining actions are the saved
`actions`, or, when an automatic step cleared them, the `planned` actions not yet done; a `resume` also finishes a
planned reload, because the new process loads the installed plugins.
The command rejects a terminal that is not in the run and a session whose status is not `skipped` or `failed`.
