---
name: orca-plugin-refresh
description: >-
  Safely refresh hei5enbug-agent-setup in Claude Code and Codex, then apply an installed version to idle
  Orca-managed sessions. Updates defer by default; an explicit offline update requires ended coding-agent
  sessions and no contradictory host, plugin, or terminal state. Use apply-installed when installation is
  already complete and the user asks to refresh running sessions.
compatibility: >-
  Requires macOS or Linux, Python 3.12+, and the user-scope hei5enbug-agent-setup plugin from the hei5enbug
  marketplace. The claude and codex CLIs read installed versions and refresh both installs. Applying to sessions
  requires an Orca terminal and the Orca CLI; an attested offline update can proceed without the Orca CLI when
  no active environment is present.
---

# Orca Plugin Refresh

Use this English `SKILL.md` as the only executable source. `SKILL.ko.md` is a non-authoritative human
translation; never load it during execution.

This skill updates `hei5enbug-agent-setup` only after affected coding-agent sessions have ended. It can also
apply a version that the user has already installed to running Orca sessions without ending them. It never
restarts a session or replaces a conversation.

## How an update reaches a running session

| Part | Claude Code | Codex |
|---|---|---|
| Skills, agents, and hooks | `/reload-plugins` | The next turn picks up the new install automatically |
| Session instructions | `/compact` | `/compact`; the session loads them on its next turn |

The plugin's session-start hook writes one marker per Orca terminal with the host, plugin directory, transcript
path, and a digest of the executable instructions. Only the terminal's interactive session writes it; a child
`claude -p` or `codex exec` started inside that terminal does not. The script compacts only a session whose marker
is missing, holds another digest, points a Codex session at a replaced plugin directory, or points a Claude Code
session at a removed one. When Claude Code answers that a session has too few messages to compact and its
transcript holds no prompt, the script sends `/clear` instead, because an empty session has nothing to lose. A
Codex session that never ran a turn needs nothing: its first turn loads the new instructions.

## Workflow

Let `<script>` be `scripts/orca_plugin_refresh.py` in the directory that holds this `SKILL.md`.

1. **Choose the install path.** For a new plugin update, run `python3 <script> update --json`. Updates defer by
   default, including when no Orca session is visible, because this command requires an explicit offline
   attestation. Do not retry a deferred update automatically. If the user explicitly says all affected
   coding-agent sessions have ended and asks for the offline update, run
   `python3 <script> update --offline --json`. The script still rejects active host, plugin, or Orca session
   state. If installation was already completed outside this skill, or the user asks to apply the installed
   version, run `python3 <script> apply-installed --json`; this reads installed roots and does not run marketplace
   or install commands.
2. **Handle the update result.** Report each host's version change. When a host has an `error`, report its code
   and message; its sessions stay untouched. A deferred host also returns its current `root` and
   `recovery_command`. Use that command only after the affected sessions have ended and from a normal terminal
   with no active host, plugin, or Orca terminal environment. Orca inventory covers managed terminals only; it
   cannot establish that non-Orca coding-agent sessions have ended. If inventory is unavailable, truncated, or
   unsupported, the script defers with `update_deferred_unknown_session_state`. Use the returned `script` path
   for every later command, because a Codex update deletes the installation this skill was loaded from. Report
   every warning:
   - `unreleased_same_version`: Claude Code keeps its installed copy because the version did not change. Tell
     the user these files reach Claude Code only after a version bump.
   - `codex_hooks_need_trust`: the hook definitions changed. Ask the user to trust the plugin hooks in Codex
     `/hooks`; Codex skips untrusted hooks.
   - `unreleased_check_unavailable`: the script could not tell whether Claude Code missed same-version files.
     Report the reason.
3. **Apply to the sessions.** When a host update succeeded, or `apply-installed` returned that host without an
   error, run `python3 <script> apply --run-id <run_id> --json` in the foreground with a shell timeout of at
   least 600 seconds. For 240 seconds the script waits for busy sessions and sends a command only to an idle
   session whose input line is empty; after that it starts nothing new and keeps confirming the commands already
   sent, for up to five more minutes. An `already_running` error means another run is still sending; wait for it,
   then run `apply` again. A host with an update error stays blocked while successful hosts can proceed.
