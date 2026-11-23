# Images in a Confluence body

## Images

### Write a plain img element

**Verified.** This is the only reliable way to place an inline image.

```html
<p><img src="/wiki/download/attachments/PAGE_ID/FILENAME" alt="..." width="900" height="225"></p>
```

The converter rewrites this into its own figure node with the matching width metadata. You do not
write that node yourself.

### Captioned image

**Observed on 2026-11-03.** Through a connected Confluence page tool, this figure with an external image URL was
stored as an `ac:image` holding `<ac:caption><p>CAPTION</p></ac:caption>`. The same figure without
`data-type="media-single"` was rejected. An attachment download URL in this form was not tested.

```html
<figure data-type="media-single" data-layout="center"><img src="/wiki/download/attachments/PAGE_ID/FILENAME" alt="..." width="900" height="225"><figcaption>CAPTION</figcaption></figure>
```

`scripts/storage_body.py` converts this figure for a storage-format write.

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

### Storage-format image

**Observed.** In storage format, a body that referenced an image's download URL through an external media
node saved without error. The next version replaced it with
`<ac:image ac:width="WIDTH"><ri:attachment ri:filename="FILENAME" /></ac:image>`, and its version message
reported that rendering became correct. The earlier display was not inspected.
