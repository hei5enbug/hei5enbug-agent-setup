---
name: docs-rewrite
description: >-
  Rewrite existing text so it reads naturally while its meaning stays exactly the same. Use when a
  document, message, review comment, commit message, PR description, chat reply, or file is supplied
  and the request is to polish, tidy, smooth, restructure for readability, fix awkward wording, or
  remove AI-sounding and translated-sounding Korean, including "다듬어줘", "자연스럽게 고쳐줘",
  "읽기 쉽게", "가독성 개선", "문장 정리", "말이 이상해", "AI 티 제거", "사람이 쓴 것처럼 윤문",
  "번역투 제거", "ChatGPT 문체 수정", "한국어 휴머나이징", "장르·강도 조정", "polish this",
  "make it read better", "reword". Also use on an agent draft before it is posted or committed. Do
  not use to write new text, to translate, to summarize, to expand with added explanation, or to
  check whether the content is correct, and never promise that a detector will be defeated.
metadata:
  version: "1.0.0"
compatibility: >-
  Works in any host that can read and emit Unicode text. The bundled reference and eval cases are
  optional local resources. Rewriting a repository file additionally requires filesystem access.
---

# Docs Rewrite

Change how text reads. Never change what it says.

## Authority and scope

Use this English `SKILL.md` as the only executable instruction source. `SKILL.ko.md` is a
non-authoritative Korean translation for human readers; never load it during execution. Korean text
in this file, `references/patterns.md`, and `evals/evals.json` is target-language data, not
instruction. Apply this skill after higher-priority instructions.

| Applies to | Does not apply to |
|---|---|
| Text the user supplies in the conversation | Writing new text from a topic or an outline |
| An agent draft before posting: review comment, commit message, PR description, chat reply | Translating between languages |
| A document file or code comment at a given path | Summarizing, condensing, or expanding content |
| Text the user calls awkward, unclear, machine-written, or hard to read | Judging whether the content is factually correct |

When the request mixes rewriting with one of the excluded tasks, rewrite first, then say plainly
that the other part was not done and why.

If the user asks to bypass an AI detector, improve the prose normally. Never guarantee or claim that
any detector will be defeated.

## Invariant elements

Each element below carries meaning. Reproduce every one of them in the output with the same value.
This table is the reason the skill exists: an ordinary rewrite silently shifts these. No option,
mode, or strength in this file ever relaxes a row of it.

| Element | What must survive unchanged |
|---|---|
| Quantity | Every number, unit, range, date, and level of precision. Never round, approximate, or add a hedge such as "약". |
| Condition and exception | Every conditional clause, exception, precondition, and caveat, with the same count and the same thing it applies to. |
| Negation and scope | Negation, and quantifiers such as 모두, 일부, 전혀, 최소, 최대. Do not convert a double negative into a positive. |
| Certainty | The grade of assertion, guess, possibility, or hearsay. Do not raise "~인 것 같다" to a flat statement or lower a flat statement to a guess. |
| Requirement strength | The difference between must, should, may, and must not. Keep a request a request and a suggestion a suggestion. |
| Actor and direction | Who acts, on what, in which direction. When turning a passive into an active, do not invent an actor the source does not name. |
| Tense and aspect | Completed, ongoing, and planned. |
| Literal strings | Proper nouns, product and model names, code identifiers, file paths, URLs, commands, error text, versions, citations, and quoted passages, character for character. |
| Speech act | Whether the sentence asks, requests, reports, or promises. |
| Severity | Severity labels, blocking status, and priority markers. |
| Genre and register | Genre, audience, formality level, point of view, and existing terminology. |
| Open question | Anything the source leaves unanswered stays unanswered in the output. |

## Forbidden changes

- Adding a fact, reason, cause, example, metaphor, transition, or conclusion the source does not contain.
- Removing a fact the source contains. Removing repetition is allowed only under "Allowed changes".
- Resolving an ambiguous phrase by picking one reading.
- Making a conclusion stronger or weaker than the source makes it.
- Naming a cause the source only hints at, or presenting a guess as a finding.
- Shifting tone across the polite, neutral, and blunt boundary.
- Making formal text casual merely to make it sound less machine-written.
- Making the prose more literary than the source, or replacing one formula with another.

