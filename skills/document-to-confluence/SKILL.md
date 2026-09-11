---
name: document-to-confluence
description: >-
  Convert Markdown, HTML, PDF, DOCX, or Google Docs content into a Confluence page and keep the page
  synchronized with later source revisions. Use when importing, publishing, migrating, updating, or
  repairing documents in Confluence, including tables, links, images, attachments, diagrams, page
  structure, or text fidelity.
compatibility: >-
  Needs a readable source and a Confluence write path. Source extraction can use connected services,
  local converters, document parsers, PDF text extraction, or OCR. Without a required capability,
  produce the normalized content, body, and attachment plan that the user can publish manually.
  Diagram rendering needs a headless browser. Image measurement uses the Python standard library.
---

# Document to Confluence

Use this English `SKILL.md` and its English references as the only executable sources.
`SKILL.ko.md` and other `.ko.md` files are non-authoritative human translations; never load them during execution.

Publish supported documents as Confluence pages while preserving their meaning, structure, relationships,
and useful visual content.

This skill separates source extraction from Confluence publishing. Select one source adapter, normalize
the source into the common document model, and then run one publishing workflow. Never skip normalization
by copying source markup directly into Confluence.

## Authority and resources

Higher-level Confluence instructions govern tool selection, credentials, comments, and destructive actions.
This skill reads no sibling skill and calls none.

Read only the references required for the current source and content:

| Reference | Read condition |
|---|---|
| `references/markdown.md` | The source is Markdown or Markdown text in the prompt. |
| `references/html.md` | The source is an HTML file, fragment, or rendered web document. |
| `references/pdf.md` | The source is a text PDF, layout PDF, or scanned PDF. |
| `references/docx.md` | The source is a DOCX file. |
| `references/google-docs.md` | The source is a native Google Doc. |
| `references/document-model.md` | Always, before converting extracted content. |
| `references/confluence-body.md` | Always, before building or repairing the Confluence body. |
| `references/attachments.md` | The document has images or other attachments. |
| `references/diagrams.md` | The document has diagrams or diagram source. |

If a required reference is absent, report the missing path and stop before the affected conversion or write.
Do not replace a missing contract with a guessed summary.

## Capability routing

Detect available capabilities before choosing mechanics. Prefer an existing connected or local tool that
preserves the required structure. Do not install a converter, run OCR through an external service, or upload
source content to another service without user authorization.

| Capability | Preferred path | Fallback |
|---|---|---|
| Confluence page access | Tool required by higher-level instructions | Produce the exact body and attachment plan for manual publishing. |
| Google Docs access | Authenticated Google Drive or Docs connector | Ask for an exported DOCX, HTML, or PDF file. |
| DOCX extraction | Structure-aware document converter or parser | Export through an available office application, then inspect the result. |
| PDF extraction | Text and layout extractor; OCR for image-only pages | Transcribe uncertain regions and mark them for user verification. |
| HTML extraction | DOM parser without executing untrusted scripts | Use visible static content and report content that requires rendering. |
| Diagram rendering | `scripts/render_diagrams.mjs` | Keep the source artifact and report that rendering remains. |
| Image measurement | `scripts/image_size.py` | Ask for verified pixel dimensions. |
| Body validation | `scripts/validate_body.py` | Apply the checklist in `references/confluence-body.md`. |
| Markdown text parity | `scripts/text_parity.py` for its supported subset | Compare source and normalized blocks manually. |
| Other source parity | Format-specific checks and block inventory | Compare the extracted model with the source side by side. |
| Column widths | `scripts/column_widths.py` | Estimate from the longest visible value and inspect the result. |

Keep the chosen method while the source, requirements, and available capabilities remain unchanged.
Re-evaluate it when one of those inputs changes.

## Run configuration

Resolve each value from the request and available evidence before asking the user. Ask only when the missing
choice would materially change the published result.

| Value | Required decision |
|---|---|
| Source | Exact file, URL, connected document, or prompt content and its format. |
| Source scope | Whole document, selected pages, named sections, or chosen tabs. |
| Target | Existing page ID, or destination space and parent for a new page. |
| Update mode | Replace from source, merge selected sections, or repair the current page. |
| Included review data | Treatment of comments, tracked changes, annotations, speaker notes, and hidden content. |
| Staging directory | Writable, ignored repository path or a temporary directory accepted by the upload tool. |
| Layout | Page width, table layout, column widths, and image display widths. |
| Navigation | Page title and table-of-contents depth. |
| Language | Source language used for OCR, fonts, sentence boundaries, and text comparison. |

Confirm the target before the first external write. For updates, confirm the requested update mode when
replacing the whole page could discard content that has no source counterpart.

## Workflow

### 1. Apply Confluence policy

Follow the higher-level Confluence instructions before choosing or invoking any Confluence tool.
Discover the command or tool contract before a write. Record capability fallbacks that change the outcome.

### 2. Capture a stable source revision

