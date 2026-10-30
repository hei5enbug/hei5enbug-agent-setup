# REPL API gaps

The Aside REPL implements only part of Playwright and Node. Each call below fails in it, and each replacement ran
there on 2026-10-31 with CLI 1.26.1023.

| Need | Fails in the REPL | Use instead |
|---|---|---|
| A delay | `await page.waitForTimeout(ms)` | `await new Promise(r => setTimeout(r, ms))` |
| The text of several elements | `locator.allInnerTexts()`, `locator.allTextContents()` | `await page.locator('h1').evaluateAll(es => es.map(e => e.innerText))`, or `e.textContent` |
| An input by placeholder | `page.getByPlaceholder('Find')` | `page.locator('[placeholder="Find"]')` |
| A role lookup across several elements | `evaluateAll` on `page.getByRole(...)` or a `role=` selector | `evaluateAll` on a CSS selector, such as `'button, [role=button]'` |
| A file write | `fs.writeFileSync(file, data)` | `await fs.writeFile(file, data)`; `fs` is promise-based |

`page.getByRole('heading')` finds no element, even when the page has `h1` elements, while `getByRole('link')` and
`getByRole('button')` work. Select headings with a CSS selector such as `'h1, h2, [role=heading]'`.
