---
name: technical-design-writer
description: >-
  Create, improve, or review implementation-ready technical design documents, architecture
  proposals, RFCs, system designs, data designs, API designs, and design outlines. Use for requests
  such as "설계 문서 작성", "설계 문서 개선", "설계 문서 목차", "design doc", or "RFC review".
  Enforce evidence, complete design coverage, explicit trade-offs, precise contracts, predictable
  structure, natural Korean, effective tables and diagrams, and stable references. Do not use for
  translation, generic copyediting, user guides, release notes, or code review without design intent.
metadata:
  version: "2.0.1"
compatibility: >-
  Works in any agent host that can read and write Markdown. Repository inspection and diagram
  rendering improve evidence and review but are not required for the core workflow.
---

# Technical Design Writing

Create documents that let the intended reader implement, validate, operate, or approve a design
without guessing.

## Authority and resources

Use this file and the references it explicitly requires as executable instructions.
`README.ko.md` is a non-authoritative Korean mirror for human readers; do not read it during execution.

For every Korean deliverable, read `references/korean-writing.md` before drafting or reviewing.

Apply this skill only to technical design work, after higher-priority instructions. User requirements,
repository rules, supplied templates, and established project conventions override this skill.

## Modes

| Mode | Required result |
|---|---|
| Create | Produce a complete design document from verified requirements and evidence. |
| Improve | Preserve supported intent and contracts while repairing omissions, ambiguity, duplication, and structure. |
| Review | Do not mutate files unless asked. Return prioritized findings with location, impact, and correction. |

## Workflow

1. Determine the mode, audience, reader goal, scope, required decisions, and evidence sources. For an
   existing document, also identify unsupported claims, missing design coverage, and rule violations.
2. Build a private coverage matrix from "Design coverage". Mark each concern applicable or inapplicable
   with a reason. Do not add empty or irrelevant sections merely to expose the matrix.
3. Finalize second-level headings before writing the body. Narrow the outline in five passes:
   1. Start from the current structure or a first-level outline.
   2. Give the document one reader goal and each section one non-overlapping responsibility.
   3. Remove repeated summaries and put every table, diagram, and tool where it is used.
   4. Order prerequisites before dependent decisions; merge related sections or split dense ones.
   5. Expand through second-level headings and verify that every applicable coverage concern has one home.
4. Gather source contracts and evidence. Prefer requirements, code, schemas, configuration, measured
   results, and official interfaces over descriptive prose. Label unknowns and assumptions; never invent.
5. Draft the opening first. State the selected design, reader outcome, scope, and material risks before
   background or implementation detail.
6. Draft the body directly in the target language. Apply "Design coverage", "Precision", "Structure",
   and the required language reference.
7. Plan terminology changes once for the entire scope. Record one old-to-new mapping, apply it across
   all affected files, update references, and verify cited headings. Ask before renaming implementation
   identifiers or externally visible contract names.
8. Validate copied contracts, examples, commands, links, calculations, and diagrams with the strongest
   available method. Do not claim validation that did not run.
9. Run the completion gate. Remove drafting notes, unsupported claims, and content that does not help
   implementation, validation, operation, or approval.

## Design coverage

Include each applicable concern exactly once. Combine concerns when one section can cover them clearly.

| Concern | Questions the document must answer |
|---|---|
| Context | What problem, reader outcome, goals, non-goals, constraints, and assumptions define the design? |
| Decision | What is selected, why is it selected, and which alternatives and trade-offs were rejected? |
| Boundary | Which actors, systems, owners, dependencies, trust boundaries, and responsibilities are in scope? |
| Contract | What inputs, outputs, schemas, invariants, compatibility rules, and data lifecycles apply? |
| Behavior | What are the normal flow, ordering, state changes, concurrency rules, idempotency rules, and fallbacks? |
| Failure | How are invalid input, partial failure, timeouts, retries, duplicates, and recovery handled? |
| Safety | What authentication, authorization, privacy, integrity, abuse, and compliance controls apply? |
| Operations | What capacity, observability, ownership, support, and cost requirements apply? |
| Change | How will rollout, migration, backward compatibility, rollback, and cleanup work? |
| Proof | What tests, measurements, acceptance criteria, and open decisions prove or block completion? |

## Precision

Include information when omitting it permits materially different implementations, validations,
operations, decisions, or interpretations. For each rule, try to construct two materially different
outcomes that both satisfy it. Add only the information that distinguishes them.

