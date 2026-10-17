# Documentation files

Use [technical-design-writer](../skills/technical-design-writer/SKILL.md) only when the user explicitly
requests technical design work, such as a technical design document, architecture proposal, RFC, system
design, data design, API design, or design outline, or directly invokes that skill. Its Create and Improve
modes load the design-document workflow and the shared independent model validation rules. Do not load or
invoke the skill for ordinary documentation.

Apply these content rules to every documentation file, including technical design documents and Markdown or
HTML that will later be published elsewhere:

- Name what the evidence actually observes, records, approximates, or calculates. An absent record proves
  only that no record was found unless the source would necessarily record that event.
- For a rate or proportion, state its denominator and any material exclusion or deduplication when known.
  Do not compare results as one metric when their population or outcome definition changed without saying so.
- When a number from delegated work, notes, or an earlier draft has not been checked against its raw source,
  confirm there what it covers, such as the stage, period, environment, and data size, and state that coverage
  with the number. Reuse a check already made against that source.
- In a document that describes current state, put dated progress, superseded observations, and dated change
  notes in a final change-history section unless a nearby claim needs them for its meaning or validity. Apply
  this to a new document or the part being written, not as an unrequested restructuring of existing text.
- When correcting a material claim, reconcile the statements that depend on it within the authorized scope,
  and report conflicts outside that scope without editing them.
- Embed an image or diagram that the reader needs instead of telling the reader to open a file path.

For ordinary documentation, apply these writing mechanics directly:

- Write for high school students; basic development terms are allowed. Use concrete subjects and verbs,
  one claim per sentence, and one central idea per paragraph.
- Use the terminology order in the session instructions. Preserve literal identifiers and contract names,
  and use one term for each meaning.
- In Korean documents, choose wording from context, audience, genre, project usage, and natural collocation.
  Do not mechanically replace a familiar loanword or established expression with a supposedly purer or
  simpler alternative. Examples are evidence for a decision, not a global substitution table.
- Give each page one reader goal and each section one responsibility. Use at most three heading levels and
  keep Markdown prose lines within 120 characters, except for tables, URLs, code, and exact literals.
- Use a table for three or more comparable items with stable fields. Use a diagram only when a complex
  branch, state change, interaction, boundary, dependency, or data relationship becomes clearer visually.
- Keep one detailed source for each topic. Use stable path-and-heading references and verify every link and
  cited heading.
- Verify factual values, units, ranges, and guarantees against the source. An identifier or familiar
  convention is not evidence of a unit. Keep unspecified details unspecified, and label proposed choices
  separately from observed facts.

Chat replies use only the terminology and reply-format rules in the common instructions.
