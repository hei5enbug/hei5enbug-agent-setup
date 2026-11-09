# REPL API gaps

The Aside REPL implements only part of Playwright and Node. Each call below fails in it, and each replacement ran
there with CLI 1.26.1023: the first five rows on 2026-10-31, and the rest of this file on 2026-11-03 and 2026-11-04
with build 1.26.1023.1115.

| Need | Fails in the REPL | Use instead |
|---|---|---|
| A delay | `await page.waitForTimeout(ms)` | `await new Promise(r => setTimeout(r, ms))` |
| The text of several elements | `locator.allInnerTexts()`, `locator.allTextContents()` | `await page.locator('h1').evaluateAll(es => es.map(e => e.innerText))`, or `e.textContent` |
| An input by placeholder | `page.getByPlaceholder('Find')` | `page.locator('[placeholder="Find"]')` |
| A role lookup across several elements | `evaluateAll` on `page.getByRole(...)` or a `role=` selector | `evaluateAll` on a CSS selector, such as `'button, [role=button]'` |
| A file write | `fs.writeFileSync(file, data)` | `await fs.writeFile(file, data)`; `fs` is promise-based |
| Text in a rich-text (contenteditable) editor, such as the Aside chat composer | `locator.fill(text)` fails with "Fill did not set the expected contenteditable value" | Paste it: `await box.evaluate((el, t) => { el.focus(); const dt = new DataTransfer(); dt.setData('text/plain', t); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }, text)`, then compare `el.innerText.length` with the text's length |
| Archived Aside chats | `aside.sessions.list({ archived: true })` fails schema validation | `{ archived: 'only' }`; the schema also accepts `'include'` and `'exclude'` |

`page.getByRole('heading')` finds no element, even when the page has `h1` elements, while `getByRole('link')` and
`getByRole('button')` work. Select headings with a CSS selector such as `'h1, h2, [role=heading]'`.

## Aside chats and projects

`aside.projects` offers only `list()`, and `aside.sessions.update(id, { projectId })` returns without moving the
chat; `aside.sessions.update(id, { title })` does rename it. Create projects and move chats on the Aside chats page
instead: open `chrome-extension://<extension ID>/main.html#/u/0/tasks`, or `.../tasks/<session ID>` for one chat.
Read the extension ID from the address bar of an open Aside chats page.

- Create a project: on the chats page, click the `Project` button and then the "Start from scratch" menu item, fill
  `[role=alertdialog] input` with the name, and click "Create". Create one project per call; a second creation in
  the same call could not find the `Project` button.
- Move a chat: on its page, click the first `button[aria-haspopup=menu]`, hover the "Add to project" menu item, and
  click the menu item whose text equals the project name. Then check `(await aside.sessions.get(id)).projectId`.
- Start a chat in a project: on the chats page, click `Project` and then the project's menu item, paste the text
  into `[aria-label="Ask Aside a task, @ for context"]` as the table shows, and press Enter. Aside's agent then runs
  on that text. `aside.sessions` has no merge method; to collect several chats into one, paste their combined record
  this way and tell the agent in the text to only restate it.
