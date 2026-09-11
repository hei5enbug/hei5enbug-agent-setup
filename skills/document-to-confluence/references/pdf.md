# PDF source

Use this adapter for text PDFs, layout PDFs, and scanned PDFs.
PDF stores appearance more reliably than semantic structure, so establish reading order before conversion.

## Source classification

Inspect representative pages and classify the source:

| Type | Primary extraction |
|---|---|
| Tagged PDF | Use the tag tree and verify it against the rendered pages. |
| Text PDF | Extract text with positions and reconstruct semantic blocks. |
| Layout PDF | Combine text positions with visual inspection of columns, tables, and captions. |
| Scanned PDF | Run OCR with the document language and verify uncertain text against the page image. |

If the file is encrypted or damaged, report the exact limitation and ask for an accessible source.
Do not bypass document protection.

## Reading order and repetition

Determine columns, sidebars, captions, footnotes, and continuation across pages before joining text.
Remove repeated headers, footers, and page numbers only after confirming that they are page furniture.
Keep a page and region locator for every normalized block.

Do not turn visual proximity into a relationship without evidence.
A caption must remain attached to the correct image or table.
Footnote markers must remain connected to their notes.

## Tables and images

Verify table rows, columns, headers, merged cells, and continuation across pages by looking at the rendered PDF.
When extraction flattens a table or produces ambiguous cells, reconstruct it only from visible evidence and
mark unresolved cells for user verification.

Extract useful figures at sufficient resolution.
Preserve captions and alternative descriptions when present.
Do not publish a full-page screenshot in place of accessible text unless extraction is impossible and the user
accepts that limitation.

## OCR and fidelity

Record the OCR engine, language, and pages processed.
Review low-confidence regions, names, identifiers, formulas, numbers, dates, and units against page images.
Never silently correct uncertain OCR text.

Compare page coverage, block counts, tables, figures, notes, and exact high-risk text before publishing.
