# REPL에 없는 API

> 영어 원본: [repl-api-gaps.md](../../../../../skills/aside-browser-tasks/references/repl-api-gaps.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Aside REPL은 Playwright와 Node의 일부만 구현한다. 아래 호출은 REPL에서 실패하며, 각 대체 방법은
CLI 1.26.1023으로 REPL에서 실행해 확인했다. 처음 다섯 행은 2026-10-31에 확인했고, 이 파일의 나머지 내용은
2026-11-03과 2026-11-04에 빌드 1.26.1023.1115로 확인했다.

| 필요한 일 | REPL에서 실패하는 호출 | 대신 쓸 방법 |
|---|---|---|
| 기다리기 | `await page.waitForTimeout(ms)` | `await new Promise(r => setTimeout(r, ms))` |
| 여러 요소의 텍스트 | `locator.allInnerTexts()`, `locator.allTextContents()` | `await page.locator('h1').evaluateAll(es => es.map(e => e.innerText))` 또는 `e.textContent` |
| placeholder로 입력 칸 찾기 | `page.getByPlaceholder('Find')` | `page.locator('[placeholder="Find"]')` |
| 여러 요소에 걸친 역할(role) 조회 | `page.getByRole(...)`이나 `role=` 선택자에 대한 `evaluateAll` | CSS 선택자에 대한 `evaluateAll`, 예: `'button, [role=button]'` |
| 파일 쓰기 | `fs.writeFileSync(file, data)` | `await fs.writeFile(file, data)`. `fs`는 프로미스 기반이다 |
| Aside 채팅 입력창 같은 리치 텍스트(contenteditable) 편집기에 텍스트 입력 | `locator.fill(text)`는 "Fill did not set the expected contenteditable value" 오류로 실패한다 | 붙여 넣는다: `await box.evaluate((el, t) => { el.focus(); const dt = new DataTransfer(); dt.setData('text/plain', t); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }, text)`. 그런 다음 `el.innerText.length`와 텍스트 길이를 비교한다 |
| 보관된 Aside 채팅 | `aside.sessions.list({ archived: true })`는 스키마 검증에 실패한다 | `{ archived: 'only' }`. 스키마는 `'include'`와 `'exclude'`도 허용한다 |

`page.getByRole('heading')`은 페이지에 `h1` 요소가 있어도 아무 요소도 찾지 못한다. 반면 `getByRole('link')`와
`getByRole('button')`은 동작한다. 제목은 `'h1, h2, [role=heading]'` 같은 CSS 선택자로 고른다.

## Aside 채팅과 프로젝트

`aside.projects`는 `list()`만 제공하며, `aside.sessions.update(id, { projectId })`는 채팅을 옮기지 않고 반환한다.
`aside.sessions.update(id, { title })`은 이름을 바꾼다. 프로젝트 생성과 채팅 이동은 대신 Aside 채팅 페이지에서 한다.
`chrome-extension://<extension ID>/main.html#/u/0/tasks`를 열거나, 채팅 하나를 열려면 `.../tasks/<session ID>`를 연다.
확장 프로그램 ID는 열려 있는 Aside 채팅 페이지의 주소 표시줄에서 읽는다.

- 프로젝트 생성: 채팅 페이지에서 `Project` 버튼을 누른 뒤 "Start from scratch" 메뉴 항목을 누른다.
  `[role=alertdialog] input`에 이름을 입력하고 "Create"를 누른다. 호출 하나당 프로젝트 하나만 만든다.
  같은 호출에서 두 번째 생성을 시도했을 때는 `Project` 버튼을 찾지 못했다.
- 채팅 이동: 해당 채팅 페이지에서 첫 번째 `button[aria-haspopup=menu]`를 누르고 "Add to project" 메뉴 항목에
  마우스를 올린 뒤, 텍스트가 프로젝트 이름과 같은 메뉴 항목을 누른다.
  그런 다음 `(await aside.sessions.get(id)).projectId`를 확인한다.
- 프로젝트에서 채팅 시작: 채팅 페이지에서 `Project`를 누른 뒤 해당 프로젝트의 메뉴 항목을 누른다.
  표에 나온 방법으로 `[aria-label="Ask Aside a task, @ for context"]`에 텍스트를 붙여 넣고 Enter를 누른다.
  그러면 Aside 에이전트가 그 텍스트를 바탕으로 실행된다. `aside.sessions`에는 병합 메서드가 없다. 여러 채팅을
  하나로 모으려면 합친 기록을 이 방법으로 붙여 넣고, 텍스트 안에 그 기록을 다시 말하기만 하라는 지시를 넣는다.
