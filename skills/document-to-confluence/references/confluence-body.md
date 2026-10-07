# Confluence HTML body format

The rules here describe how the Confluence HTML converter treats a body you send it.

## Checked scope

Everything marked **verified** was observed against a Confluence Cloud instance by sending a body
through the Confluence REST API in its HTML body representation and reading back what the
converter stored. The check date and the exact client used were not recorded when these notes
were written, so treat each verified rule as an observation of unknown age: the first time one
fails, trust the page over this document and record the date and tool of the new observation here.

Everything marked **convention** worked reliably but its failure mode was not deliberately tested.
Treat a convention as the safe default, not as a proven constraint.

### Assumptions

These statements have no recorded observation behind them. Confirm them at use time.

- Confluence Data Center and Server behave like Cloud for the rules below. They were not tested.
- Every connected Confluence tool accepts the HTML body representation used here. Tools that
  accept only storage format or ADF need a conversion step this document does not describe.
- The `width` and `height` convention on `img`, the block-element rule for table cells, and the
  text escaping rule are conventions, not verified constraints.

## The body is replaced whole

**Verified.** There is no partial edit. A save replaces the entire body.

So an update always runs read, then modify, then send. Sending a body you assembled without
reading the current one deletes whatever you did not happen to include.

Preserve values the converter generated on an earlier save, notably macro identifiers.

## Images

### Write a plain img element

**Verified.** This is the only reliable way to place an inline image.

```html
<p><img src="/wiki/download/attachments/PAGE_ID/FILENAME" alt="..." width="900" height="225"></p>
```

The converter rewrites this into its own figure node with the matching width metadata. You do not
write that node yourself.

### A hand-written media-single container is rejected

**Verified.** Sending a `div` carrying `data-type="media-single"` fails the request with an
unsupported data-type error. The node is valid in stored content, but the HTML converter will not
accept it as input.

### A media-group container renders as a card

**Verified.** `data-type="media-group"` produces an attachment card, not an inline image. It is
the wrong node for a picture inside a paragraph or a table, even though the request succeeds and
nothing reports an error.

This failure is quiet. The page looks wrong rather than broken.

### Images work inside table cells

**Verified.** An `img` element inside a table cell is converted normally and stays in the cell.

```html
<td><p><img src="/wiki/download/attachments/PAGE_ID/before.jpg" alt="before" width="200" height="139"></p></td>
```

Do not restructure a table into a column layout to place pictures. That changes the document for a
reason that does not exist.

### Always state width and height

**Convention.** Take both numbers from the file itself and scale them together. An `img` whose
declared ratio differs from the real ratio is drawn stretched.

Scale down, never up. A display width above the file's pixel width blurs the image. Render a
higher-resolution image instead.

When the page width changes, revisit every display width. A diagram sized for a narrow page wastes
space on a wide page, while enlarging a small image makes it less legible.

`scripts/image_size.py` does this calculation. Write its `display_width` and `display_height` onto
the element; its `width` and `height` are the file's real size for the ratio check. When it
returns `clamped: true`, the requested width exceeded the file and was reduced to the file width.

### Referencing by identifier

**Verified.** If you reference a media node by identifier rather than by download URL, the value
must be the media file id, which is a UUID. The attachment id, which looks like `att` followed by
digits, is a different value.

Passing an attachment id where a file id belongs does not fail. Confluence creates a new empty
attachment named after the identifier string, and readers see a broken preview. Cleaning that up
means deleting attachments, which needs user approval.

Referencing by download URL avoids this problem entirely, which is why the `img` form above is the
default.

## Table of contents

**Verified.** Use the built-in macro rather than a hand-written list, so the page keeps working
when headings change.

```html
<div data-type="extension"
     data-extension-key="toc"
     data-extension-type="com.atlassian.confluence.macro.core"
     data-layout="default"
     data-parameters="{&quot;macroParams&quot;:{&quot;maxLevel&quot;:{&quot;value&quot;:&quot;3&quot;},&quot;minLevel&quot;:{&quot;value&quot;:&quot;2&quot;}}}"></div>
```

Do not invent a macro identifier. Omit it when creating the macro. When a body you read already
carries one, send it back unchanged, because it is how the page tracks that macro instance.

## Info panel

**Observed.** On 2026-09-29, `confluence read --format storage` returned a rendered info panel
stored as this storage-format macro:

