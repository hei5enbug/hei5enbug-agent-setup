# Shared text

Read this before writing or rewriting text that people read to grasp the work, and before writing Markdown whose
newlines are shown as line breaks. Each section names when it applies.

## Cut and completeness passes

Apply this section to every text a person reads to grasp the work: a reply or final report to the user, a repository
document, an issue or ticket body, a comment, a review reply, a commit message, a chat message, and a pull request
description. When you write or update one, run both passes over the whole text, not only the changed part.

1. Cut pass: delete each sentence or link whose removal loses no fact the reader needs to decide or act. This covers a
   sentence that restates a linked source, an adjacent table or figure, another section, or a diff the reader sees
   with the text; a list of names such a diff shows; the reason behind a check item; a statement that something does
   not change, unless a reader would otherwise act wrongly; and a link whose target another listed link already
   covers. Merge items of one kind into one line.
2. Completeness pass: compare the text with the request and its sources. Restore every decision, condition,
   prerequisite, order, and completion criterion the reader needs, and rewrite every sentence with two readings.
3. When the destination has a length budget and the text exceeds it, cut by the first pass. Keep the text over budget
   only when the independent review below confirms each fact that cutting would lose.
4. When the destination's writing rules live in a team-shared document or repository, change them there and share
   the change instead of overriding them in a plugin.

## Independent text review

Before posting text to an external system, writing a file another person reads, or sending a final report, run this
after the passes above. A final report is the reply that ends a task by reporting its result, not a short answer or a
question. Never count a check you record about your own draft as this review.

```text
python3 <Source directory>/scripts/text_review.py review --kind <kind> --draft <file> --rules <file>... --source <file>...
```

- `--kind` is `pr-description`, `review-reply`, `issue-body`, `ticket-comment`, `commit-message`, `chat-message`,
  `shared-document`, `final-report`, or `other`. Pass the destination's writing rules with `--rules`, the request,
  diff, or ticket the text reports on with `--source`, the length budget with `--budget <characters>`, and
  `--no-ticket-keys` when the destination's rules forbid a ticket key.
- It first checks the patterns the text alone decides and stops on them; fix each finding. It then has two reviewers
  with no conversation context review the draft at once against only the rules and sources you passed.
- Exit 0: post. Exit 1: apply each finding to the whole text and run it again. To keep a flagged sentence, pass your
  reason with `--note` and let the next run judge it. Post only after a run returns no findings.
- After three runs that still return findings, post nothing, show the user the remaining findings, and ask. Send a
  final report as revised instead, with no line about the review.
- Exit 3 means the reviewer gave no verdict. Say that the review did not run, and ask before posting externally.

## Line breaks

- In a GitHub issue, pull request, or comment body, and in any other target that shows a newline as a line break,
  write each paragraph and each list item on one source line instead of wrapping it at a column. This holds for text
  written for agents too.
- In a Markdown document that will be published to Confluence, or whose project requires one source line per
  rendered line:
  - Keep consecutive sentences on one topic in one paragraph, and put a blank line only where the topic changes.
    Never leave a run of one-sentence paragraphs on one topic.
  - When the paragraph needs more than one line, end each line inside it with `<br>` after a sentence where the
    meaning pauses, so a line holds one sentence or two closely connected ones. Never break inside a sentence.
  - Write three or more items of the same kind as a lead sentence and a list.
  - Make a one-sentence paragraph that only introduces the next table or figure, and continues the previous
    paragraph's topic, the last line of that paragraph.
- Before posting or finishing such text, run `python3 <Source directory>/scripts/markdown_line_breaks.py FILE` on
  it, adding `--max-chars 0` for a GitHub body. When the workflow writes no local file, pass the text on standard
  input with `-` as FILE. Fix every finding.

## Readable shared text

Apply this section to summaries, including one the user asks for in a reply, documents shared with colleagues,
Jira issue bodies and comments, and pull request descriptions. Text written for coding agents, such as an issue
body that `skill-issue-creator` writes, follows its own rules instead.

- In Korean, write what an English term from the agent's instructions means in context instead of its literal
  translation, such as 규칙, 응답 형식, or 정해 둔 동작 for "contract" instead of 계약. Keep the English term only as a
  literal identifier.
- Leave out a number that does not change how the reader understands a decision or rule. Show a needed number in a
  table that compares it with its counterpart or breaks down a total, never in a list of numbers inside a sentence.
  Rule constants such as thresholds, and values an example needs, stay in prose. For a check, state what it verified,
  such as the behavior and the condition, instead of how many tests ran.
- When an adjacent figure or table already shows a fact, keep the figure or table and delete the sentence that
  restates it. Keep one sentence before it that says what it shows, and after it add only facts it does not show.
- In a summary of more detailed sources, keep the decisions, their reasons, and one representative example per
  section. Leave full lists, per-item tables, and implementation details to the detailed source. In a table cell,
  name only the items the summary discusses, joined with a separator instead of a list.
- After shortening or rewriting existing text, compare the new version with the previous one and restore every
  dropped condition, exception, scope, or decision timing that the reader needs. Give an independent reviewer of that
  comparison both versions, not a summary of the changes.
