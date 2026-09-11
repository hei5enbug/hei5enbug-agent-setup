# DOCX source

Use this adapter for Microsoft Word DOCX files.
Prefer a structure-aware parser or converter that preserves styles, relationships, and embedded assets.

## Content selection

Extract visible document content in body order:

- title and heading styles;
- paragraphs and character formatting;
- numbered and bulleted lists with nesting;
- tables, merged cells, and captions;
- hyperlinks, bookmarks, cross-references, footnotes, and endnotes;
- inline and floating images with captions and alternative text;
- headers and footers when they carry document content.

Ask how to handle tracked changes and comments only when they exist and the request does not establish
whether the published page should use accepted text, original text, or review markup.
Do not publish hidden text, document properties, macros, or embedded files by default.

## Conversion behavior

Use paragraph styles to determine hierarchy. Visual font size alone does not prove a heading level.
Preserve automatic numbering when the number communicates sequence or identity.
Resolve relationship targets for links and media through the document package.

Treat text boxes, shapes, equations, SmartArt, and embedded objects as special blocks.
Use an available renderer or office application when a parser cannot preserve them.
If they must become images, retain an accessible caption or text alternative and record the downgrade.

## Fidelity check

Compare document statistics and the normalized block inventory where the tool exposes them.
Inspect headings, list numbering, table spans, links, notes, and every special block.
Confirm that the DOCX file revision is unchanged immediately before publishing.