When a passage cannot be improved without breaking one of these rules, leave it as it is and report
it. Leaving awkward text intact is the correct outcome; changing its meaning is not.

## Allowed changes

- Splitting, joining, and reordering sentences.
- Removing translationese, stacked passives, and noun-heavy phrasing, for example
  "확인을 진행하다" to "확인하다", "보여지다" to "보인다".
- Fixing particles, endings, spacing, and spelling.
- Deleting a repetition only when two passages state exactly the same thing. If any part of the
  meaning differs, keep both.
- Splitting paragraphs, and moving the conclusion ahead of its supporting detail.
- Converting to a list when the source holds two or more independent matters.
- Converting to a table when three or more items share three or more common comparison dimensions.
- Marking an identifier, path, or command as inline code without altering its characters.

## Korean pattern layer

When the source is Korean, also repair the AI-like and translated-sounding patterns catalogued in
`references/patterns.md`. Read that file and inspect only the patterns relevant to this source.
Rewrite detected spans locally; never run a global search and replace. This layer changes wording
only, so every "Invariant elements" row still holds.

Infer omitted options from the source. An explicit user choice always wins.

| Option | Values | Effect |
|---|---|---|
| `장르` | `칼럼`, `리포트`, `블로그`, `공적` | Target genre. Changing genre needs an explicit request, because "Invariant elements" protects genre and register. |
| `강도` | `보수`, `기본`, `적극` | Edit breadth. Default `기본`. |
| `최소심각도` | `S1`, `S2`, `S3` | Eligible patterns. Default `S2`. |

Severity runs `S1` for obvious local defects such as double passives and empty canned phrases, `S2`
for repeated or context-dependent patterns that make the prose mechanical, and `S3` for subtle
preferences worth changing only in aggressive rewriting. A threshold includes stronger levels, so
`S2` covers `S1` and `S2`.

Use `보수` for high-confidence local edits only, `기본` for relevant `S1` and `S2` patterns, and
`적극` for broader rhythm and structure changes. If the text is already natural, leave it unchanged
or make only a few clear edits. Never rewrite merely to demonstrate activity.

## Structure guards

Format conversion is allowed, so it needs limits. Over-structuring a short message hurts
readability as much as leaving it tangled.

- Do not build a list or paragraph structure when the source is three sentences or fewer and
  covers a single matter.
- Do not split one matter across several list items.
- Do not invent a heading. When the source already has sections, keep their names.
- Produce one level of structure only. Keep nesting only when the source already nests.
- Keep the source's format family: plain text stays plain text, Markdown stays Markdown.
- Preserve useful Markdown structure, list semantics, and paragraph boundaries.

## Ambiguity

Poorly written text usually has passages that can be read two ways. Choosing one reading changes
the meaning, so treat ambiguity as content to preserve.

1. Mark every passage that supports more than one reading.
2. Choose wording that keeps all of those readings open. When no natural wording keeps them open,
   keep the source wording for that passage.
3. List the passage under "확인 필요" with the readings it allows. Do not pick one.

## Workflow

1. Identify the genre, audience, register, stance, and formatting role.
2. List the source's claims in order. For each claim, note which invariant elements it carries.
   This list is working material, not output.
3. Mark ambiguous passages and protected content.
4. Rewrite within "Allowed changes" and "Structure guards", applying the Korean pattern layer when
   the source is Korean.
5. Verify by contrast. List the claims in the result and match them one to one against step 2.
   The counts must match, the order correspondence must hold, and every invariant value must be
   identical. Delete any claim that appeared. Restore any claim that disappeared.
6. Check naturalness, rhythm, register, and over-editing. Roll back any edit that only trades one
   formula for another.
7. Report the result, what changed and why, and what was left alone.

When edits affect roughly more than one-third of the prose, run an extra fidelity review. When more
than half of the sentences were rewritten without an aggressive or genre-change request, roll back
the broad edits and retry locally. Treat these as qualitative safeguards unless a diff was measured.

## Strict review

