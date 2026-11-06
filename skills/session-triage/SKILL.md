---
name: session-triage
description: >-
  Show every Claude Code and Codex agent session running in Orca in one table, sort them by whether they wait for
  the user, stalled, finished, or still working, and act on all of them after one approval: answer-only items shown,
  one instruction sent to a stalled session, an idle session exited to free its memory while keeping its terminal
  and recording how to resume it, or a finished session's clean worktree removed. Use when the user asks to see,
  sort out, or clean up running agent sessions in Orca, to find sessions waiting on them or stalled, or to free the
  memory those sessions use, such as "세션 정리해줘", "대기 중인 세션 보여줘", or "free memory used by my agent
  sessions", and when a plugin memory-gate denial suggested it and the user agrees. Not for updating plugins and
  reloading sessions (orca-plugin-refresh), disk cleanup (local-data-cleanup), or creating worktrees.
compatibility: >-
  Needs Python 3.12 or later and the `orca` CLI reaching a running Orca (`ORCA_CLI_COMMAND` overrides the
  executable). `git` is needed only for clean-up checks.
---

# Session Triage

Use this English `SKILL.md` as the only executable source.

Give the user one compact view of every agent session in Orca and let one approval act on all of them. Do everything
that needs no user decision yourself: read, classify, draft, and verify. Ask once, then act.

## Boundaries

- Never act on the current session (`is_current`), not even its worktree comment or unread mark, and never answer
  another session's prompt for the user.
- Never kill a process. A session ends only by its own exit command typed at an idle prompt, and a terminal closes
  only after its agent exited and nothing else runs in that worktree.
- Never change a board status. Write only the comment a `sleep` needs.
- One approval covers only the actions listed in the question. Silence is not approval. Anything outside the list
  needs a new question.
- A check that fails, or cannot be read, skips that session and says why. Do not retry around it.

## Workflow

### 1. Read once

```text
python3 scripts/session_overview.py
```

Run it by its path relative to the directory that holds this `SKILL.md`, once per run. It is read-only and prints
one JSON object: `host_total_mb`, `host_available_mb`, `sessions[]`, `worktrees_without_agent[]`, and `warnings[]`.
Exit 2 means Orca was unreachable or a required read failed; report its one-line reason and stop. Show every
warning that affects a row. A `null` memory or terminal handle means that value is unknown, never zero.

### 2. Classify

Judge each session from `last_assistant_message`, `state`, `board_status`, `comment`, `prompt`, and
`minutes_in_state`; the last message ends with what the session asks.

| Class | Meaning |
|---|---|
| `needs you` | It asks the user a question, decision, or approval. |
| `working` | `state` is `working`. |
| `stalled` | Its turn ended, the work is not finished, and nothing is asked of the user. |
| `finished` | Its work is done and nothing is left. |
| current | `is_current`; shown, never acted on. |

A `done` session with no clear ending is `stalled`, not `finished`. When the message cannot decide it, say
so in the row instead of guessing.

### 3. Recommend one action per session

| Action | Use when |
|---|---|
| `answer` | `needs you`. User only: show the question in one line. |
| `continue` | `stalled`. Send one instruction. Draft it only when the next step follows from that session's own last message; otherwise ask the user for it. |
| `sleep` | It waits on something slow, such as a review, a schedule, or the user, and host memory is low or it has waited long. Exits the agent CLI, keeps the terminal. Never for a session that would lose work by exiting: one whose screen shows monitors, background tasks or terminals, or running subagents, or whose last message says it will continue by itself at a later time, unless you found the process or scheduler that does that outside the session. |
| `clean up` | Only `finished`, in a non-main worktree with no children (`is_main_worktree` false, `child_count` 0). |
| `keep` | Everything else, including every `working` session and the current one. |

Treat host memory as low when `host_available_mb` is under 2048 MB, the plugin's default threshold for starting
another agent session. When it is unknown, say so and do not call it low. A session with an unknown terminal handle can only be
`answer` or `keep`.

### 4. Show one table and ask once

Show one table sorted with `needs you` first, in the user's language: session, repository or display name, class,
what it waits for or did last in one line, minutes in state, memory, recommended action. Add the host's total and
available memory, the `worktrees_without_agent` rows with their terminal memory unknown, and the warnings.

Then ask one question that lists the proposed actions, `sleep`, `continue` (with the exact instruction), and
`clean up`, preselected or individually selectable as the host's question tool allows. Wait for the answer. Run
nothing before it. When there is nothing to act on, say so and ask nothing.

### 5. Run the approved actions

Before any send, run `orca terminal read --terminal <handle> --screen`. Send only when no approval prompt or
question is open and the input line is empty. Text on the line can be the host's grey suggestion: send
`--text x` without `--enter`; when the line then shows only `x`, delete it with `--text $'\x7f'` and go on. Otherwise
delete the `x`, skip that session, and say the user's text is there. Recheck the screen right before an exit command.

- `continue`: `orca terminal send --terminal <handle> --text "<instruction>" --enter --json`.
- `sleep`: send the exit command for its `agent_type`, wait until the screen shows the shell prompt, and read the
  resume command it printed, such as `claude --resume <id>` or `codex resume <id>`. Then run
  `orca worktree set --worktree "id:<worktree_id>" --comment "<one-line sleep note with the resume command> · <previous comment>" --json`,
  leaving the board status alone. If no resume command shows, say so and keep the session's `conversation_name`
  in the note.
- `clean up`: first confirm all of these, and ask the user instead when any fails:
  - the worktree is not a main worktree, has no children, and is not the current session's worktree;
  - `orca terminal list --worktree "id:<worktree_id>" --json` shows only this session's terminal, and no other row
    of the overview has the same `worktree_id`, so no other session or shell uses that checkout;
  - the screen shows an idle prompt with no open question and no monitors, background tasks, or running subagents;
  - `git -C <path> status --porcelain` is empty, with ignored files only regenerable caches;
  - the branch's commits are in the base branch (`git -C <path> merge-base --is-ancestor HEAD <base ref>`; a squash
    merge does not pass, so ask).

  Then exit the agent as `sleep` does and confirm the shell prompt. Look for anything still running there:
  `orca ports --worktree "id:<worktree_id>" --json`, and processes other than the terminal's own shell whose working
  directory is inside the path, such as from `lsof -d cwd -Fpn`. When something remains, keep the terminal and worktree and report it. Otherwise run
  `orca terminal close --terminal <handle> --json` and
  `orca worktree rm --worktree "id:<worktree_id>" --delete-branch --json`. Never a session that is not `finished`.

Exit commands:

| Agent | Command |
|---|---|
| Claude Code | `/exit` (alias `/quit`) |
| Codex | `/quit` (`/exit` is the same) |

### 6. Report

For each action, report its result. Report the host's available memory before and after, rerunning only
`orca diagnostics memory --json` for the after value, and list the user-only items that remain.

To wake a slept session later, on request, read that terminal's screen and send its recorded resume command only
when it shows an empty shell prompt.
