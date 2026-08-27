---
name: technical-design-writer
description: >-
  Create, improve, or review technical design documents with precise terminology, complete
  implementation rules, non-overlapping structure, plain language, effective tables and diagrams,
  stable references, and progressive outline narrowing. Use for requests such as "설계 문서 작성",
  "설계 문서 개선", "설계 문서 목차", or "design doc". Do not use for translation, typo
  correction, or prose polishing unrelated to technical design.
metadata:
  version: "1.5.0"
compatibility: >-
  Works in any agent host that can read and write Markdown. Repository inspection and Mermaid
  rendering improve evidence and review but are not required for the core workflow.
---

# Technical Design Writing

Create documents that let a reader implement, validate, or decide without guessing.

## Authority and scope

Use this English `SKILL.md` as the only executable instruction source.
`README.ko.md` is a non-authoritative Korean translation for human readers; do not read or use it while executing the skill.
Treat Korean text in this file as target-language data, not additional instructions.

Apply it only to technical design work, after higher-priority instructions, unless the user explicitly excludes a rule.

## Workflow

1. Define the audience, scope, required decisions, implementation questions, and validation questions.
   For an existing document, also identify missing content, unsupported claims, and rule violations.
2. Finalize second-level headings before writing the body. Narrow the outline in five passes:
   1. Start from the current chapter structure or a first-level outline.
   2. Remove sections that duplicate a role or restate information already clear elsewhere.
   3. Put each table, diagram, and tool in the section where it is used.
   4. Merge related sections or split dense ones without dropping required topics.
   5. Expand every section through second-level headings and finalize them.
3. Gather the evidence and source contracts needed to support the design.
4. Draft under the rules below. For a Korean deliverable, complete the draft in English first, then translate it into Korean.
5. Plan terminology changes once for the entire scope:
   1. Find every occurrence and group positions such as standalone terms, compounds, headings, table headers, and implementation identifiers.
   2. Test one replacement for every position and record one old-term-to-new-term mapping.
   3. Apply the mapping across all files in one pass.
   4. Update every affected reference and verify cited headings against actual headings.
   5. Ask before renaming an implementation identifier derived from the document.
6. Review every rule in this file and remove unsupported or unnecessary statements.

## Terminology

| Rule | Requirement |
|---|---|
| Canonical terms | Use one full term for each meaning and one meaning for each term. Do not shorten a canonical term or reuse any word inside it with another sense. |
| Plain language | Use established plain wording in the target language. Keep a foreign-language term only when no suitable equivalent exists. |
| Literal names | Preserve proper nouns and exact implementation or contract names despite grammar differences. Define abbreviations and symbols unless their source fixes them. |
| Established sense | Use dictionary or established domain meanings. Avoid coined, figurative, system-conflicting, or neighboring-field senses. Definition substitution must preserve the statement. |
| Precise operations | Use the verb or technical noun that names the actual operation. If one word needs different replacements by context, replace each use with its specific meaning. |
| Distinct names | Name an item by what distinguishes it from peers, usually what it owns or produces. Keep a qualifier only when the unqualified name denotes a different item. |

## Semantic precision

Include information only when its omission permits materially different implementations, validations, decisions, or interpretations.
For each statement, try to construct two materially different outcomes that both satisfy it.
If this is possible, add only the information that distinguishes the outcomes.

| Check | Requirement |
|---|---|
| Subject identity | Name the subject at the abstraction level on which the statement operates. Do not substitute a related object, identifier, representation, or container. |
| Reference | A reference resolves within its sentence, cell, or list introduction. Otherwise repeat the canonical term or use a stable name; position, pronoun, or count alone is insufficient. |
| Operation | State the operation, affected subject, and observable result. Add actor, source, destination, condition, priority, or order when omission changes behavior. |
| Rule completeness | A decision or transformation states its inputs, evaluation order or precedence, output, and fallback or exceptional result. |
| Evidence | A quantity includes its unit and reproducible measurement basis. A qualitative claim that affects implementation, validation, or a decision names its criterion or evidence. |
| Structured content | A table cell forms one proposition with its headers. A list item forms one proposition with its introduction. |

