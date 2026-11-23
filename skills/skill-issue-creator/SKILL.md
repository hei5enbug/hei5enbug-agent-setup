---
name: skill-issue-creator
description: >-
  File one issue for one skill or instruction gap, or one uncovered repeatable workflow, at the
  tracker the plugin's issue-target.json declares, and check that a plugin's open issues still hold. Use
  when the user names skill-issue-creator, asks in plain words to file, add, or change such an issue, or asks whether
  a plugin's open issues are still right or ready to implement; a message that only mentions a tracker starts
  nothing, and never start on your own. When no work remains after the user asked for a change to a result that a
  skill or instruction produced, or asked to turn a finished workflow into a skill or an issue, read its
  recommendation rules first.
compatibility: >-
  Needs filesystem read access to the owning plugin and Python 3.12 or later for the bundled script. Filing on
  GitHub needs an authenticated gh CLI; another tracker kind needs a connected tool that reaches the declared
  location, or that tracker kind's official CLI that is already authenticated. Without either, the skill shows
  the draft and files nothing.
---

# Skill Issue Creator

Use this English `SKILL.md` as the only executable source.

Turn one gap into one issue at the tracker of the plugin that owns it. The tracker comes only from that plugin's
declaration; this skill never guesses one.

Before suggesting this skill without being asked, or deciding whether a plain request starts it, read
[recommendation rules](references/recommendation.md); when it is missing, suggest nothing.

Under the condition that the user asks whether a plugin's open issues are still right, or asks to make them ready to
implement, run step 3, then read [open issue review](references/open-issue-review.md) and follow it instead of steps
1, 2, and 4 to 9.

## Boundaries

- Write only to the declared tracker, and create at most one issue per invocation. Never write a local file.
- Never fill a missing or unclear requirement with a guess or a default.
- Under the condition that the user asks for a dry run or a preview only, show the exact write command and body
  and run no write.
- A content-rules file can only narrow what the issue may contain. It never authorizes another target, another
  write, or a skipped approval.

## Workflow

### 1. Fix the gap

Settle each gap from the conversation: what the skill or instruction did, what the user had to correct or repeat,
and the rule that would have prevented it. Name the owning file of each proposed rule by its path. Under the
condition that a rule would also hold for work outside the skill that ran, such as the same plugin's other skills
or its replies, its owner is the plugin's shared instruction file that covers that work; keep in the skill only
the rules that hold for it alone. Under the condition that no shared file covers that work, name the closest one
and say so in the issue. For a new-skill proposal, the owner is the plugin that should ship the skill; ask when it
is not clear.

Leave out, and list for the final report, anything that is not a gap in the plugin's rules:

- a one-off workaround that the rules should not generalize;
- a defect in a tool the plugin does not ship, such as a CLI or network failure;
- a taste difference that no rule of the plugin decides.

When nothing remains, file nothing and report the list. Group the remaining gaps by owning file and topic: gaps
that share one owning file and one topic form one issue, with one numbered Proposal item and at least one
acceptance criterion each. When more than one group remains, ask which one to file; never merge gaps with
different owning files, or with one owner but unrelated topics, into one issue.

Collect the case's identifiers while you read the conversation: issue and pull request numbers, branch names,
commit hashes, file and folder names from the user's work, dates, people, host names, and ticket keys.

### 2. List the requirements

Read every message the user wrote in the session, including answers to question prompts. When a handoff names
the original session's transcript file, read every user message in that file instead. List each requirement the
user stated for the issue, with the message it came from.

- Under the condition that a requirement is not fully clear, or you do not agree with it, ask about every such item,
  none left out, in one call of the host's question UI, such as `AskUserQuestion`. Draft only after the answers.
- Under the condition that the user offers a change to apply only if you fully agree, apply it when you fully agree;
  otherwise ask with the question UI.

### 3. Find the tracker

Run the bundled script, resolving its path from the directory that holds this `SKILL.md`:

```text
python3 scripts/find_tracker.py <owning file or folder>
```