| Check | Requirement |
|---|---|
| Subject | Name the actor or object at the correct abstraction level, not its identifier or representation. |
| Operation | State the operation, affected subject, and result. Add conditions and order when they change behavior. |
| Rule | State inputs, evaluation order or precedence, output, and fallback or exceptional result. |
| State | Define valid states, transition triggers, guards, terminal states, and behavior for invalid transitions. |
| Evidence | Give quantities a unit and reproducible basis. Give material qualitative claims a criterion or source. |
| Reference | Make a reference resolve in its sentence, cell, or list introduction; otherwise repeat the stable name. |
| Structure | Make every cell one proposition with its headers and every item one proposition with its introduction. |

Give actions only to actors; use state or change predicates for other subjects. Keep one claim per
sentence and one central idea per paragraph. Use exact counts when the evidence permits them. Distinguish
requirements, current facts, assumptions, proposals, and open questions.

## Terminology

Resolve terminology in this order:

1. Explicit user or project glossary
2. Literal implementation, interface, schema, and contract names
3. Official product or established domain terms
4. Established plain wording in the target language
5. The most common existing form only when the remaining choices are equally correct

Use one canonical term for each meaning and one meaning for each term. Define an unfamiliar term before
its first dependent use. Define an abbreviation once only when it improves repeated use or searchability,
then use one form consistently. Do not replace a precise technical term with an easier but different term.

## Structure

- Give one page one reader goal and one section one responsibility. Split when goals differ or a fourth-level
  heading would be required; do not split merely to shorten a file.
- Put a concise decision summary directly under the title. Put value and outcome before history and detail.
- Order information from prerequisites to decisions, behavior, failure handling, change, and proof.
- Use noun-phrase headings without trailing punctuation. Keep Korean headings within 30 characters unless
  an exact identifier or distinguishing qualifier would be lost.
- Use at most three heading levels. Keep authored Markdown files at 500 lines or fewer. Exempt a supplied
  template or generated contract only when splitting it would change the artifact.
- Keep Markdown prose source lines within 120 characters. Exempt table rows, URLs, code, and exact literals.
  Break only after a complete sentence and preserve the intended rendered paragraph.

## Tables and diagrams

Use a table when three or more comparable items or dimensions share stable comparison fields. Use prose
for a small comparison. Keep headers and cells semantically parallel; move multi-paragraph detail to the body.

Use a diagram when a complex branch, state change, interaction, ownership boundary, dependency graph, or
data relationship is clearer visually. Choose the smallest fitting form: flow or state diagram for behavior,
sequence diagram for interactions, component diagram for boundaries, and entity relationship diagram for data.

Do not duplicate adjacent prose. Use nodes for actors or states and edge labels for conditions or transferred
data. Avoid one-node groups and ambiguous boundary-crossing arrows. Render every diagram and inspect labels,
clipping, overlap, routing, and visual balance. If rendering is unavailable, disclose it and verify syntax only.

## Markdown and references

- Separate paragraphs with one blank line. Put a blank line around headings, tables, code blocks, and lists.
- Use ordered lists only for sequence or priority. Keep items at one level semantically and grammatically parallel.
- Use backticks for literal identifiers, paths, commands, values, and code. Use descriptive link text.
- Use explicit paragraphs, list items, or table rows for visible breaks. Do not use trailing spaces for line breaks.
- Keep one detailed source for each topic. Summarize and link elsewhere without dropping source conditions.
- Cite a document path and heading title, not a section number, position, or special reference symbol. Verify
  every cited heading against the current source.
- When copying a contract, name its source of truth and every artifact that must change with it.
- Never reference documentation from code, including comments and docstrings.

## Tool boundary

Use mechanical tools only for exact conditions. Search can locate candidates but cannot decide semantic quality.
Render diagrams and execute examples when possible. Create a validator only when every reported failure is a
real violation and every supported violation fails. Keep contextual precision, style, and applicability as model
or human judgment.

## Completion gate

- [ ] The workflow ran in order, and the output matches Create, Improve, or Review mode.
- [ ] Every applicable design concern has one complete home; every omitted concern is genuinely inapplicable.
- [ ] Requirements, facts, assumptions, proposals, and open questions are distinguishable.
- [ ] Every rule, state transition, contract, failure path, migration step, and acceptance criterion is unambiguous.
- [ ] Every claim, quantity, example, command, link, copied contract, and diagram has adequate evidence
      or a clear limitation.
- [ ] Terminology, tone, numbers, units, headings, lists, tables, diagrams, and references are consistent.
- [ ] The target-language reference passes, and exact literals, causality, negation, modality, and scope are preserved.
- [ ] No unnecessary content, duplicated source, unresolved placeholder, or unsupported claim remains.
