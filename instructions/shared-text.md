# Shared text

Read this before writing or rewriting text that people read to grasp the work, and before writing Markdown whose
newlines are shown as line breaks. Each section names when it applies.

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