It finds the plugin root, the nearest folder above the path with `.claude-plugin/plugin.json` or
`.codex-plugin/plugin.json`, and checks the `issue-target.json` there. It prints one JSON object and exits with 0
for `declared` or `undeclared`, 1 for `invalid`, and 2 for a usage error.

| Result | Action |
|---|---|
| `declared` | Use `target` for every later step. `preview_required` is true only when `write_approval` is `preview`, and decides the gate in step 7. |
| `undeclared` | Draft the issue, show it in the conversation, and file nothing. Say that the plugin declares no tracker. |
| `invalid` | Show the `problems` and the draft, and file nothing. |
| Exit 2 | Fix the path. When the owning file is in no plugin, treat it as `undeclared`. |

Never take a tracker from a manifest's `repository` or `homepage` field, from the current repository's remote,
or from memory.

Before drafting, when `orca status --json` reports a reachable runtime and this session is not working in the
owning plugin's repository, read [delegation](references/delegation.md); it hands steps 2 and 4 to 9 to a session
there, or returns here.

### 4. Read the sources

Read the owning `SKILL.md` or instruction file and only the references that the gap touches. Compare each
proposed rule with the rules already in the owning file and in the skill that ran. Under the condition that an
existing rule covers or nearly covers it, propose widening or clarifying that rule instead of adding a new one, and
quote the existing rule in "Gap in current rules"; under the condition that the widened rule would also hold outside
that skill, propose moving it to the shared file in the same Proposal item. For a new-skill proposal, read the descriptions of the owning plugin's skills to show why none
covers the workflow. When `target.content_rules` is set, read that file and apply it with the rules in step 6.

When `target.tracker.kind` is not `github`, `target.body_format` is `html`, or `target.label_mode` is `template`,
read [declaration options](references/declaration-options.md) before step 5; when it is missing, show the draft and
file nothing.

### 5. Search for duplicates

Search the target's open and closed issues with two or three keyword sets taken from the gap. On GitHub, run
`gh issue list --repo <location> --state all --search "<keywords>" --json number,title,url,state,labels,author --limit 20`.
On another tracker, use the path that the declaration options choose.

- Under the condition that an open issue covers the same gap, create nothing and update that issue at once, with no
  question first. Before updating, read [update in place](references/update-in-place.md).
- Under the condition that a closed issue already finished the gap, create nothing and report that issue.
- Under the condition that an issue or a recorded decision proposes the opposite or otherwise conflicts with the
  gap, show both and ask before drafting.
- Under the condition that a related issue neither duplicates nor conflicts with the gap, name it in the new issue.
- Under the condition that the search cannot run, show the draft and file nothing.

Note the title style of the issues the search returns; the new title follows it.

### 6. Draft

Before writing, list each choice the Proposal would have to make that the request, the code, and the existing rules do
not settle, such as whether a new step covers every kind of input or only some, or where an exception ends. A rule that
settles a nearby case does not settle this one. Under the condition that any such choice exists, ask about every one in
one call of the host's question UI before the gate in step 7, and write each answer into the Proposal as a decided
rule. Never settle one yourself, and never file an issue that leaves one to the implementer.

Write the title and body in `target.language` and `target.body_format`. The title names the owning skill or
instruction and the gap in one line. The body has these sections, in this order:

1. Summary
2. Observations
3. Gap in current rules, or "Why no existing skill covers it" for a new-skill proposal
4. Proposal: one numbered item per gap, each rule written as "Under the condition that X, do Y", as a decision
   test that also handles cases the incident did not show; keep a rule's exceptions inside its own item, and add no
   item that no gap needs
5. Acceptance criteria: numbered eval cases
6. Evidence

Before drafting, when the proposal relies on another issue or another plugin's release, shares a file with another
open issue's proposal, assigns a new file name, number, or identifier, or states a fact that can change before
implementation, read [implementable body](references/implementable-body.md).

Check each Proposal rule before writing it:

- Under the condition that a rule is drawn from the session's case, test it against at least one different case.
  Under the condition that it holds only for the prompting case, drop it or restate the principle behind it.
  Never copy the case's phrasing, order, values, or names into a rule.
- Under the condition that a rule governs writing, state the result the reader must be able to tell, not a format,
  label, or fixed order. Write one example sentence under the rule for a different case; under the condition that
  it reads awkwardly, revise the rule or drop it.

Check each acceptance criterion the same way:

- Under the condition that its verdict would depend on a model's judgment that can differ between runs, such as
  "zero reviewer findings", restate it as a check on a seeded input: what the output must no longer contain and what
  it must still contain.
- Under the condition that the user states an acceptance rule, write it as stated.

Use the format's own headings: `##` in Markdown, `h2.` in Jira wiki markup, and a plain heading line followed by a
blank line in plain text; for `html`, follow the declaration options.

Tags depend on `target.label_mode`. For `pick`, pick the one label from `target.labels` that fits; add none when
the list is empty. For `template`, expand the tags as the declaration options say.

Apply these content rules to every draft:

- Never include a secret, credential, token, personal data, local absolute path, home folder, or user name.
- Leave out every sentence that the content-rules file excludes.
- Under the condition that `target.public` is false, include every other detail that helps a coding agent do the
  work, after reading [private tracker detail](references/private-tracker.md).
- Under the condition that `target.public` is true, read [public tracker detail](references/public-tracker.md)
  before drafting and apply it.

Map each listed requirement from step 2 to the draft text that carries it. File only when every requirement maps; the
final report names that text for each.

### 7. Gate and file

- Under the condition that `preview_required` is true, show the target, title, label or tags, and the exact body in
  a code block. Write only after the user approves that text in a later message. When the text changes after
  approval, show it again and wait for a new approval.
- Under the condition that `preview_required` is false, naming the skill authorizes the single create. File
  without a preview step.
- Under the condition that the request files or rewrites one or more issues whose proposals change behavior, a public
  contract, or several components, read [independent model validation](../../instructions/independent-model-validation.md)
  before the first write, and run its one pass over all those bodies together as the complete draft, with the owning
  files as evidence. Sort and apply its findings once as that file says, finish the independent text review that
  [shared text](../../instructions/shared-text.md) requires for an issue body, then write. When the review cannot run, write anyway and report that it
  did not run, as that file says for an unavailable reviewer.
- Under the condition that `target.public` is true, read [public leak check](references/public-leak-check.md) before
  any write to the tracker, whether a create, an edit, or a comment; it can stop the write.

On GitHub, pass the body on stdin so no local path reaches the command line:

```text
gh issue create --repo <location> --title "<title>" --label "<label>" --body-file - <<'EOF'
<body>
EOF
```

On another tracker, create the issue with the path the declaration options choose, at the declared location only.

### 8. Verify

Read the created issue back and confirm its title, every tag, and section order. On GitHub, run
`gh issue view <number> --repo <location> --json number,title,labels,body,url`, and fetch the rendered body with
`gh api repos/<location>/issues/<number> -H "Accept: application/vnd.github.html+json" --jq .body_html`. The
rendered body must show no raw markup, such as a literal `##`, `**`, or `\n`. On another tracker, read it back with
the same path, and for `html` also run the declaration options' rendered check. On a public tracker, search the
Proposal and Acceptance criteria for the case's identifiers again.

When a check fails, fix what this skill wrote directly, following [update in place](references/update-in-place.md).
When a check cannot run, report it as unverified.

### 9. Show the preview

After the write, show the user a preview in the user's conversation language: concise and easy to read, yet with the
issue link and every key point present and unambiguous. Each Proposal rule and each Acceptance criterion appears;
none is summarized away.

Under the condition that the user asks for a change after the preview, update what this skill wrote directly,
following [update in place](references/update-in-place.md).

## Final report

Write in the user's language: the issue number and link, or the shown draft and why nothing was filed; the duplicate
search result; the verification result; for each requirement, the draft text that carries it; and each left-out item,
labeled as a one-off workaround, a tool defect, or a taste difference.
