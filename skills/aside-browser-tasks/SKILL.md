---
name: aside-browser-tasks
description: >-
  Use the user's Aside Browser, with their logged-in sessions, through the on-demand `aside` CLI when the agent's
  own tools cannot finish a browser task: a Jira or Confluence operation the connected tools cannot do, a frontend
  or visual check of a running page, a URL that web fetch cannot open or that needs a login, or a web search or
  reference lookup the built-in search leaves thin. Also use for a site that an Aside site skill covers, such as
  Slack, Gmail, Notion, Google Docs, Sheets, or YouTube, when no connected tool covers it.
compatibility: >-
  Needs the Aside Browser app running on this machine, a signed-in `aside` CLI 1.26.1023 or later, and a shell.
  Measured on macOS.
---

# Aside Browser Tasks

Use this English `SKILL.md` as the only executable source.

Aside is a browser that holds the user's logins. Its `aside` CLI either delegates a task to Aside's own agent
(`aside exec`) or runs Playwright-style JavaScript in the browser (`aside repl`). Each command starts, does its
work, and exits, so nothing keeps running between uses.

## When to use

Try the owned tool first and switch to Aside when it fails, returns too little, or cannot do the task.

| Need | Try first | Aside route |
|---|---|---|
| Jira or Confluence | Connected Atlassian tools | REPL REST fetch; the agent for work only the web UI offers |
| Frontend or design check of a running page | None | REPL snapshot and screenshot |
| URL that web fetch cannot open: 401, 403, login wall, script-rendered, or a local server | Web fetch, or `curl` for a local server's raw HTML | The agent for a specific fact; a REPL snapshot for the whole page |
| Web search or reference lookup | Built-in web search | The agent for a research question; REPL `googleSearch` for raw result links |
| Slack, Gmail, Notion, Google Docs or Sheets, YouTube, LinkedIn | A connected tool for that service | `aside skills show <name>`, then the REPL global it documents |

Tell the user in one line which route you use and why.

## Choose the route

Measured on 2026-10-28 with CLI 1.26.1023:

| Route | Time | Output that reaches the context |
|---|---|---|
| Agent with the final-answer recipe below | 16 to 34 s | The final answer only, about 100 bytes; raw output is 4 to 15 KB of tool trace |
| REPL `fetch` of a site's JSON API with the browser's cookies | 1 to 2 s | Only the fields you print |
| REPL interactive snapshot | About 2 s | About 10 KB |
| REPL full snapshot of an issue page | About 9 s | About 17 KB |
| REPL `googleSearch`, five results | About 10 s | About 1.5 KB |
| REPL screenshot | About 1.5 s | One image read |

- Use the REPL when you know the page, API, or element. It is faster, deterministic, and its output is evidence.
- Use the agent when the path through the site is unknown or spans several pages and you need a short answer.
  It runs Aside's own model, so ask it for source URLs and verify any fact the result depends on.
- Use the REPL whenever you must see the page yourself, such as a visual check.
- Never read raw `aside exec` output into the context; use the recipe below.

## Writes

Every route acts as the user on real sites. Keep a task read-only unless the user asked for that change, and then
follow the host's approval rules for outward writes. State the exact change in the agent prompt. Never send a
mutation through REPL `fetch`; use the site's UI or a connected tool. Never edit Aside settings or memory.

## Agent recipe

```bash
log="$(mktemp)"
aside exec "<task>. Read only; do not change anything. Reply with only <fields> and the source URL." >"$log" 2>&1
id="$(sed -n 's/.*created new session: \([A-Za-z0-9_-]*\).*/\1/p' "$log" | tail -n 1)"
ans=""
[ -n "$id" ] && ans="$(aside repl "const m = await aside.sessions.messages('$id', { limit: 20, order: 'desc' }); const a = m.find(x => x.role === 'assistant'); console.log(typeof a?.content === 'string' ? a.content : (a?.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\n'))" 2>&1)"
if printf '%s\n' "$ans" | grep -v 'ok |' | grep -q '[^[:space:]]' && ! printf '%s\n' "$ans" | grep -q 'error |'; then
  printf '%s\n' "$ans"
else
  echo "aside exec failed (session ${id:-none}):"; tail -n 40 "$log"
fi
rm -f "$log"
```

- The recipe prints only the final answer. When the run fails or returns no answer, it prints the last 40 lines
  of the run's output instead; report that failure.
- Bound the run with the host's command timeout. Run a task that may take longer than a minute in the background
  and give the user a short status about once a minute.
- Continue the same task with `aside session resume <id> "<prompt>"`, extracting the answer the same way; stop it
  with `aside session stop <id>`.

## REPL recipe

Run `aside repl "<code>"` with the whole flow in one call. These limits were each verified:

- Each call is a new session. Variables, the tabs it opened, and attached tabs end with the call, and one call
  has a 120 s limit.
- Pass code as the argument; standard input opens an interactive shell. For a long script, write it to a file
  and run `aside repl "$(cat <file>)"`.
- The exit code is 0 even when the code throws. Treat output that contains `[error |` as a failure.
- Print every result with `console.log()`.
- `page.screenshot`, `page.pdf`, and `fs` write only inside the call's session folder, and the files stay after
  the call. Use a relative path, print `path.resolve(<file>)`, and read the file from that absolute path.
- `page` starts unset. Open a page with `openTab(url)`. For a tab the user already has open, call
  `listBrowserTabs()` and then `attachBrowserTab(targetId)`, and leave that tab open.
- There is no viewport or media emulation. Check a responsive layout with the project's own browser test tools.
- Read with `snapshot(page, { interactive: true })` first, and take `snapshot(page)` only when you need the text.
  Print a snapshot whole; do not cut it.
- `fetch(url)` sends the browser's cookies without opening a tab. Use it only for GET or HEAD requests to the site
  the task names, and print only the fields you need.
- Before using `googleSearch` or a site global such as `slack` or `gmail`, read `aside skills show <name>` and
  follow it. Run one Google query at a time; parallel queries trigger a CAPTCHA.
- For any other API, read `aside guide repl`.

Jira issue through REST:

```bash
aside repl "const r1 = await fetch('https://<site>.atlassian.net/rest/api/3/issue/ABC-123?fields=summary,status,assignee'); const j1 = await r1.json(); console.log(r1.status, j1.fields?.summary, j1.fields?.status?.name, j1.fields?.assignee?.displayName)"
```

Confluence pages use `https://<site>.atlassian.net/wiki/api/v2/pages/<id>?body-format=storage` the same way.

Frontend check:

```bash
aside repl "await openTab('http://localhost:3000/settings'); const s1 = await snapshot(page, { interactive: true }); console.log(s1.tree); await page.screenshot({ path: 'settings.png', fullPage: true }); console.log('saved', path.resolve('settings.png')); console.log(await page.locator('button[type=submit]').evaluate(el => getComputedStyle(el).backgroundColor))"
```

Then read the saved image and judge the layout against the request.

## Failures

- `aside` is missing or reports an unknown command: tell the user and stop; installing or updating the CLI is
  their decision.
- The host sandbox blocks the CLI's connection to the app: rerun with the host's permission escalation.
- A login page appears: report it and ask the user to sign in in Aside; never enter credentials.
