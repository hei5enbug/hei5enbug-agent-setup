# Confluence HTML body format

The rules here describe how the Confluence HTML converter treats a body you send it.

## Verified scope

Everything marked **verified** was observed directly against a Confluence Cloud instance through
the HTML body format, by sending a body and reading back what the converter stored.

Everything marked **convention** worked reliably but its failure mode was not deliberately tested.
Treat a convention as the safe default, not as a proven constraint.

Behaviour on Confluence Data Center and Server was not tested at all. If a rule below fails there,
trust the observed behaviour over this document.

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

`scripts/image_size.py` does this calculation.

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

## Tables

**Convention.** Wrap the content of every `td` and `th` in a block element.

```html
<tr><td><p>text</p></td><td><p>more text</p></td></tr>
```

Use `br` for a line break inside a cell. Use a second paragraph for a real paragraph break.

Keep header cells in a `thead` row.

## Text

**Convention.** Escape quotation marks and apostrophes in body text. Escape the usual reserved
characters. Inline code goes in a `code` element.

## What does not survive from Markdown

Remove these during conversion. They are correct in the source file and wrong on the page.

| Source form | Why it fails | Replacement |
|---|---|---|
| Absolute local path | Means nothing to a reader, and leaks a directory layout | Describe the thing instead of pointing at it |
| Relative link to another Markdown file | Does not resolve on Confluence | Name the target in the sentence, or link the published page |
| Fenced diagram source | Renders as a code block, not a diagram | An image, see `references/diagrams.md` |
| Section written for the document's authors | Not part of what readers need | Remove |

## Checklist before saving

`scripts/validate_body.py` covers the mechanical half of this list.

- No hand-written `media-single` or `media-group` container.
- Every `img` carries `width` and `height`.
- Every table cell wraps its content in a block element.
- No local filesystem path and no link to a Markdown file.
- Every referenced attachment exists on the page already.
- The version message names what changed.
