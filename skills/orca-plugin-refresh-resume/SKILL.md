---
name: orca-plugin-refresh-resume
description: >-
  Preview and update hei5enbug-agent-setup in idle Orca-managed Claude Code and Codex sessions, then resume each
  session with its existing native ID. Use only when the user asks to refresh this plugin and continue the sessions.
compatibility: >-
  Requires macOS or Linux, Orca-managed Claude Code and Codex terminal sessions, the enabled user-scope plugin
  from the hei5enbug marketplace in both hosts, Python 3.12+, and the codex, claude, and Orca CLIs.
---

# Orca Plugin Refresh and Resume

Run a reviewed update transaction for `hei5enbug-agent-setup` across its registered Orca-managed Claude Code and
Codex sessions. This skill does not update other plugins or restart Orca.

## Preconditions

- Run inside an Orca-managed Claude Code or Codex terminal on macOS or Linux.
- Orca's terminal inventory must provide a process incarnation ID for every target agent terminal. Without it, stop
  before planning an update; a runtime handle alone cannot prove which process will receive `/exit`.
- Both hosts must have the enabled user-scope `hei5enbug-agent-setup@hei5enbug` plugin installed from
  `https://github.com/hei5enbug/hei5enbug-agent-setup.git`.
- Codex plugin hooks must be enabled, reviewed, and trusted. Claude Code plugin hooks must be enabled.
- Each target session must have a lifecycle registry entry created by this plugin. Older sessions have no entry:
  install this feature, review and trust its hooks, then manually restart or resume every existing session once.
  Do not infer native session IDs from terminal previews or transcript files.
- Before running `apply`, follow the active session's hosted-service access rules for refreshing marketplaces.

If the platform, marketplace, plugin scope, hook state, or session registry cannot be verified, stop and report the
specific blocker. Never update a different marketplace source or infer a session ID.

## Workflow

Resolve the plugin root from the loaded skill path. The script is at `<plugin-root>/scripts/orca_plugin_refresh.py`.
The `plan` command reads current Orca terminals, the local lifecycle registry, installed plugin versions, and cached
marketplace manifests. It saves a private plan under Orca's user-data directory and returns a short preview without
updating marketplaces or plugins.

Run:

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py plan --json
```

Show the target versions, every Claude Code and Codex terminal, its worktree, short terminal handle, state, and any
blockers. Do not include native session IDs in the chat. If the plan is blocked, do not run `apply`. Explain that all
non-initiating sessions must be idle and registered. Claude Code background tasks and session-scoped scheduled wakeups
also prevent an idle verdict. Ask the user to run a new plan after resolving the blocker.

When the preview is eligible, ask the user to approve its exact `plan_id`. Do not treat a general request to update as
approval to skip this preview. On a later explicit approval, run:

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py apply --plan-id <plan_id> --json
```

`apply` rechecks the terminal set, session IDs, worktrees, marketplace versions, and installed versions. It permits the
initiating session to be busy only because it is processing the approval; every other target must still be idle.
It records a transaction lease, starts the detached worker, and returns a transaction ID. End the current turn after
reporting that ID. The worker waits for the initiating turn to finish before updating plugins or restarting sessions.
Do not poll or send another prompt to a target session during the transaction. The lifecycle hook normally blocks
new prompts until the worker releases the lease and sends the completion notice to the resumed initiating session.

The hook cannot guarantee prompt exclusion if the host times it out or does not run it. The worker checks the planned
native session's current registry handle, process incarnation, lease, and Orca idle state again immediately before
exit. If the planned process cannot be verified, stop; do not substitute another terminal in that worktree.

The worker refreshes both configured marketplaces and verifies the planned versions and revisions are still current.
It updates the installed plugin in both hosts and resumes each session in its original worktree with the same native ID.
Before each exit it checks the Orca `tui-idle` state again. It uses `/exit`, waits for process exit, then creates a new
terminal. It does not force-kill a session or close a worktree. A resumed session must register the target plugin
version through `SessionStart` before it counts as complete.

If marketplace refresh changes either planned version or revision, the worker stops before installing or exiting
sessions. Ask the user to review a new plan. If Claude Code requires approval for a marketplace-declared command,
do not auto-accept it; report the command hash from the receipt. The user must inspect the pending command with
`claude plugin update hei5enbug-agent-setup@hei5enbug --json`, then create a fresh plan and explicitly approve the same
hash with:

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py apply --plan-id <fresh_plan_id> --accept-command <sha256> --json
```

If the worker reports an error, show its safe status and recovery instructions without retrying or rolling back
automatically.

## Status and recovery

Use the receipt path returned by `apply` or the latest transaction:

```bash
python3 <plugin-root>/scripts/orca_plugin_refresh.py status --transaction-id <transaction_id> --json
python3 <plugin-root>/scripts/orca_plugin_refresh.py status --json
```

If a worker stopped unexpectedly, first establish outside the target agent sessions that the worker process has
stopped. Then run the receipt's recovery command with `--confirm-worker-stopped`. Recovery only clears the matching
lease and records current terminal states; it does not update plugins, exit sessions, or resume them. Use the exact
manual resume command in the private receipt for a session that the worker could not resume. If status reports
`manual_resume_requires_terminal_check`, inspect the possibly live new terminal and confirm that agent has exited
before running the command; otherwise a second process could resume the same session concurrently. A recovered
session whose terminal identity is unverified stays busy until its lifecycle hook records the current handle.

If status reports `complete_but_not_confirmed` or `complete_but_not_delivered`, read the receipt directly. Do not
resend the completion prompt blindly: Orca may have accepted it without proving that the turn started.

## Safety and data

- `plan` and `status` do not change plugins or terminals. `plan` writes a private plan file under Orca user data.
- `apply` can update only this plugin in the verified `hei5enbug` marketplace and can restart only registered
  Claude Code and Codex sessions in the preview.
- A busy, unregistered, stale, duplicated, or ambiguous session blocks the operation before plugin installation.
- A plugin hook is a best-effort guard, not an atomic lock on host input. Never claim that an idle preview alone proves
  interruption-free continuation or that a timeout cannot admit another prompt.
- The registry stores host, native session ID, Orca handle, worktree, cwd, plugin version, lifecycle state, and
  timestamps. It never stores prompts, transcripts, tokens, or arbitrary environment variables. Files use
  user-only permissions; ended records older than 30 days are removed on a later registry write.
- Transaction receipts omit raw CLI output and environment values. They retain the session IDs needed for resume and
  recovery under Orca's user-data directory.
- Plugin version updates are not rolled back automatically. After partial failure, the receipt records each completed
  step and the next safe action.
