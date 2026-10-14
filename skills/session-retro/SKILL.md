---
name: session-retro
description: >-
  Review one day's coding-agent session history for a repository, from Claude Code and Codex, and turn
  the evidence into concrete improvements for existing skills and candidates for new skills, grouped by
  plugin. Use when the user asks to look back over a day's sessions of a repository to find skill or
  plugin improvements, such as "오늘 이 레포 세션 히스토리 보고 스킬 개선점 정리해줘" or "review today's agent
  sessions for skill improvements", and when the user then asks to resolve the open decisions or to write
  the resulting plans. Do not use to summarize a single conversation, to debug one failure, or to review
  code.
compatibility: >-
  Needs filesystem read access to the hosts' session folders and Python 3.12 or later for the bundled
  listing script. Independent read-only workers are optional; without them the main session reads the
  sessions itself.
---

# Session Retrospective

Use this English `SKILL.md` and its English references as the only executable sources. `SKILL.ko.md` and other
`.ko.md` files are non-authoritative human translations; never read them during execution.

Find what went wrong or was repeated in a day's agent sessions, and turn it into evidence-backed skill
improvements. The evidence comes from the session records; the improvements are decided in the main session.

## Boundaries

- Never change a session record, the user's repository, or an installed plugin.
- Write worker assignments and results only to the host's session temporary folder. When the host has none,
  create a new folder under the operating system's temporary folder.
- Write to a repository only in step 7, and only under its `.plan/` folder.
- Session records can hold secrets and private conversations. Quote only the few words a finding needs, and
  never copy a credential, token, or personal data into any output.
- Keep everything specific to one organization, such as hosts, ticket keys, and people, in the target
  repository's plan, never in this skill.

## Workflow

### 1. Fix the target

Settle from the request: the day (default today in the local time zone), the repository whose sessions to
read (default the current working directory), and the plugins the improvements are for. When the request is
ambiguous, such as "this repository" while several repositories are in view, state the reading you chose.

### 2. List the sessions

Run the bundled script, resolving its path from the directory that holds this `SKILL.md`:

```text
python3 scripts/list_sessions.py --date <YYYY-MM-DD> --cwd <repository path> [--tz <zone>] [--claude-dir <dir>] [--codex-dir <dir>]
```

It prints one JSON object with `sessions` and `skipped`, and exits with 0 when the scan finished, 2 for an
invalid argument, and 1 when a session folder exists but cannot be listed. Pass `--claude-dir` or
`--codex-dir` only when the user names other session folders. Report every `skipped` entry.

Choose the sessions to review:

- Review sessions whose `source` is interactive, such as `cli`. Group a Codex session whose `source` is
  `subagent` under its `parent_session_id`, and review the group as one.
- Leave out automated runs, such as `exec` sessions started by worker runners, unless the user asks for them.
- Review the current session from the conversation itself instead of its record.

### 3. Gather evidence

Give each chosen session or group to one read-only scout through the host's scout route, with the assignment
in `references/scout-assignment.md`. When the host has no worker route, read the records in the main session
with the same assignment. A scout returns evidence only, in six sections: the user's requests; corrections,
complaints, and repeated instructions; failures and retries; skill use; repeated manual work; and what it
could not confirm. It never proposes an improvement.

Check that each scout ran on the model and effort its route pins before you accept its result. When a scout
fails, use the route's named fallback once and report the substitution.

### 4. Verify against the sources

For every finding that claims a defect in a skill, a script, or a rule, read the installed plugin source and
cite the file and line that cause it. Mark a claim you could not confirm as unverified, and keep it out of the
improvements unless the user decides otherwise.

### 5. Write the improvement table

Present the result in the user's language, grouped by plugin:

- Existing skills: one heading per skill, with short bullets that say only how to change it.
- New skills: a table with the plugin, a working name, what it does, the evidence sessions, and the expected
  effect.

Name every item's evidence sessions with short labels, and give the labels once in a small table. End with
what could not be confirmed.

### 6. Ask the open decisions

Collect what only the user can decide, especially requests from different sessions that conflict with each
other, and requests that conflict with a rule of the plugin. Ask them, a few at a time, with the options and
the recommended one first. Wait for the answers, then update the table. Ask again only when an answer opens a
new decision.

### 7. Write the plans, when asked

When the user asks for plans, write one plan per repository under `<repository>/.plan/<descriptive name>/`.
Follow the host's implementation planning rules when it has them; otherwise state the goal, scope, decisions,
changes per skill, tests, and verification. Write nothing else in the repository.

## Final report

State the sessions reviewed and left out, the workers' model evidence, the improvement table, the decisions
taken, and the plan paths when step 7 ran.
