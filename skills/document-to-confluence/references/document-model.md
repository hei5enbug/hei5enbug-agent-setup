# Common document model

Normalize every supported source into this logical model before generating a Confluence body.
The model is a working representation, not a required file format.

## Document fields

Record these document-level values when the source provides them:

| Field | Meaning |
|---|---|
| `title` | Published page title. |
| `language` | Language used for OCR, font selection, and sentence boundaries. |
| `source_revision` | Stable source identity and freshness marker. |
| `scope` | Whole document or selected pages, sections, or tabs. |
| `metadata` | Author, created date, modified date, and other user-approved visible metadata. |
| `blocks` | Ordered top-level content blocks. |
| `assets` | Images, files, and diagram outputs referenced by blocks. |
| `omissions` | Source content intentionally excluded with its locator and reason. |
| `uncertainties` | Unreadable or ambiguous source regions requiring verification. |

Do not publish hidden properties, revision history, comments, tracked changes, or annotations unless the user
includes them in scope.

## Block fields

Each block needs a type, ordered content, and a stable source locator.
Use source-native locators such as a Markdown heading, HTML element path, PDF page and region,
DOCX paragraph or table position, or Google Docs tab and index.

Supported logical block types include:

- heading with level and text;
- paragraph with inline runs;
- ordered or unordered list with nested items;
- quotation, callout, or code block;
- table with header roles, rows, columns, spans, and caption;
- image or diagram with asset reference, caption, and alternative text;
- attachment link;
- footnote or endnote with its referring block;
- explicit page or section break when it carries meaning.

Inline runs preserve text, emphasis, code, link target, and line-break intent.
Do not use visual coordinates as the only representation of semantic order.

## Invariants

- Block order follows the source's reading order.
- Heading levels preserve hierarchy without gaps introduced by conversion.
- Lists preserve nesting, sequence, and numbering when the number is meaningful.
- Tables preserve cell text, header roles, row and column relationships, and merged-cell spans.
- Links preserve their label and destination intent even when the destination must be replaced.
- Images preserve their caption, alternative text, and relationship to surrounding content.
- Footnotes remain connected to their references.
- Every omission and uncertainty points to a source locator.

## Fidelity inventory

Before generating the body, count the applicable source structures.
After generating it, compare the same counts and inspect every exception.

| Structure | Minimum comparison |
|---|---|
| Headings | Text, level, and order. |
| Paragraphs | Text and paragraph boundaries. |
| Lists | Item count, nesting, and order. |
| Tables | Table count, dimensions, headers, spans, and cell text. |
| Links | Label, destination, and unresolved destination handling. |
| Images and diagrams | Asset count, caption, alternative text, and placement. |
| Footnotes | Reference count and note text. |

Counts expose dropped structures but do not prove semantic fidelity.
Read the normalized model against the source before publishing.
