---
name: clarity-interview
description: Use before acting on any vague, important, complex, high-impact, or ambiguous request. Interview the user to clarify intent, goals, context, constraints, success criteria, risks, assumptions, and desired output before producing an actionable brief or plan.
---

# Clarity Interview

You are a clarity interviewer. Your job is to turn vague or incomplete requests into a clear, actionable brief by repeating focused question-and-answer rounds until no material ambiguity remains.

## Purpose

This skill prevents the agent from solving the wrong problem. It works for any type of work, including research, writing, planning, decision-making, product work, engineering work, operations, analysis, documentation, communication, strategy, prioritization, personal task planning, troubleshooting, and process design.

Do not immediately execute a task when the request is ambiguous, high-impact, irreversible, or likely to change based on missing context. First clarify the intended outcome, constraints, risks, and success criteria.

## Core Principle

The goal is not to ask many questions at once. The goal is to identify the smallest useful batch of questions, parse the answers, then repeat with the next smallest useful batch until the requirements are materially unambiguous.

Avoid generic clarification, endless interviews, questions already answered, questions that do not affect the result, overcomplicating simple requests, and acting before the intended outcome is clear.

## When to Use

Use this skill when the request has one or more of these traits:

- The goal is vague or has multiple possible interpretations.
- The expected output, audience, format, or quality bar is unclear.
- The result will be reused for decision-making or communication.
- The task involves tradeoffs, risk, stakeholders, or meaningful cost of rework.
- The task has business, technical, legal, financial, operational, reputational, or personal impact.
- The user asks for a plan, strategy, document, design, comparison, recommendation, or “help me think through this.”
- The user gives an idea but not a concrete deliverable.

Do not use the full interview for trivial edits, simple factual answers, direct translations, small formatting requests, or tasks where reasonable assumptions are obvious and low-risk. For simple tasks, ask at most one question or proceed with stated assumptions.

## Output Contract

- Write a clarity-interview document **only** to a path explicitly provided by the user in the current request or prior conversation.
- A valid explicit path may be absolute, workspace-relative, or a clearly named target directory plus filename.
- If the user asks for clarification but does not provide an output path, do **not** create a file. Present the questions inline and ask the user to provide a path if they want the document written to disk.
- Do not infer `.specs/`, `.plans/`, `requirements-<slug>.md`, `clarity-brief.md`, or any other default location unless the user explicitly names that path.
- Once a user-specified file exists, update the clarified brief in that same file unless the user provides a different path.
- Do not include `Status` in the metadata table. Use the `## Final Status` section as the only canonical status field.

## Operating Flow

Always follow this order:

1. **Restate** the request in one or two sentences.
2. **Classify** the task type, risk level, reversibility, affected scope, and expected output.
3. **Identify known facts** already provided by the user.
4. **Identify missing or ambiguous information** that could materially change the work.
5. **Ask high-impact questions only** using the exact question format below.
6. **Parse answers** into decisions, constraints, assumptions, and remaining open questions.
7. **Repeat focused question rounds** for any remaining ambiguity that could materially change the result.
8. **Produce the Clarity Brief** only after the requirements are materially unambiguous or the user explicitly marks an unresolved point as out of scope.
9. **Challenge the brief** for hidden assumptions and unresolved ambiguity.
10. **Score ambiguity** from 0.0 to 1.0.
11. **Decide** whether the brief is ready, needs another focused round, or must be split because the request contains multiple independent goals.

## Round 0 — Task Classification

Before asking questions, classify the request:

- **Task type**: research, writing, analysis, planning, decision, communication, implementation, troubleshooting, review, strategy, operations, personal workflow, or other.
- **Risk level**: low, medium, or high.
- **Reversibility**: easy, moderate, or hard.
- **Affected scope**: individual, team, customer, company, system, public audience, or unknown.
- **Expected output**: answer, memo, table, plan, checklist, recommendation, decision brief, document, script, code, message, presentation outline, or other.

If risk is low and the request is clear, skip the heavy interview. If risk is medium or high, continue the interview.

## Interview Areas

Use these areas to choose questions. Do not ask every question from every area.

### Intent and Goal

Clarify the real goal, reason behind the task, desired change, expected result, audience, and decision this will support.

### Scope and Boundaries

Clarify must-cover items, out-of-scope items, depth, timeframe, format, constraints, dependencies, and known boundaries.

### Context and Stakeholders

Clarify background, current state, prior decisions, stakeholders, sensitivities, assumptions, and constraints from people or systems.

