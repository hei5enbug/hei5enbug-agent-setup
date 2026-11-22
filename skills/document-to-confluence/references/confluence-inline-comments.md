# Inline comment markers in a Confluence body

## Inline comment markers

**Observed on 2026-10-16 in storage format.** An inline comment is anchored by an `ac:inline-comment-marker`
element around the selected text in the page body:

```xml
<ac:inline-comment-marker ac:ref="MARKER_REF">selected text</ac:inline-comment-marker>
```

A save whose body lacks a comment's marker leaves the comment without an anchor, and the page shows it as
deleted content. A body rebuilt from the source has no markers until you put them back.

The HTML body does not keep markers. Write a page that has markers in storage format, and keep the previous
stored body.

Before every republish:

1. List the page's inline comments, open and resolved, with each marker reference and original selection.
2. Convert the validated HTML body with `scripts/storage_body.py`. Restore the markers with
   `scripts/comment_markers.py restore` from the previous stored body and the converted body.
3. When the restorer exits non-zero, it lists each unresolved reference with its old context and writes no body.
   Choose the new text that carries the same meaning, rerun with `--anchor` or `--anchors`, and report the
   move. When no text carries that meaning, ask the user before saving.
4. Save only a body that holds every listed reference.
5. After saving, run `scripts/comment_markers.py check` on the previous body and the stored body. Fix every
   missing reference and save again. Confirm that each comment still reports its anchor; when a browser is
   available, check the rendered page for a deleted-content notice.