Read the source with the selected format adapter. Record the strongest revision marker available:

- local file path, size, and modification time or content hash;
- Google Drive file ID and revision or modified time;
- URL and retrieval time for authorized HTML;
- page range and extraction method for PDF.

For an existing page, read the complete current body and version. A save replaces the body, so preserve
content outside the requested change and preserve existing macro identifiers.

### 3. Extract source structure

Use the selected source reference. Capture semantic content before presentation details:

- headings and their levels;
- paragraphs, lists, quotations, code, and callouts;
- tables, merged cells, captions, and footnotes;
- links and their targets;
- images, diagrams, attachments, and alternative text;
- ordering, grouping, and relationships between these blocks.

Do not infer unreadable text or missing structure. Keep uncertainty tied to the affected block and resolve
material uncertainty before publishing.

### 4. Normalize the document

Read `references/document-model.md`. Build a source-neutral block inventory with stable source locators.
Preserve words, numbers, hierarchy, ordering, table relationships, link intent, captions, and alternative text.

Remove source-application chrome, repeated headers or footers, and authoring-only controls only when the
source adapter establishes that they are not document content. Record intentional omissions.

### 5. Build the Confluence body

Read `references/confluence-body.md`. Map normalized blocks to supported Confluence structures.
Keep wording unchanged unless the user requested editing. Change containers and unsupported presentation,
not the source's meaning.

Use a native table-of-contents macro when navigation is useful. Apply one table-spacing and width rule
throughout the document unless the source requires a documented exception. Remove local filesystem paths
and replace unresolved relative links with useful page wording or a valid published destination.

### 6. Prepare diagrams and attachments

When diagrams exist, read `references/diagrams.md`. Render diagram source to images unless a working
Confluence macro is available and requested. Inspect every rendered image for overlap, clipping, missing
glyphs, routing errors, and excess whitespace before upload.

When attachments exist, read `references/attachments.md`. Upload each file before referencing it.
Measure raster images with `scripts/image_size.py` and preserve their aspect ratios. Do not invent attachment
IDs, media IDs, dimensions, or filenames.

### 7. Validate fidelity and body structure

Run `scripts/validate_body.py` and fix every finding in its declared scope.

For Markdown within the script's supported subset, run `scripts/text_parity.py`. For every other source,
compare the normalized block inventory with the source and the generated body. Check exact text and counts
for headings, paragraphs, lists, table rows and columns, links, images, diagrams, footnotes, and intentional
omissions. Inspect constructs that no tool can compare.

Re-read the source when its revision marker changes. Rebuild affected blocks and repeat validation.

### 8. Save with concurrency protection

Immediately before saving, read the target page version again. If it differs from the version captured
earlier, stop and report both versions. Do not overwrite another editor's changes.

Confirm that the source revision is unchanged. Send the complete body and a version message that names the
source and the change. Compose oversized requests from complete blocks before the write.

### 9. Verify the stored result

Read the saved page in rendered or stored form. Compare its title, hierarchy, text, tables, links, images,
attachments, macros, and version with the validated body. Inspect visual layout when the host can display it.
Report any capability fallback and any item still requiring user verification.

### 10. Clean up with approval

List obsolete attachments or temporary external artifacts and explain why each can be removed.
Delete an attachment, comment, or external artifact only after explicit user approval.

## Update contract

Treat the captured source revision and normalized block inventory as the update baseline.
When republishing:

1. Identify source blocks that were added, changed, moved, or removed.
2. Distinguish source-derived page content from Confluence-only content.
3. Apply the requested update mode without silently deleting Confluence-only content.
4. Preserve stable attachment names and macro identifiers when their semantic content remains.
5. Re-run extraction when the source format or exporter changes because block boundaries may change.

## Rules for every source

- Preserve factual content, ordering, hierarchy, negation, uncertainty, units, and link intent.
- Preserve source structure when Confluence supports it. Record every deliberate structural downgrade.
- Never publish OCR text, malformed tables, or ambiguous reading order as verified content.
- Never expose local paths, credentials, hidden document data, or unsupported private links.
- Never claim source parity from a validator that does not support the source construct.
- Confirm the target before the first write and verify the stored page after every write.
- Ask before permanent deletion.

## Bundled resources

| Path | Contract |
|---|---|
| `scripts/image_size.py` | Reads PNG, JPEG, and GIF dimensions. Reports unsupported or truncated input and calculates a clamped display size. |
| `scripts/column_widths.py` | Produces integer column-width ratios and rejects impossible floors or incomplete image constraints. |
| `scripts/text_parity.py` | Compares text for its declared Markdown subset and reports unsupported constructs. |
| `scripts/validate_body.py` | Checks mechanical Confluence body rules within its declared scope. |
| `scripts/render_diagrams.mjs` | Captures valid, unique element IDs from local HTML and always closes the browser. |
| `assets/diagram-template.html` | Provides a starting point for consistent HTML and CSS diagrams. |

Run each script with `--help` for its exact interface.
