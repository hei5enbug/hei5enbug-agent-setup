# Recommendation Rules

Rules for deciding whether a request starts `skill-issue-creator`, and for suggesting it in one line when the user has
not named it.

## Plain requests

Under the condition that the user asks in plain words to file, add, or change an issue about a plugin's skill or
instruction, start the skill at once, as if it were named: show no line first. Under the condition that a message only
mentions a tracker, an issue, or a plugin, such as a question about where issues go or how many are open, start nothing.
Without such a request the skill never starts on its own.

## When to show the line

Show one only when all of these hold:

- No work remains in the session.
- The user asked for a change to a result that a skill or instruction produced, or asked to turn a workflow finished in
  this session into a skill or an issue.
- At least one correction counts, as "Which corrections count" decides.
- `scripts/find_tracker.py` run on the owning file returns `declared` with `target.recommend` true. Run the script
  before showing the line.

Otherwise show no line. A correction while work remains, a one-off workaround, a tool defect, a taste difference,
a session review, and a question about the skill never earn a line.

## Which corrections count

At the end of the work, test each correction the user made to such a result: would the same mistake recur in a
different case unless the instructions of the plugin that owns the skill change?

- Under the condition that it would, it counts. It counts also when the agent already saved the correction to its own
  memory, because a memory note does not change the plugin's instructions for any other session.
- Under the condition that it holds only for that case, such as one ticket or one document, it earns no line. Name it
  in the same message, before the line, as left out, with the reason.
- Counted corrections that share one owning file and one topic are one issue, as in step 1 of the skill; the line
  states the number of issues.

Illustration, not a complete list: a correction "write dates in ISO form" holds for any report, so it counts; a
correction "this report's total should exclude the March invoice" holds only for that report, so it is left out.

## What the line says

- It is the last line of the message, in its own paragraph after any analysis, in the response language, and it is
  one question.
- It says in plain words what would be filed; where, which is a public repository anyone can read when
  `target.public` is true and otherwise the plugin's private tracker; what approving does, which is to file at
  once and then show a short preview when `target.preview_required` is false and otherwise to show the full draft
  first; and how to answer.
- With more than one issue, it states the number of issues.
- It uses no unexplained internal term, such as a skill name, "gap", "target", "label", or "trigger".

## After the line

- File nothing in that turn. Start only after the user approves in a later message. That approval counts as
  invoking the skill, once for each issue counted. Silence or an unrelated reply is not approval.
- When the user names the skill or makes a plain request, start at once without the line.

## Examples

English, private tracker, files at once:

> Should I file this as an issue in the team's private tracker so this mistake stops repeating? If you approve, I will
> file it right away and then show you a short summary; reply yes to go ahead or no to skip.

Korean, public repository, draft first:

> 이 문제를 누구나 읽을 수 있는 공개 저장소에 이슈 1건으로 올려 둘까요? 승인하시면 먼저 전체 초안을 보여 드리고,
> 확인해 주신 뒤에 올립니다. 올리려면 "네", 건너뛰려면 "아니요"라고 답해 주세요.
