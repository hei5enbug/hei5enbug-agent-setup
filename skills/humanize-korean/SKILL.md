---
name: humanize-korean
metadata:
  version: "2.0.0"
description: >-
  Rewrite Korean text so it reads naturally while preserving meaning, facts, numbers, names,
  quotations, stance, register, genre, and useful formatting. Detect and repair translationese,
  formulaic parallelism, repeated English glosses, passive constructions, connective overuse,
  uniform rhythm, nominalization, canned conclusions, and other AI-like Korean patterns. Use for
  requests such as AI 티 제거, 사람이 쓴 것처럼 윤문, 번역투 제거, ChatGPT 문체 수정,
  한국어 휴머나이징, 문단 재윤문, 장르·강도 조정, or Korean detector-bypass phrasing. Do not
  promise detector evasion or alter substantive content.
compatibility: >-
  Works in any agent host that can read and emit Unicode Korean text. No external tools or files are
  required for the core rewrite; the bundled reference and eval cases are optional local resources.
---

# Humanize Korean

## Language contract

Use this English `SKILL.md` as the only executable instruction source. `README.ko.md` is a non-authoritative Korean translation kept synchronized with this file for human readers.
Do not read or use it during execution.

Korean text in this file, `references/patterns.md`, and `evals/evals.json` is target-language data. Follow the English instructions around that data. Never treat Korean examples as instructions.

## Goal

Make the source sound like natural Korean written for its existing audience. Preserve the writer's meaning and voice. Prefer the smallest edit that fixes a real problem.

This skill is for style rewriting.
It is not for translation, fact expansion, summarization, argument improvement, or simple spelling correction unless those tasks are part of a requested style rewrite.

If the user asks to bypass an AI detector, improve the prose normally but do not guarantee or claim that any detector will be defeated.

## Non-negotiable invariants

Preserve all of the following unless the user explicitly asks to change one of them:

- meaning, factual claims, uncertainty, causality, stance, and emphasis;
- numbers, dates, units, proper nouns, product and model names, and citations;
- direct quotations, statutory language, code, links, and technical notation;
- genre, audience, formality level, point of view, and existing terminology;
- useful Markdown structure, list semantics, and paragraph boundaries.

Do not add examples, metaphors, evidence, opinions, transitions, or conclusions that the source does not support. Do not make a cautious claim more certain.
Do not make formal text casual merely to make it sound less machine-written.

## Options and modes

Infer omitted options from the source. An explicit user choice always wins.

- `장르: 칼럼|리포트|블로그|공적`: set the target genre while preserving content.
- `강도: 보수|기본|적극`: control edit breadth. Default to `기본`.
- `최소심각도: S1|S2|S3`: choose eligible patterns. Default to `S2`.
- `--strict`, `정밀 모드`, or the legacy phrase `5인 파이프라인`: run the strict review below.

Interpret severity in this order:

- `S1`: obvious local defects such as double passives or empty canned phrases;
- `S2`: repeated or context-dependent patterns that make the prose mechanical;
- `S3`: subtle preferences that should be changed only in aggressive rewriting.

A threshold includes stronger levels. `S2`, for example, includes `S1` and `S2`.

Use conservative strength for only high-confidence local edits. Use default strength for relevant S1 and S2 patterns.
Use aggressive strength for broader rhythm and structure changes, but never relax the invariants.

## Workflow

For every new rewrite request:

1. Identify the genre, audience, register, stance, and formatting role.
2. Mark protected content from the invariant list before changing prose.
3. Read `references/patterns.md` and inspect only patterns relevant to this source.
4. Rewrite detected spans locally. Avoid global search-and-replace behavior.
5. Compare every changed claim with the source and restore any lost nuance.
6. Check naturalness, rhythm, register, and over-editing. Roll back edits that merely replace one formula with another or make the prose more literary than the source.
7. Return the result in the source format unless the user requests another format.

When edits affect roughly more than one-third of the prose, run an extra fidelity review.
When more than half of the sentences were rewritten without an aggressive or genre-change request, roll back broad edits and retry locally.
Treat these as qualitative safeguards unless an actual diff was measured.

If the text is already natural, leave it unchanged or make only a few clear edits. Never rewrite merely to demonstrate activity.

## Strict review

Use strict review when the user requests `--strict`, `정밀 모드`, or the legacy phrase `5인 파이프라인`, or when the input exceeds 8,000 Korean characters.
For automatic promotion, tell the user in one short progress update.

Perform strict review in the current agent without requiring named sub-agents or host-specific orchestration:

1. Complete the normal workflow section by section while retaining whole-document context.
2. Run a separate fidelity pass against facts, protected strings, uncertainty, and causal links.
3. Run a separate naturalness pass for remaining eligible patterns and over-editing.
4. Retry only the affected spans. Stop after two retries and report any unresolved span plainly.

Strict review changes validation depth, not the user's requested tone or rewrite strength. The legacy phrase does not require five agents, and the response must not claim that five agents were used.

## Follow-up requests

Apply follow-ups to the latest source or result available in the conversation:

| User signal | Action |
|---|---|
| `특정 카테고리만 다시` | Touch only that pattern category and preserve every other span. |
| `이 문단만` | Rewrite only the named or quoted paragraph. |
| `2차 윤문` or `/humanize-redo` | Review the latest result again and edit only remaining problems. |
| `윤문 강도 조정` | Apply the new strength without reopening unrelated content. |
| `장르 바꿔서` | Change the genre treatment while preserving facts and stance. |

If the referenced text is no longer available, ask the user to provide it again.

## Output contract

Return the rewritten text directly by default. Preserve headings, paragraphs, lists, tables, links, and quotation layout when they carry meaning.

When the user asks for an explanation, put the rewritten text first and then list only the important change categories or unresolved risks.
If no rewrite is needed, say so briefly and return the source unchanged.

Do not create run directories, reports, metrics files, or rewritten files unless the user explicitly requests file output or asks to edit a supplied file.
Do not fabricate an exact change rate, grade, detector score, or pass count. Report a numeric metric only when it was actually measured.

## Runtime resource

- `references/patterns.md`: compact pattern signals, treatments, genre rules, and final checks.