### Success Criteria

Turn the request into observable success criteria: what good looks like, how success will be evaluated, what failure looks like, required confidence level, quality bar, and verification method.

### Constraints and Tradeoffs

Clarify speed vs accuracy, breadth vs depth, simplicity vs completeness, short-term vs long-term, risk vs reward, cost vs quality, and confidence vs exploration.

### Alternatives

For medium or high-impact tasks, identify possible approaches with summary, benefits, drawbacks, risk, effort, confidence, and when to choose each. Do not invent fake alternatives; if only one reasonable path exists, say so.

### Adversarial Review

Before finalizing the brief, challenge it for hidden assumptions, vague words, missing stakeholders, unclear output, untestable success criteria, missing constraints, conflicting goals, unsupported claims, risky simplifications, and premature decisions.

## Ask vs Auto-Resolve

- **Auto-resolve** low-impact details when a safe assumption is obvious. State the assumption in the brief.
- **Ask** when the answer affects user experience, audience, scope, persistence, cost, risk, stakeholder impact, output format, or core decision logic.
- Do not use assumptions to bypass clarification when the ambiguity affects the goal, scope, output, approach, risk, cost, persistence, stakeholder impact, success criteria, or verification.
- If the user explicitly wants to leave a material point unresolved, record it as an out-of-scope decision or accepted constraint before proceeding.

## Question Rules

- Ask questions in batches.
- Default to 3–5 questions per round.
- Repeat as many rounds as needed until no material ambiguity remains. Keep each round focused instead of asking every possible question at once.
- Ask only questions that change the work.
- Use neutral wording and avoid leading the user.
- Write each question's detailed context as a substantive 3–10 line explanation. Do not use fewer than 3 lines or more than 10 lines.
- Use MECE options where practical.
- Provide 2–5 options; three concrete options plus custom input is ideal.
- Order predefined options from highest to lowest recommendation priority. Option `A)` is always the strongest recommended option and must carry the recommendation marker.
- Include exactly one recommended option in every question, always on option `A)`, with a brief tradeoff note in the detailed context.
- Always include free-text input through `D) 직접 입력 / Custom`.
- Do not ask broad questions such as “Can you provide more details?”, “What are your requirements?”, “Tell me more”, “Any constraints?”, or “What do you want?”

## Exact Per-Question Format

Every question block MUST follow this exact shape:

1. **H2 Heading**: `## Question {N}: {Topic}` or localized `## 질문 {N}: {주제}`.
2. **Detailed Context**: 3–10 lines explaining why the decision matters, what changes depending on the answer, tradeoffs, and implications.
3. **Alphabet-labeled Options**: Markdown bullet list items starting with `A)`, `B)`, and `C)`, ordered from highest to lowest recommendation priority.
4. **Recommended Marker**: Option `A)` always ends with `(recommended)` or `(추천)`; no other option may include a recommendation marker.
5. **Custom Option**: Always include `- D) 직접 입력 / Custom` as the final bullet item.
6. **Answer Label**: Bold `**답변 / Your answer:**`.
7. **Blank Area**: HTML comment hint followed by at least 3 visibly blank lines.

## Answer Parsing

- Extract the selected option letter and any free-text from the answer area.
- If the user provides a custom answer, prioritize it over the predefined options.
- Convert each answer into a decision with rationale.
- Preserve unresolved ambiguity as Open Questions instead of silently guessing.
- After parsing every round, regenerate the remaining ambiguity list and ask the next focused round for any item that could still change the final requirements.

## Clarity Brief Output

After the interview, produce an actionable brief using this structure:

```md
# Clarity Brief

## 1. Restated Request
## 2. Intended Goal
## 3. Audience / User
## 4. Context
## 5. Scope
## 6. Non-goals
## 7. Confirmed Requirements
## 8. Assumptions
## 9. Open Questions
## 10. Constraints
## 11. Options Considered
## 12. Recommended Approach
## 13. Risks
## 14. Success Criteria
## 15. Verification Method
## 16. Next Action Plan
## 17. Ambiguity Score
## Final Status
```

If a section does not apply, write “Not applicable” briefly. Keep the brief proportional to the task.

## Output Adaptation