```xml
<ac:structured-macro ac:name="info" ac:schema-version="1">
  <ac:rich-text-body>
    <p><strong>PANEL TITLE</strong></p>
    <ul><li><p><strong>TERM</strong>: explanation</p></li></ul>
  </ac:rich-text-body>
</ac:structured-macro>
```

The body format that produced it was not recorded. Keep one body format per write: do not mix this
storage-format macro with HTML body markup such as the table-of-contents element above. Before the
first write, confirm the panel markup that the write tool accepts in the chosen format, then read
the page back and verify that the panel renders. The macro-identifier rule for the table of
contents applies here too.

## Tables

**Convention.** Wrap the content of every `td` and `th` in a block element.

```html
<tr><td><p>text</p></td><td><p>more text</p></td></tr>
```

Keep header cells in a `thead` row.

### Cell spacing

**Verified.** A paragraph break and a line break inside a cell produce different gaps. Mixing both
forms across a table creates uneven row spacing.

Use one form consistently within a document. Use line breaks for stacked values and paragraphs
for separate prose. Give an image its own paragraph regardless of the selected text spacing.

### Table and column widths

**Verified.** `data-layout` on a table and `data-colwidth` on each cell survive conversion and
remain when the page is read back.

```html
<table data-layout="full-width">
  <thead><tr>
    <th data-colwidth="220"><p>Code</p></th>
    <th data-colwidth="1580"><p>Decision</p></th>
  </tr></thead>
  <tbody><tr>
    <td data-colwidth="220"><p>ABCDE</p></td>
    <td data-colwidth="1580"><p>...</p></td>
  </tr></tbody>
</table>
```

Give every cell in a column the same value, including the header.

**Verified.** The widths behave as ratios rather than fixed pixels. The table fills its available
width and divides that width by the stated proportions.

Match the table layout to the page width. Set column widths on every table unless its columns carry
comparable content and an even division is appropriate.

When widths are needed, reserve only the necessary space for columns containing short values and
leave the remaining width to columns whose text wraps. Estimate the needed width from the longest
line. Treat CJK glyphs as wider than Latin letters and include inline-code padding. Give an image
column an explicit minimum width equal to the image display width.

`scripts/column_widths.py` produces a deterministic estimate. Review its output before publishing;
the content-based weighting is a layout aid, not visual proof. The script recognizes an image column
only by Markdown image syntax `![...](...)` in a cell, and it requires `--floor` for that column. A
cell that holds an HTML `<img>` is not recognized, so set that column's minimum width manually.

## Text

**Convention.** Escape quotation marks and apostrophes in body text. Escape the usual reserved
characters. Inline code goes in a `code` element.

### Paragraph structure

Preserve the paragraphs in the source document. Never put an explicit line break inside a
sentence. Remove such breaks from the source or the current page, but keep breaks that separate
stacked values.

Break a paragraph or table cell at sentence boundaries when it holds more than one sentence and
does not fit on one display line. Leave a single sentence and a paragraph that fits on one line
unbroken. Derive the threshold from the display width: use the page width for body text and the
column width for a table cell.

## Source artifacts that do not belong on the page

Remove or replace these during conversion. They may be valid in the source application but do not
produce a usable published page.

| Source form | Why it fails | Replacement |
|---|---|---|
| Absolute local path | Means nothing to a reader, and leaks a directory layout | Describe the thing instead of pointing at it |
| Relative source-document link | Does not resolve for page readers | Link the published destination or name the target in the sentence. |
| Diagram source or unsupported embedded object | Renders as text or disappears | Use a supported macro or an accessible image. |
| Source application control or authoring note | Is not reader content | Remove it unless the user includes review data. |
| Repeated page header, footer, or page number | Interrupts the page reading flow | Remove it after the source adapter confirms its role. |

## Checklist before saving

`scripts/validate_body.py` checks exactly these items:

- No hand-written `div` with `data-type` `media-single` or `media-group`.
- Every `img` has `width` and `height`. The script checks that both are present, not that they match
  the source pixel size.
- Every table cell wraps its content in a child element. Any element counts, not only block elements.
- No local filesystem path in text or attributes, and no unresolved source-document link in `href`.
- When `--attachments` is given, every attachment reference exists in that list.

The remaining items need a manual check, or another script for text parity:

- No dimension scales an image above its source pixel size.
- Table layout, column widths, and cell spacing follow one consistent rule.
- Every table sets column widths unless its columns carry comparable content.
- No explicit line break falls inside a sentence.
- Every referenced attachment exists on the page already.
- The body's text matches the source within the parity checker's supported scope, or a manual
  comparison covers the unsupported constructs.
- The version message names what changed.
