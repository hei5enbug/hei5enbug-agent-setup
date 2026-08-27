# Diagrams

Diagram source published as text stays text. Confluence renders a fenced diagram block as a code
block, so every diagram has to become an image before it reaches the page.

## Decide the route

| Situation | Route |
|---|---|
| The space has a working diagram macro and the user wants live source | Use the macro, and verify it renders on the saved page |
| No macro, or the macro fails for anyone | Render to an image and attach it |
| No headless browser available | Leave the source in place and tell the user rendering is still required |

A diagram macro that depends on an installed app can be broken for the whole organisation and you
cannot fix that from here. Check that it renders before committing to it. If it does not, switch
to images rather than reporting the page as done.

## Rendering to an image

Two approaches, both ending in an attached image.

**Diagram-language renderer.** Fastest when the diagram already exists as source and its default
appearance is good enough.

**Hand-built HTML and CSS.** Start from `assets/diagram-template.html`. Slower to author, but you
control spacing, label placement, and colour, and the result stays consistent across every diagram
in the document. Prefer this when the default rendering is cramped, when labels collide, or when
several diagrams must look like one set.

Either way, `scripts/render_diagrams.mjs` captures the result.

## Settings that matter

| Setting | Why |
|---|---|
| Font stack | Pick fonts that cover the document's language. A missing glyph renders as a blank box or a fallback shape, and nothing warns you |
| Device scale factor | Capture above 1 so text stays sharp when the page scales the image down. 2 or 3 works well |
| Element capture | Capture the diagram element rather than the viewport, so the image has no surrounding whitespace |
| Explicit element size | Give the captured container a definite width and height. An element sized from its content can collapse or stretch unpredictably |

## Look at the result

**This step is not optional and no script can replace it.**

Load every rendered image and check it:

- Labels that overlap each other or a connector.
- Text clipped at an element edge.
- Glyphs that failed to render.
- Connectors that end in the wrong place.
- Whitespace around the drawing.

These are all invisible to a dimension check and to body validation. They are only visible in the
picture.

If the host cannot display an image to you, say so plainly and ask the user to check before you
publish. Do not publish an image you could not see.

## Iterating

Fix the source, re-render, look again. Upload under the same file name so the attachment gains a
version and the body keeps working. Update the `height` in the body only if the aspect ratio
changed.

## Consistency across a document

Within one document, keep the same shape language, the same colour meaning, the same font, and the
same connector style. A reader learns the visual code once.

The colours in the template are a starting point. Any consistent scheme is fine, as long as the
same colour means the same thing in every diagram of the document.
