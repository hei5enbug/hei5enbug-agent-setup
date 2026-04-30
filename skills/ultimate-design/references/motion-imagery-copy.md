# Motion, Imagery, and Copy Reference

## Motion Design

Core principle (verbatim):

- "Use motion to create presence and hierarchy, not noise."

Required motion set for visually led work (verbatim requirements):

- one entrance sequence in the hero
- one scroll-linked, sticky, or depth effect
- one hover, reveal, or layout transition that sharpens affordance

### Implementation by stack

**CSS-only (모든 프레임워크 공통, 우선 사용)**:
- `@keyframes` + `animation-delay`로 staggered reveals
- `scroll-timeline` / `view-timeline`으로 scroll-linked 효과 (2025+ 브라우저 지원)
- `transition` + `:hover` / `:focus-visible`로 인터랙션
- `position: sticky`로 storytelling 스크롤

**React (Framer Motion 사용 가능 시)**:
- section reveals (`motion.div` + `whileInView`)
- shared layout transitions (`layoutId`)
- scroll-linked opacity, translate, or scale shifts (`useScroll` + `useTransform`)
- sticky storytelling
- carousels that advance narrative, not just fill space
- menus, drawers, and modal presence effects

**기타 프레임워크**:
- Vue: `<Transition>` / `<TransitionGroup>` + CSS
- Svelte: `transition:` directive + `tweened`/`spring`
- Vanilla JS: Web Animations API (`element.animate()`)

Anthropic motion priority:

- Prioritize CSS-only solutions for HTML.
- Use Motion library for React when available.
- Focus on high-impact moments: one well-orchestrated page load with staggered reveals (`animation-delay`) creates more delight than scattered micro-interactions.

Motion rules (verbatim):

- noticeable in a quick recording
- smooth on mobile
- fast and restrained
- consistent across the page
- removed if ornamental only

## Imagery

Core principle (verbatim):

- "Imagery must do narrative work."

Image direction (verbatim):

- Use at least one strong, real-looking image for brands, venues, editorial pages, and lifestyle products.
- Prefer in-situ photography over abstract gradients or fake 3D objects.
- Choose or crop images with a stable tonal area for text.

Forbidden imagery patterns (verbatim):

- Do not use images with embedded signage, logos, or typographic clutter fighting the UI.
- Do not generate images with built-in UI frames, splits, cards, or panels.
- If multiple moments are needed, use multiple images, not one collage.

Quality gate (verbatim):

- The first viewport needs a real visual anchor. Decorative texture is not enough.

## Copy Strategy

Core principle (verbatim):

- "Write in product language, not design commentary."

Copy rules (verbatim):

- Let the headline carry the meaning.
- Supporting copy should usually be one short sentence.
- Cut repetition between sections.
- Do not include prompt language or design commentary into the UI.
- Give every section one responsibility: explain, prove, deepen, or convert.

Deletion test (verbatim):

- "If deleting 30 percent of the copy improves the page, keep deleting."

## Utility Copy for Product UI

Use utility copy by default for dashboards, admin tools, and operational surfaces.

Critical defaults (verbatim):

- Prioritize orientation, status, and action over promise, mood, or brand voice.
- Start with the working surface itself: KPIs, charts, filters, tables, status, or task context. Do not introduce a hero section unless the user explicitly asks for one.
- If a sentence could appear in a homepage hero or ad, rewrite it until it sounds like product UI.

Additional utility rules (verbatim):

- Section headings should say what the area is or what the user can do there.
- Supporting text should explain scope, behavior, freshness, or decision value in one sentence.
- If a section does not help someone operate, monitor, or decide, remove it.

Litmus check (verbatim):

- "if an operator scans only headings, labels, and numbers, can they understand the page immediately?"
