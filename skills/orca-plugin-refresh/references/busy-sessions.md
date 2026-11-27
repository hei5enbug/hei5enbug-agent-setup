# Busy Claude Code sessions

## Queue path and questions

Claude Code queues a command typed during a turn and runs it after the turn ends, one at a time. So `apply` does not
wait for a busy Claude Code session other than the one running the skill. After the usual input checks, the draft
recheck, and a recheck that the turn is still running, it types `/reload-plugins`, and `/compact` when the session's
instructions are stale, into the input line at once and types any held text back before it returns. The session is
`deferred` with the detail `commands_queued` and the `queued` list. This session itself keeps `queued_after_turn`.

The helper confirms each queued command from transcript records after the queue offset, or a compaction from a marker
rewritten after the queue time, and sends nothing more while a queued command has not run and the turn is busy. It
goes back to the ordinary deferred path only after the turn ended and the reload or compact timeout passed without
evidence, rechecking what is still needed, so each command is sent once. Before each queued command after the first, the
screen and the input line are checked again; a dialog or new input stops the typing, and the commands not typed wait for
the ordinary path after the turn. A session still waiting for its answer, or answered `skip`, is left alone by a later
`apply` of the same run. A reload that Claude Code answers with
the MCP-tools refusal is `failed` with `reload_needs_force`. At the one-hour limit an unconfirmed entry is `skipped`
with `queued_unconfirmed`; the commands may still run.

In five cases the script types nothing and deletes nothing. The session becomes `awaiting_answer` and `questions`
holds one question for it: `id`, terminal, host, worktree, title, `reason`, `background`, and `options`. `background`
is `true` when a background task, subagent, monitor, or wakeup may still report back, `false` when none does, and
`null` when the transcript cannot tell, which counts as `true`. `apply`, `refresh`, and `status` list the questions,
and `awaiting_answer` counts as ok for the exit code.

| `reason` | Why the script asks |
|---|---|
| `dialog_open` | A permission prompt or another dialog is open, so typing would answer it. |
| `input_not_restorable` | The input line holds text the script cannot type back exactly, such as a paste placeholder. |
| `reload_needs_force` | A plugin this run changed for the session declares MCP servers (a `.mcp.json` at its root or an `mcpServers` key in its `.claude-plugin/plugin.json`) in its loaded or installed folder, or a folder or the session marker cannot be read. A plugin changed outside this run is not predicted; its refusal stays `failed` with `reload_needs_force`. |
| `orchestration_mail_pending` | Orca holds unread orchestration mail for the session, or its inbox cannot be read. |
| `state_unreadable` | The turn record or the input line cannot be read. |

## Options

Each question offers three options with an English `effect` sentence built by the script. Ask every unanswered
question in `questions` (one without an `answer`; `decide` and `status` also list answered ones) as soon as the script
returns, before any other report, with the question tool and these three options (up to four questions per call), then
run `decide`.

| Option | Effect |
|---|---|
| `wait` | Nothing is typed now. The helper sends the commands once the session is idle, with the usual checks. When the line holds text the script cannot type back exactly, whatever the `reason`, it sends nothing and deletes nothing while that text is on the line; when the line becomes empty or restorable while the turn is still running, it types the commands as a queued command at once, and it ends the session `skipped` with `input_not_restorable` when the line does not change within one hour. |
| `interrupt` | Described under the interrupt rules. For `dialog_open`, the Esc declines the open prompt, and the effect sentence says so. |
| `skip` | Nothing is sent. The session ends `skipped` with `skipped_by_user`. |

No answer authorizes `--force`. A session with no answer stays `awaiting_answer` and nothing is sent to it.

## The decide command

Run `python3 <script> decide --run-id <run_id> --answer <question id>=<wait|interrupt|skip> [--answer ...] --json`
with a shell timeout of at least 600 seconds, once for all answers. It takes the sessions lock and returns the
sessions it handled. Each answer is saved right after its session is handled, so a rerun after a partial failure does not
repeat an action. An unknown question id, or an answer that differs from the one already saved, returns `question_unknown`
and does nothing; an answer that repeats the saved choice is ignored. A question records the conversation it was asked
about: when the terminal runs another conversation by the time of an `interrupt` answer, nothing is sent and the session
is `failed` with `session_replaced`.