4. **Report every session.** Show the terminal suffix, host, worktree, status, completed actions, and detail:
   - `done`: every needed action is confirmed. `already_current` means nothing was needed, and
     `fresh_session_loads_on_first_turn` marks a Codex session that never ran a turn. The note
     `empty_session_cleared` marks an empty Claude Code session that got `/clear`, and
     `instructions_load_on_next_turn` marks a compacted Codex session.
   - `skipped`: the session stayed busy, kept unsent input, showed an unreadable input line, changed its input
     just before the send, reached the deadline, or closed.
   - `failed`: an action was sent but not confirmed, or Claude Code refused it. A reload refusal that asks for
     `--force` means a plugin's MCP tools changed; do not force it without the user's approval.
     `compact_needs_more_messages` means the conversation is too short to compact; its instructions refresh at
     its next compaction or restart. `probe_interrupted_check_input` means the user typed while the script
     checked the input line; tell the user to check that session's input line for a stray `x`, because the script
     never deletes input it did not type. `helper_start_failed` means this session's follow-up could not start;
     run `apply` again.
   - `blocked`: that host's plugin update failed or its installed manifest, hook targets, or instruction digest
     did not validate.
   - `queued_after_turn`: this session itself; see step 5.
5. **Finish this session last.** When the session running this skill needs an action, `apply` hands it to a
   detached helper and reports `queued_after_turn`. End the turn right after the report. The helper waits until
   this session is idle, applies the actions, and then sends a prompt that asks to run
   `python3 <script> status --run-id <run_id> --json`. When that prompt arrives, run it and report the result.
   When `self_notification` in the status is not `sent`, the prompt could not be delivered; the status still
   holds the result.

Pass `--compact always` or `--compact never` only when the user explicitly asks for it. Never send commands to
Orca terminals by hand, never exit or restart a session, and never pass `--force` on your own.

## Safety and limits

- `update` does not run marketplace or install commands unless `--offline` is explicit and the caller has no
  active coding-agent, plugin, or Orca terminal environment. Host markers such as `CLAUDECODE`,
  `CODEX_THREAD_ID`, and `CODEX_SESSION_ID`, plugin-root variables, and `ORCA_TERMINAL_HANDLE` count as active
  signals. A connected coding-agent terminal is active even when its prompt is idle.
- `--offline` is an attestation that affected coding-agent sessions have ended, not a bypass. Active environment
  signals or a connected coding-agent terminal in readable Orca inventory still defer the update. If Orca is
  installed but its inventory cannot be read completely, the script defers as unknown. With no Orca CLI, an
  explicit offline attestation and no active environment may be enough.
- Before reporting an install as successful, the script checks the host manifest and version, every required
  hook target, and the instruction digest. A failed host remains blocked while another host's successful result
  is preserved.
- A command goes only to a connected, writable, idle terminal whose input line is empty. A short race between
  that check and the send remains.
- Orca hides the Claude Code input line from the screen and reports it as a draft, which also carries Claude
  Code's grey prompt suggestion. When a draft stays unchanged for five seconds, the script types one character
  and deletes it only when the draft shows exactly that character: a suggestion is replaced and typed text is
  extended, and both come back unchanged. A session with typed text is skipped, never sent to. The script checks
  the draft again just before each send.
- `/clear` runs only after Claude Code refuses to compact and the transcript, read again right before the send,
  holds no prompt.
- Each result is confirmed from transcript records appended after the send, or from a marker rewritten after it,
  and from the screen only when no transcript is available.
- One lock covers every process that sends commands, including this session's detached helper.
- `/compact` summarizes the conversation, so it runs only for sessions whose instructions are stale.
- A Codex session that was compacted loads the new instructions at its next turn; the report says so.
- Only Orca-managed terminals are reached. The offline attestation is responsible for non-Orca sessions; the
  inventory cannot prove they have ended.
- Manual updates outside this workflow and another process deleting a loaded plugin directory remain outside
  this skill's enforcement boundary.
- Run state lives under `~/.local/state/hei5enbug-agent-setup/orca-plugin-refresh/`, or under
  `$XDG_STATE_HOME` when it is set, and markers live under Orca's user-data directory. Neither stores prompts
  or transcripts.
