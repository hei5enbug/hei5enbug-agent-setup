# Documentation files

Use [technical-design-writer](../skills/technical-design-writer/SKILL.md) only when the user explicitly
requests technical design work, such as a technical design document, architecture proposal, RFC, system
design, data design, API design, or design outline, or directly invokes that skill. Its Create and Improve
modes load the design-document workflow and the shared independent model validation rules. Do not load or
invoke the skill for ordinary documentation.

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

Chat replies use only the terminology and reply-format rules in the common instructions.
