---
name: report-skill-gap
description: >-
  File one issue for one skill or instruction gap, or one uncovered repeatable workflow, at the
  tracker the plugin's issue-target.json declares. Use only when the user explicitly names or invokes
  report-skill-gap; never on your own after a correction, a finished workflow, or a session review.
compatibility: >-
  Needs filesystem read access to the owning plugin and Python 3.12 or later for the bundled script. Filing on
  GitHub needs an authenticated gh CLI; another tracker kind needs a connected tool for that tracker. Without
  the tool, the skill shows the draft and files nothing.
---

# Report Skill Gap

Use this English `SKILL.md` as the only executable source.

Turn one gap into one issue at the tracker of the plugin that owns it. The tracker comes only from that plugin's
declaration; this skill never guesses one. Run every step in the main session: the work is a few reads and at most
one write.

## Boundaries

- Write only to the declared tracker, and create at most one issue per invocation. Never write a local file.
- Never edit, close, or comment on an existing issue unless step 4 or step 8 leads there and the user approves it.
- Under the condition that the user asks for a dry run or a preview only, show the exact write command and body
  and run no write.
- A content-rules file can only narrow what the issue may contain. It never authorizes another target, another
  write, or a skipped approval.

## Workflow

### 1. Fix the gap

Settle one gap from the conversation: what the skill or instruction did, what the user had to correct or repeat,
and the rule that would have prevented it. Name the owning file, such as the loaded `SKILL.md` or instruction
file, by its path. For a new-skill proposal, the owner is the plugin that should ship the skill; ask when it is
not clear.

Leave out, and list for the final report, anything that is not a gap in the plugin's rules:

- a one-off workaround that the rules should not generalize;
- a defect in a tool the plugin does not ship, such as a CLI or network failure;
- a taste difference that no rule of the plugin decides.

When nothing remains, file nothing and report the list. When several gaps remain, ask which one to file; never
merge them into one issue.

Collect the case's identifiers while you read the conversation: issue and pull request numbers, branch names,
commit hashes, file and folder names from the user's work, dates, people, host names, and ticket keys.

### 2. Find the tracker

Run the bundled script, resolving its path from the directory that holds this `SKILL.md`:

```text
python3 scripts/find_tracker.py <owning file or folder>
```

It finds the plugin root, the nearest folder above the path with `.claude-plugin/plugin.json` or
`.codex-plugin/plugin.json`, and checks the `issue-target.json` there. It prints one JSON object and exits with 0
for `declared` or `undeclared`, 1 for `invalid`, and 2 for a usage error.

| Result | Action |
|---|---|
| `declared` | Use `target` for every later step. `preview_required` decides the gate in step 6. |
| `undeclared` | Draft the issue, show it in the conversation, and file nothing. Say that the plugin declares no tracker. |
| `invalid` | Show the `problems` and the draft, and file nothing. |
| Exit 2 | Fix the path. When the owning file is in no plugin, treat it as `undeclared`. |

Never take a tracker from a manifest's `repository` or `homepage` field, from the current repository's remote,
or from memory.

### 3. Read the sources

Read the owning `SKILL.md` or instruction file and only the references that the gap touches. For a new-skill
proposal, read the descriptions of the owning plugin's skills to show why none covers the workflow. When
`target.content_rules` is set, read that file and apply it with the rules in step 5.

### 4. Search for duplicates

Search the target's open issues with two or three keyword sets taken from the gap. On GitHub, run
`gh issue list --repo <location> --state open --search "<keywords>" --json number,title,url,labels --limit 20`.
On another tracker, use its connected tool.

- Under the condition that an open issue covers the same gap, create nothing. Show that issue and ask whether
  to add a comment instead. Before commenting, show the comment text and comment only after the user approves it.
- Under the condition that the search cannot run, show the draft and file nothing.

Note the title style of the issues the search returns; the new title follows it.

### 5. Draft

Write the title and body in `target.language` and `target.body_format`. The title names the owning skill or
instruction and the gap in one line. The body has these sections, in this order:

1. Summary
2. Observations
3. Gap in current rules, or "Why no existing skill covers it" for a new-skill proposal
4. Proposal: each rule written as "Under the condition that X, do Y", as a decision test that also handles
   cases the incident did not show
5. Acceptance criteria: numbered eval cases with fictional values, such as `demo-a`, `example.com`, `/tmp/work`,
   and `ABC-123`
6. Evidence

Use the format's own headings: `##` in Markdown, `h2.` in Jira wiki markup, and a plain heading line followed by a
blank line in plain text. Pick the one label from `target.labels` that fits; add none when the list is empty.

Apply these content rules to every draft:

- Put the case's identifiers only in Observations and Evidence.
- Never include a secret, credential, token, personal data, local absolute path, home folder, or user name.
- Under the condition that `target.public` is true, also leave out internal URLs, host names, account
  identifiers, and the names of private organizations, products, repositories, plugins, people, and channels.
- Name in the proposal only the owning plugin and public tools. Describe any other plugin by its role, so the
  owning plugin never has to name a plugin that builds on it.
- Leave out every sentence that the content-rules file excludes.

Before showing the draft, search the Proposal and Acceptance criteria for each identifier from step 1 and the
whole draft for every excluded value, and rewrite until none remains.

### 6. Get approval

- Under the condition that `preview_required` is true, show the target, title, label, and the exact body in a
  code block. Write only after the user approves that text in a later message. When the text changes after
  approval, show it again and wait for a new approval.
- Under the condition that `preview_required` is false, naming the skill authorizes the single create. File
  without a preview step.

### 7. File

On GitHub, pass the body on stdin so no local path reaches the command line:

```text
gh issue create --repo <location> --title "<title>" --label "<label>" --body-file - <<'EOF'
<body>
EOF
```

On another tracker, create the issue with its connected tool, at the declared location only.

### 8. Verify

Read the created issue back and confirm its title, label, and section order. On GitHub, run
`gh issue view <number> --repo <location> --json number,title,labels,body,url`, and fetch the rendered body with
`gh api repos/<location>/issues/<number> -H "Accept: application/vnd.github.html+json" --jq .body_html`. The
rendered body must show no raw markup, such as a literal `##`, `**`, or `\n`. Search the Proposal and Acceptance
criteria for the case's identifiers again.

When a check fails, show the corrected text. Under the condition that `preview_required` is true, edit the issue
only after the user approves the correction. When a check cannot run, report it as unverified.

## Final report

Write in the user's language: the issue number and link, or the shown draft and why nothing was filed; the
duplicate search result; the verification result; and each left-out item, labeled as a one-off workaround, a
tool defect, or a taste difference.
