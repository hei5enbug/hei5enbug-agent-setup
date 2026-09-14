# Korean technical design prose

For Korean design documents, judge accuracy, contract preservation, grammar, consistency, and naturalness
in that order. Do not disturb meaning, spelling, spacing, or register merely to sound natural.

## Writing principles

- Draft directly in Korean rather than translating an English draft. Translate only for a translation request.
- Unless the user specifies a style, use the formal Korean `한다` register for explanations and rules.
  Use one consistent imperative form for direct procedural instructions.
- Preserve code, identifiers, paths, commands, UI strings, proper nouns, and direct quotations exactly.
- Compare facts, dates, units, causality, negation, possibility, obligation, scope, and exceptions before and after.
- Follow standard Korean spelling and spacing. Do not introduce deliberate errors or irregularity.
- Exclude code blocks from Korean prose review. Review prose outside code and comments only when they are in scope.

## Subjects and predicates

- Use active voice when the actor is known and material. Use passive voice only when the actor is immaterial or unknown.
- A system or tool may be the subject when describing what it actually does.
- Omit a repeated subject when context is clear. Restate it when the subject changes or contrast and ownership matter.
- A sentence must remain valid when reduced to its subject and predicate.
  Replace an abstract noun that appears to act with the actual actor or state change.
- Keep one claim per sentence. A condition, action, and result may stay together when they form one rule.

## Terminology and wording

- Prefer the project glossary, contract names, official product names, and industry terms over simpler wording.
- Use an established loanword when no suitable Korean term exists or the Korean form is less familiar.
  Do not force a native-Korean replacement.
- Never treat a loanword and a native-Korean alternative as a global substitution pair. Choose each form
  from its context, audience, genre, established project usage, and natural collocation. A familiar loanword
  may be more natural than a technically possible native-Korean replacement.
- Define an abbreviation once only when repetition or searchability benefits.
- Do not combine a quantity expression with `들` unless an exact plural distinction is necessary.
- Replace `본`, `해당`, `이것`, and `그것` with the object name, or omit them when context is clear.
- Use evaluative words such as `중요한`, `효과적인`, `혁신적인`, and `강력한` only with a criterion or
  evidence.
- Expand stacked `-적` forms and abstract nouns, such as `전략적 함의`, when they obscure the actual meaning.
- Replace vague operation nouns such as `진행`, `수행`, `실시`, and `처리` with the concrete verb.

## Translationese assessment

Read the `A. Translationese` table in `../humanize-korean/references/patterns.md` and apply its signals.
Resolve the path from this skill directory. Never use an absolute path or host installation location.
If the file is absent, apply the remaining rules here and report that the signal list was unavailable.

Do not prohibit an expression from its string alone. Check its role in the sentence and change it only when
a more direct expression preserves the same meaning.

For design documents, these judgments override the signal list:

- Preserve a contract string that exists verbatim in code, configuration, or an interface even if it looks
  like translationese. Keep `되어진다` when it is a state name.
- Keep `할 수 있다` only for actual capability, permission, or possibility.
  State confirmed behavior and results directly.
- Keep `할 것이다` only for a prediction, intention, or plan.
  Use present tense for current contracts and confirmed behavior.
- Distinguish whether `X에 기반하여` denotes evidence, input, tool, or foundation.
- Keep `X를 위해` only when the purpose matters to the design decision.
  Reduce it when the purpose is obvious or the verb already expresses it.

Remove meta phrases such as `결론적으로`, `정리하면`, and `앞서 설명했듯이` when they add no
information.
Use a connective only when omitting it could obscure the logical relationship.
Do not vary sentence length, list length, or endings merely to look human-written.

## Punctuation and format

- Use a comma after a connective ending only when needed to clarify a long clause boundary.
  Do not separate subject and predicate with a comma.
- End a list introduction as a complete sentence. Do not overuse colons except for time, ratios, keys and values,
  or code syntax.
- Use commas for independent alternatives. Use a middle dot only for shared elements or one grouped expression.
- Use double quotation marks for direct quotation, single quotation marks inside it, and backticks for code
  and identifiers.
- Use bold only for a critical warning or term. Do not use emoji unless the user or template requires them.
- Keep markers, grammatical roles, and endings consistent across parallel list items.

## Numbers and time

- Use Arabic numerals for exact technical quantities. Add a thousands separator every three digits.
- Attach Korean counting units: `3개`, `5명`, `2회`.
- Put a space before SI symbols: `10 ms`, `5 GB`, `25 °C`. Do not space percent and angle: `50%`, `90°`.
- Unless the project says otherwise, write technical dates as `YYYY-MM-DD` and use 24-hour time.
- Include a timezone when readers span timezones or interpretation could differ.

## Final review

1. Check spelling, spacing, particles, endings, and punctuation.
2. Check terminology, register, numbers, units, dates, lists, and emphasis.
3. Compare code and contract strings, facts, causality, negation, possibility, obligation, and scope.
4. Reduce nominalization, translationese, meta phrases, unnecessary subjects, and unsupported evaluation in context.
5. Confirm that each revision is more concrete and concise while preserving the same meaning.

Do not judge an expression from a suffix or final character alone.
For example, UI state `처리됨` may be a contract string.
Requirement wording such as `해야 함` may be a project format. Judge it by context and role.
