# PNG export and verification

### 4.2 PNG Export

Browser viewport size, `100vh` height, and full-page screenshots are not valid final outputs.
The deliverable PNG must be cropped to the rendered visible content and then re-padded with the **same value on all four sides**.

Visible content includes nodes, edges, arrowheads, icons, text, group containers, section titles, and separators.
It excludes browser viewport whitespace, `100vh`-induced page space, CSS layout padding, traces of hidden groups or subtitles, and any leftover `viewBox` margin from a prior layout.

Procedure:

1. Render the SVG/HTML normally.
   Constrain the page shell so it does not introduce empty space larger than the chart, and let the SVG height follow its `viewBox` ratio rather than being forced into the viewport.
2. Render a second pass with the same background but with the SVG visual elements hidden. The goal is a content-free image that shares the original background — including any faint gradient.
3. Diff the two renders to locate the actual content region. Do not crop by background color alone, since white icon fills will be misread as background, and corner-color trimming fails on gradients.
4. Crop the deliverable to that bounding box.
5. Re-pad the crop equally on all four sides. The padding target is "tight but not cramped," chosen once per chart set and reused; the absolute value matters less than its consistency across the set.
6. Save the deliverable with a timestamp postfix appended to the basename so iterative revisions stay traceable.

### 4.3 Verification of the Final PNG

Open the saved PNG and confirm, by eye:

- Top and bottom padding read as equal.
- Left and right padding read as equal.
- No descender, arrowhead, group border, or icon shadow is clipped.
- No empty region remains from a hidden element or a prior layout.

If the rendered PNG is visually unbalanced, do not chase the problem by re-tweaking `viewBox` alone — re-crop the rendered raster against visible content and re-apply equal padding.
Documentation references only the verified PNG; raw viewport captures and pre-verification renders never appear in deliverables.

---
