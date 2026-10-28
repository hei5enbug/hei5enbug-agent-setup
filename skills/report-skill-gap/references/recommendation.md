# Recommendation Rules

Rules for suggesting `report-skill-gap` in one line when the user has not named it.

## When to show the line

Show one only when all of these hold:

- No work remains in the session.
- The user corrected a result the agent had already finished and the cause is a gap in a skill or instruction of
  one plugin, or the user asked to turn a workflow finished in this session into a skill or an issue.
- `scripts/find_tracker.py` run on the owning file returns `declared` with `target.recommend` true. Run the script
  before showing the line.

Otherwise show nothing. A correction while work remains, a one-off workaround, a tool defect, a taste difference,
a session review, and a question about the skill never earn a line.

## What the line says

- It is the last line of the message, in its own paragraph after any analysis, in the response language, and it is
  one question.
- It says in plain words what would be filed; where, which is a public repository anyone can read when
  `target.public` is true and otherwise the plugin's private tracker; what approving does, which is to file at
  once when `target.preview_required` is false and otherwise to show the full draft first; and how to answer.
- With more than one issue, it states the count.
- It uses no unexplained internal term, such as a skill name, "gap", "target", "label", or "trigger".

## After the line

- File nothing in that turn. Start only after the user approves in a later message. That approval counts as
  invoking the skill, once for each issue counted. Silence or an unrelated reply is not approval.
- When the user names the skill, start at once without the line.

## Examples

English, private tracker, files at once:

> Should I file this as an issue in the team's private tracker so this mistake stops repeating? If you approve, I will
> file it right away; reply yes to go ahead or no to skip.

Korean, public repository, draft first:

> 이 문제를 누구나 읽을 수 있는 공개 저장소에 이슈 1건으로 올려 둘까요? 승인하시면 먼저 전체 초안을 보여 드리고,
> 확인해 주신 뒤에 올립니다. 올리려면 "네", 건너뛰려면 "아니요"라고 답해 주세요.
