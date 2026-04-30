# Web Quality (🔍 Audit Mode)

This module synthesizes web quality guidance from the web-quality-audit, performance, core-web-vitals, accessibility, SEO, and best-practices skills.

## Web Quality Audit Overview

### 5 audit categories

1. Core Web Vitals
2. Performance
3. Accessibility
4. SEO
5. Best Practices

### Trigger phrases

Use this audit mode when prompts include:

- "audit my site"
- "review web quality"
- "run lighthouse audit"
- "check page quality"
- "optimize my website"
- "speed up my site" / "optimize performance" / "reduce load time"
- "improve Core Web Vitals" / "fix LCP" / "reduce CLS" / "optimize INP"
- "improve accessibility" / "a11y audit" / "WCAG compliance"
- "improve SEO" / "fix meta tags" / "add structured data"
- "apply best practices" / "security audit" / "modernize code"

## Core Web Vitals

### Targets

| Metric | Target | Why it matters |
|---|---:|---|
| LCP | < 2.5s | Fast perceived loading |
| INP | < 200ms | Responsive interactions |
| CLS | < 0.1 | Visual stability |

### Optimization patterns (with code)

#### LCP: prioritize hero asset and remove render blocking

```html
<link rel="preload" href="/hero.avif" as="image" fetchpriority="high">
<img src="/hero.avif" alt="Hero" fetchpriority="high" loading="eager" width="1600" height="900">

<style>
  /* critical above-the-fold css */
</style>
<link rel="preload" href="/app.css" as="style" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link rel="stylesheet" href="/app.css"></noscript>
```

#### INP: break long tasks and defer non-critical work

```javascript
button.addEventListener('click', () => {
  button.classList.add('is-loading');

  requestAnimationFrame(() => {
    runImportantUiUpdate();
  });

  requestIdleCallback(() => {
    sendAnalytics();
  });
});

async function processInChunks(items, size = 100) {
  for (let i = 0; i < items.length; i += size) {
    items.slice(i, i + size).forEach(expensiveOperation);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}
```

#### CLS: reserve layout space for variable content

```html
<img src="/photo.webp" alt="Product" width="800" height="600" loading="lazy" decoding="async">

<div class="embed-shell">
  <iframe src="https://www.youtube.com/embed/abc" title="Product demo" loading="lazy"></iframe>
</div>
```

```css
.embed-shell {
  aspect-ratio: 16 / 9;
}

.embed-shell iframe {
  width: 100%;
  height: 100%;
  border: 0;
}
```

## Performance

### Critical rendering path

- Keep TTFB under 800ms with CDN, caching, and efficient backend responses.
- Preconnect third-party origins and preload critical LCP assets.
- Inline critical CSS and defer non-critical CSS/JS.
- Avoid render-blocking scripts in `<head>` unless absolutely required.

### JS bundling

- Apply route-, component-, and feature-level code splitting.
- Remove unused JavaScript and tree-shake imports.
- Defer or async-load non-essential scripts.
- Keep long tasks under 50ms on the main thread.

### Image optimization

- Prefer AVIF/WebP with JPEG/PNG fallbacks.
- Use `srcset` + `sizes` for responsive delivery.
- Use eager + high-priority loading for LCP image; lazy-load below fold.
- Always provide intrinsic dimensions to prevent layout shifts.

### Font loading

- Use `font-display: swap` or `optional` depending on UX sensitivity.
- Preload critical fonts only.
- Subset glyph ranges where possible.
- Prefer variable fonts when it reduces total transfer.

### Caching

- Hashed static assets: `Cache-Control: public, max-age=31536000, immutable`.
- HTML: short/no-cache with revalidation.
- Use stale-while-revalidate where appropriate.
- Add service worker caching for stable static resources when product goals justify it.

## Performance Budget

| Resource | Budget |
|---|---:|
| Total page weight | < 1.5MB |
| JavaScript (compressed) | < 300KB |
| CSS (compressed) | < 100KB |
| Images (above fold) | < 500KB |
| Fonts | < 100KB |

## Accessibility

### WCAG 2.2 POUR principles

- Perceivable: text alternatives, contrast, captions/transcripts.
- Operable: keyboard accessibility, visible focus, no traps, target sizing.
- Understandable: clear labels, consistent navigation, clear errors.
- Robust: semantic HTML first, valid ARIA usage only when needed.

### Required checkpoints

- Contrast: 4.5:1 minimum for normal text, 3:1 for large text/UI graphics.
- Keyboard navigation: every action reachable and usable via keyboard.
- ARIA: do not replace native elements with ARIA-only patterns.
- Form labels: every input has a programmatically associated label.
- Motion: support `prefers-reduced-motion`.

## SEO

### Crawlability

- Valid `robots.txt` that does not block critical render resources.
- XML sitemap with canonical, indexable URLs submitted to Search Console.
- Correct canonical URLs to reduce duplicate content.
- Ensure important pages are not `noindex`.

### Meta tags and indexing signals

- Unique, descriptive `<title>` per page (roughly 50-60 chars).
- Unique meta descriptions (roughly 150-160 chars).
- Logical heading hierarchy with one primary `<h1>`.
- Mobile viewport correctly configured.

### Structured data (JSON-LD)

Use schema types relevant to page intent (e.g., `Organization`, `Article`, `Product`, `FAQPage`, `BreadcrumbList`).

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Example Company",
  "url": "https://example.com"
}
</script>
```

### Mobile-friendliness

- Responsive layouts and readable defaults.
- Tap targets at least 48px in typical mobile contexts.
- No intrusive interstitials on mobile.

## Best Practices

### HTTPS and transport security

- Enforce HTTPS and eliminate mixed content.
- Enable HSTS in production.

### Security headers

Apply and validate:

- `Content-Security-Policy`
- `Strict-Transport-Security`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Permissions-Policy`

### Modern APIs and code quality

- Replace deprecated APIs (`document.write`, sync XHR, appcache).
- Use passive listeners for scroll/touch when possible.
- Remove production console noise and handle runtime errors cleanly.
- Keep dependencies updated and audit vulnerabilities regularly.

## Lighthouse Targets

| Category | Target |
|---|---:|
| Performance | >= 90 |
| Accessibility | 100 |
| Best Practices | >= 95 |
| SEO | >= 95 |

## Framework-Specific Notes

### React / Next.js

- Use SSR/SSG/streaming for LCP-critical content.
- Lazy-load heavy routes/components (`React.lazy`, dynamic import).
- Memoize expensive trees to reduce INP regressions.
- Ensure image dimensions are explicit (or framework image components enforce them).

### Vue / Nuxt

- Use async components for large features.
- Preload LCP media and keep route bundles lean.
- Use semantic templates and robust form labeling by default.

### Svelte / SvelteKit

- Minimize hydration work and split browser-only heavy modules.
- Reserve dimensions for dynamic media to prevent CLS.
- Favor compile-time optimizations and simple reactive boundaries.

### Astro

- Keep pages mostly static where possible and hydrate only interactive islands.
- Use partial hydration directives intentionally (`client:visible`, `client:idle`).
- Preload key assets for LCP sections.

### Static HTML (no framework)

- Inline critical CSS, defer non-critical assets, and avoid parser-blocking scripts.
- Use semantic landmarks (`header`, `nav`, `main`, `footer`) for accessibility and SEO.
- Add JSON-LD, canonical, sitemap, and robust caching headers.