Give actions only to actors; use a state or change predicate for other subjects.
Keep one claim in each sentence and one central idea in each paragraph.
Read a sentence's subject and predicate alone; rewrite when they do not agree.
Use an exact count when the available data permits one, and an approximation only when it does not.
Replace a colon followed by items with a complete sentence, list introduction, or table.

A label identifies a subject, property, category, relationship, or state clearly and concisely.
A statement communicates an operation, condition, decision, result, or reason without omitting meaning-changing information.
Items with the same role use a consistent semantic structure and writing style.
A decision node names the property being judged, and its edges name the outcomes.

## Structure and size

- Give every document and section one distinct scope. Cover each topic in one place.
- Keep only content whose removal would reduce implementation, validation, understanding, or decision quality.
- Use subheadings for subdivisions.
- Write every heading as a noun phrase without a predicate, question, or trailing colon.

| Target | Limit |
|---|---:|
| Rendered line | 200 characters |
| File | 500 lines |
| Section depth | 3 levels |

Do not split a file within the limits. Split a file that exceeds a limit by responsibility.
Inside a table cell, `<br>` starts a new rendered line.

## Markdown and paragraphs

- Separate paragraphs with one blank line.
- Put a blank line before and after headings, tables, code blocks, and lists.
- Align a multiline list continuation with the first character of the item text.
- Keep source lines together when Markdown should render one flowing paragraph.
- Break a paragraph only after a complete sentence.
- For a required visible break, use `<br>` only when the target supports inline HTML; otherwise use a paragraph, list item, or table row.
- Never use trailing spaces to create a line break.

## Tables

- Use a table when three or more items or three or more dimensions share the same comparison dimensions.
- Keep a comparison of two items across two dimensions in prose.
- When a cell exceeds two sentences or 120 characters, split it at sentence boundaries with `<br>`.
- If one sentence exceeds 120 characters, rewrite it or move its detail to the section body.
- For three or more items in one cell, start each item with `<br>· `.
- Move content that needs more than five rendered cell lines into the section body, leaving a short reference in the cell.
- Do not restore unnecessary content merely to fill a table.

## Diagrams

- Use Mermaid only when a branch, state change, or interaction communicates structure or flow better than prose or a table.
- Do not diagram a simple fact list, a one-line explanation, or an unbranched sequence.
- Remove a diagram that duplicates adjacent content or is less clear than prose or a table.
- Balance both dimensions with real branches or siblings; changing direction does not fix a one-dimensional shape.
- Put pass-through elements on edges and reserve nodes for actors.
- A boundary-crossing arrow attaches to the subgraph boundary, not its node. Use a subgraph only for siblings with few crossing arrows, and never wrap one node.
- Render every diagram and inspect clipping, overlap, routing, labels, and visual balance.

## Duplication, references, and contracts

- Never reference documentation from code, including comments and docstrings.
- Keep one detailed source for each topic. Summarize and link elsewhere without dropping any condition from the source.
- Cite a document path and section title, not a section number, position, or reference symbol. Verify every cited title against the actual heading.
- When copying a contract from code or an external source, name the source of truth and every file that must change with that contract.

## Tool boundary

Use mechanical tools only for structural conditions they can decide exactly.
Search may locate text but cannot decide semantic quality.
Before creating custom tooling, compare available host capabilities and established tools.
Create a validator only when every reported failure is a real violation and every supported violation fails.
Keep semantic precision as contextual model judgment.

## Completion gate

- [ ] The workflow ran in order, including outline narrowing and one-pass terminology replacement.
- [ ] Every rule in "Terminology" and "Semantic precision" passes without adding unnecessary detail.
- [ ] Every document part meets "Structure and size", "Markdown and paragraphs", "Tables", and "Diagrams".
- [ ] Every source, summary, reference, and copied contract meets "Duplication, references, and contracts".
- [ ] Every mechanical check meets "Tool boundary", and every semantic judgment was reviewed in context.
