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

Three approaches, all ending in an attached image.

**Mermaid source: Pele.** The default when the diagram exists as Mermaid source, or when you author a new
document diagram as Mermaid, and a Chromium-based browser is available. See "Mermaid with Pele" below.

**Another diagram language.** Use a renderer for that language when one is available and its default
appearance is good enough.

**Hand-built HTML and CSS.** Start from `assets/diagram-template.html`. Slower to author, but you
control spacing, label placement, and colour, and the result stays consistent across every diagram
in the document. Prefer this when the default rendering is cramped, when labels collide, or when
several diagrams must look like one set.

Either way, `scripts/render_diagrams.mjs` captures the result.

### Mermaid with Pele

Pele renders Mermaid source to SVG in the page that `render_diagrams.mjs` captures.

- **Exact version.** Use `pele@1.8.0`, the version verified for this skill, unless the user names another
  exact version. Reject any plan that loads a version range such as `pele@1` or `^1.8.0`, a dist-tag such as
  `latest`, or a CDN path without a version, and pin the exact version instead. Install it into the staging
  directory with `npm install --save-exact pele@1.8.0` and load `node_modules/pele/dist/pele.global.js`, or use
  `https://cdn.jsdelivr.net/npm/pele@1.8.0/dist/pele.global.js`. Report the version used.
- **Browser API.** Render with `pele.mount(element, source)`, not the server-side `render()`, so text is
  measured with the fonts the page loads. Set `--pele-font` to a stack that covers the document language.
- **Source stays.** Keep the Mermaid source next to the image: in the source document, or as an attachment
  when the page shows only the image.
- **Fallback.** When Pele cannot parse the source, or the image fails "Look at the result", use hand-built
  HTML and CSS, or report the diagram as unresolved. Name the failure in the report.
- **No browser.** Leave the source in place and report that rendering remains.

Page pattern that produced an image with no empty margin:

```html
<style>
  :root { --pele-font: "Apple SD Gothic Neo", "Noto Sans CJK KR", "Malgun Gothic", sans-serif; }
  .diagram { display: inline-block; padding: 16px; background: #fff; }
  .diagram svg { display: block; }
</style>
<div><div id="request-routing" class="diagram"></div></div>
<script src="node_modules/pele/dist/pele.global.js"></script>
<script>
  const sources = { "request-routing": "flowchart LR\n  Client --> Gateway" };
  for (const el of document.querySelectorAll(".diagram")) {
    const mounted = pele.mount(el, sources[el.id]);
    if (mounted.error) el.setAttribute("data-failed", mounted.error.message);
  }
</script>
```

Capture with `--selector ".diagram:not([data-failed])"`.

- The captured element is `inline-block`, so its width comes from the SVG plus its padding. A fixed width,
  such as `width: 900px`, left empty space to the right of the SVG. `svg { display: block }` removes the
  few pixels of line gap below an inline SVG.
- Check the size: the image width must equal (SVG width + 2 × padding) × scale. Read the SVG width from its
  `width` attribute. Measure the image with `scripts/image_size.py`.
- A diagram wider than the capture viewport is scaled down by the page and its text shrinks. When the
  SVG's rendered width is smaller than its `width` attribute, change the direction or split the diagram.
- A source Pele cannot parse does not throw. `mount()` fills the element with the message as red text
  and sets `mounted.error` (`code`, `line`, `message`), and the capture still succeeds and shows only
  that text. Check `mounted.error`, not the capture, and never attach such an image.

### Naming and browser flags

- Give every diagram element an `id` to control its file name. An element without an `id` is captured
  as `diagram-N`, where N is its 1-based position among the matched elements.
- An `id` that is present may contain only letters, digits, `-` and `_`. It becomes the image file
  name, and the script stops before capturing anything when an id is invalid.
- Two elements that would produce the same file name, including a generated `diagram-N` name, stop
  the run before capture. `--strip-prefix` removes a prefix only when the id starts with it, so
  `--strip-prefix dia-` leaves `mydia-x` alone.
- The browser runs with its sandbox on. Pass `--no-sandbox` only in a container or CI image where
  the sandbox cannot start, and say so in the report.
- The browser is closed even when a capture fails, so a failed run leaves no stray process.

## Settings that matter

| Setting | Why |
|---|---|
| Font stack | Pick fonts that cover the document's language. A missing glyph renders as a blank box or a fallback shape, and nothing warns you |
| Device scale factor | Capture above 1 so text stays sharp when the page scales the image down. 2 or 3 works well |
| Element capture | Capture the diagram element rather than the viewport, so the image has no surrounding whitespace |
| Explicit element size | Give a hand-built diagram a definite width and height. An element sized from its content can collapse or stretch unpredictably. A Pele diagram is the exception: size the element from its SVG, as "Mermaid with Pele" describes, because a fixed width adds empty margin |

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