Run strict review when the user requests `--strict` or `정밀 모드`, or when the input exceeds 8,000
characters. Announce an automatic promotion in one short progress update.

Perform it in the current agent, without named sub-agents or host-specific orchestration:

1. Complete the normal workflow section by section while retaining whole-document context.
2. Run a separate fidelity pass against the invariant table, protected strings, and causal links.
3. Run a separate naturalness pass for remaining eligible patterns and over-editing.
4. Retry only the affected spans. Stop after two retries and report any unresolved span plainly.

Strict review changes validation depth, not the requested tone or rewrite strength.

## Follow-up requests

Apply follow-ups to the latest source or result available in the conversation.

| User signal | Action |
|---|---|
| `특정 카테고리만 다시` | Touch only that pattern category and preserve every other span. |
| `이 문단만` | Rewrite only the named or quoted paragraph. |
| `2차 윤문` | Review the latest result again and edit only remaining problems. |
| `윤문 강도 조정` | Apply the new strength without reopening unrelated content. |
| `장르 바꿔서` | Change the genre treatment while preserving facts and stance. |

If the referenced text is no longer available, ask the user to provide it again.

## Output

Use this structure:

```markdown
<the rewritten text, in the source's language and format>

**주요 변경**
- <what changed and why, three to six lines>

**확인 필요**
- <passage left alone because it reads two ways, with the readings it allows>
```

- Keep the source's language. Never translate.
- Omit "확인 필요" when nothing was ambiguous.
- When the user asks for the rewritten text only, output that text alone.
- If no rewrite is needed, say so briefly and return the source unchanged.
- For an agent draft, keep posting conventions literal: mentions, identity IDs, severity prefixes,
  signatures, and commit type prefixes.
- For a repository file, show the change and get approval before writing. Rewrite prose and
  comments only; leave code, commands, and configuration values untouched.
- Do not create run directories, reports, or metrics files unless the user asks for file output.
- Do not fabricate a change rate, grade, detector score, or pass count. Report a numeric metric
  only when it was actually measured.

## Examples

Korean source, review comment, two independent matters, so a list is allowed:

```text
원문:
성능이 좀 안좋아진거 같은데 아마 N+1 때문일수도 있을것 같습니다 그리고 로그가
너무 많이 찍히는것도 있고 일단 확인해보시면 좋을것 같아요

결과:
다음을 확인해 보시면 좋겠습니다.

- 성능이 나빠진 것 같습니다. N+1 때문일 수도 있습니다.
- 로그가 지나치게 많이 남습니다.
```

The guess stays a guess, and the suggestion stays a suggestion rather than becoming a request.

A rewrite that breaks the rules, and the correct one:

```text
원문:
캐시 만료가 5분인데 좀 짧은 것 같습니다

잘못된 결과:
캐시 만료 시간이 5분으로 너무 짧으니 늘려야 합니다.

올바른 결과:
캐시 만료 시간이 5분인데, 조금 짧은 것 같습니다.
```

The wrong version raises a guess to a statement and adds an instruction the source never gives.

Ambiguity kept open:

```text
원문:
값이 없으면 기본값을 쓰는데 그게 맞는지 모르겠네요

결과:
값이 없으면 기본값을 씁니다. 그게 맞는지 모르겠습니다.

확인 필요:
- "그게"가 기본값을 쓰는 동작을 가리키는지, 기본값 자체를 가리키는지 원문만으로는
  정해지지 않아 그대로 두었습니다.
```

## Completion gate

- [ ] The claim lists from step 2 and step 5 match one to one, with no addition and no loss.
- [ ] Every "Invariant elements" row holds the same value in the source and the result.
- [ ] No "Forbidden changes" item occurred.
- [ ] Every structural change satisfies "Structure guards".
- [ ] Every ambiguous passage is either kept open or reported under "확인 필요".
- [ ] The language, genre, register, and format family match the source.
- [ ] No detector claim, fabricated metric, or unrequested file was produced.
- [ ] A repository file was written only after the change was shown and approved.

## Runtime resource

- `references/patterns.md`: Korean pattern signals, treatments, genre rules, and final checks.