## Interrupt rules

1. The session is planned again. When it is already idle, it is applied normally and no continue prompt is sent.
2. Otherwise the script sends one Esc and waits up to 15 seconds for the turn record to leave busy. When it does not,
   the session is `failed` with `interrupt_unconfirmed`, nothing else is sent, and a second Esc is never sent.
3. When `background` is `false`, the script exits and resumes the session with the resume code (no `/reload-plugins`,
   no `/compact`) and notes `resumed_without_compaction`. When a resume check holds that back, it sends `/reload-plugins`
   alone, never `/compact`, and the note `resume_check_skipped:<check>` names the check.
4. Otherwise it sends `/reload-plugins` and, when the instructions are stale, `/compact` through the normal send
   path, because exiting would end the background work.
5. After the actions are confirmed, it sends one fixed English prompt asking the session to continue the work it was
   doing before the plugin update interrupted it, and reports `continue_prompt`. A session that failed gets no prompt; one
   handed to the helper keeps that duty, and the helper sends the prompt after its actions are confirmed.

## Codex sessions

When the install gate finds Codex sessions with a turn in progress, `update` defers the Codex install with
`codex_turn_in_progress`, or with `update_deferred_active_session` when the session running the skill is in a turn,
keeps `recovery_command` in the host result, and adds one `codex_install` question per busy rollout to `questions`. A
question has the fields above with `reason` `codex_install`, the terminal and `worktree` of the session, and `background`
null. A rollout that no Codex session marker names is `outside_orca`: `terminal` is null, `worktree` is its folder, and no
prompt text is read. The session running the skill has `own_session`. Claude Code installs and sessions are unaffected by
every answer.

| Option | Effect |
|---|---|
| `wait` | Nothing is sent now. The detached helper installs once every `wait` session has ended its turn, resumes the Codex sessions on replaced plugin folders, and needs no rerun. |
| `interrupt` | Offered only for an Orca session other than the one running the skill. After every `wait` session is idle, the script presses Esc once, confirms the turn-abort record, installs, resumes the session, and asks it to continue. |
| `skip` | No Codex update this run; nothing is sent to any Codex session. |

A session outside Orca and the session running the skill get `wait` and `skip` only. Under `wait`, the session running the
skill is resumed after its turn like any session on a replaced folder. The script types nothing else into a busy Codex
session and never uses `codex queue`.

Run `decide` once for all Codex answers: every unanswered `codex_install` question needs an answer in that call
(`answers_incomplete`), and a choice the question does not offer is `answer_invalid`. Any `skip` means no Codex update this
run (`hosts.codex.decision` is `skip`, `codex_install.status` is `skipped_by_user`). With only `interrupt` answers the
install runs in the foreground of `decide`; with any `wait` answer the detached helper carries it with a one-hour limit.

The install job, in this order:

1. Wait until every `wait` session's rollout has recorded the end of its turn in its own records, however long ago it was
   written. The session running the skill counts with the rollout found from its thread id; when none is found, `decide`
   refuses a `wait` or `interrupt` answer with `rollout_unknown`, and `skip` still works.
2. Send one Esc to each `interrupt` session that is still busy and still runs the conversation its question named, and
   confirm a turn-abort record. When none is recorded within 15 seconds, Orca rejects the Esc, or the terminal runs another
   conversation, send nothing more to that session and treat it as `wait`.
3. Take the lock, recheck that the job is still pending and inside its limit, recheck the gate, and run the Codex
   marketplace update and installs as `update` does; one caller installs a job. A companion that reports `error` fails the job.
4. Write the Codex host result without the error and save the new `script` path; use it for every later command, because
   the install deletes the old copy.
5. Plan the Codex sessions and resume the ones on replaced folders, the session that ran the skill included.
6. Send the continue prompt to the interrupted sessions only.

At the limit nothing is installed and `codex_install.status` is `not_idle_before_deadline`. The result in `decide` and
`status` holds `codex_install` with `status` (`pending`, `done`, `failed`, `skipped_by_user`, or
`not_idle_before_deadline`), the last gate `detail`, and each interrupted session's state.