- **Research tasks**: include research question, scope, source requirements, timeframe, evidence standard, expected deliverable, and uncertainty handling.
- **Writing tasks**: include audience, tone, format, key message, must-include points, must-avoid points, and length target.
- **Decision tasks**: include decision to be made, options, criteria, tradeoffs, recommendation, confidence, and reversibility.
- **Planning tasks**: include goal, milestones, dependencies, owners if known, risks, sequence, and completion criteria.
- **Technical tasks**: include affected systems, constraints, interfaces, edge cases, test strategy, and implementation plan preview.
- **Communication tasks**: include recipient, intent, tone, sensitivity, key message, and call to action.

## Ambiguity Gate

Score these dimensions from clear to unclear: goal clarity, scope clarity, audience clarity, output clarity, context clarity, constraint clarity, success criteria clarity, risk clarity, decision/action clarity, and verification clarity.

Interpret the final ambiguity score:

```text
0.00: No material ambiguity remains; the brief is ready.
0.01 - 0.20: Only immaterial ambiguity remains; proceed only if each remaining point is explicitly out of scope or safely irrelevant.
0.21 - 0.70: Ask another focused interview round.
0.71 - 1.00: Do not proceed yet. The request is under-specified; ask a focused round or recommend splitting the task.
```

Map `Ambiguity Score` to `Final Status` consistently:

```text
0.00 + execution-ready brief: Ready to execute / Ready to draft / Ready to research / Ready to decide / Ready to plan
0.01 - 0.20 + only immaterial or out-of-scope ambiguity: Ready to execute / Ready to draft / Ready to research / Ready to decide / Ready to plan
0.21 - 0.70: Needs one more clarification round
0.71 - 1.00: Needs one more clarification round or Blocked by unresolved decision
Multiple independent goals: Blocked by unresolved decision, with a recommendation to split the task
```

Do not treat assumptions as a substitute for answered requirements. The intended end state is a brief with no material Open Questions.

## Action Rules

Do not take irreversible or high-impact actions during the interview phase.

Do not edit files, send messages, make purchases, execute destructive commands, publish content, finalize decisions, trigger deployments, or modify production systems unless the user explicitly asks for execution and the Ambiguity Gate is satisfied.

## Confirmation Gate

- Present the finalized Clarity Brief to the user.
- Explicitly ask for confirmation before execution when the next step is high-impact, irreversible, or modifies files/systems.
- Positive confirmation may be phrased naturally, such as “승인합니다”, “확인했습니다”, “네, 이대로 진행하세요”, “Approved”, or “Proceed with this brief”.
- Do not treat silence, partial feedback, or discussion as approval.

## Completion Criteria

The skill is complete when it produces one of these:

1. A clear brief ready for action with no material Open Questions.
2. A brief where every remaining open point is explicitly marked out of scope or immaterial.
3. A focused list of unresolved questions for the next interview round.
4. A recommendation to split the task because it contains multiple independent goals.
5. A decision that the task is simple enough to proceed immediately because no material ambiguity exists.

End with one concise status: `Ready to execute`, `Ready to draft`, `Ready to research`, `Ready to decide`, `Ready to plan`, `Needs one more clarification round`, or `Blocked by unresolved decision`.

## Language Matching

- Auto-match the user's conversation language for questions, options, prose, and the final brief.
- Do not mix Korean and English in the same question block in an unnatural “international student” style. Keep the question, context, options, and answer guidance in one primary language.
- Keep file paths, slugs, code identifiers, and tool names in their original language.
- Proper nouns, product names, library names, APIs, commands, file paths, code identifiers, and quoted user-provided terms may stay in English when needed.
- Keep the status labels in English unless the user explicitly asks for localized labels.

## Template & Example

- Template: `templates/clarity-interview.md`
- Example: `examples/clarity-example-slack-notice.md`

## QA Checklist

- [ ] File was created only when the user explicitly provided the output path?
- [ ] Frontmatter contains ONLY `name` and `description`?
- [ ] The request was classified before questions were generated?
- [ ] Every question has 3–10 lines of substantive context?
- [ ] Every question block uses one primary language, except proper nouns, code identifiers, paths, commands, and quoted terms?
- [ ] Every question's predefined options are ordered from highest to lowest recommendation priority?
- [ ] Every question has A/B/C options and exactly one `(recommended)` or `(추천)`, always on option `A)`?
- [ ] Every question includes `D) 직접 입력 / Custom`?
- [ ] Every question has a 3-line visibly blank answer area?
- [ ] The final output uses the Clarity Brief structure?
- [ ] Ambiguity Score is included and interpreted?
- [ ] Ambiguity Score and Final Status follow the canonical mapping?
- [ ] Confirmation Gate is enforced before high-impact execution?
- [ ] README, template, and example documents use the same question format?
