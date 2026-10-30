# REPL에 없는 API

> 영어 원본: [repl-api-gaps.md](../../../../../skills/aside-browser-tasks/references/repl-api-gaps.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Aside REPL은 Playwright와 Node의 일부만 구현한다. 아래 호출은 REPL에서 실패하며, 각 대체 방법은 2026-10-31에
CLI 1.26.1023으로 REPL에서 실행해 확인했다.

| 필요한 일 | REPL에서 실패하는 호출 | 대신 쓸 방법 |
|---|---|---|
| 기다리기 | `await page.waitForTimeout(ms)` | `await new Promise(r => setTimeout(r, ms))` |
| 여러 요소의 텍스트 | `locator.allInnerTexts()`, `locator.allTextContents()` | `await page.locator('h1').evaluateAll(es => es.map(e => e.innerText))` 또는 `e.textContent` |
| placeholder로 입력 칸 찾기 | `page.getByPlaceholder('Find')` | `page.locator('[placeholder="Find"]')` |
| 여러 요소에 걸친 역할(role) 조회 | `page.getByRole(...)`이나 `role=` 선택자에 대한 `evaluateAll` | CSS 선택자에 대한 `evaluateAll`, 예: `'button, [role=button]'` |
| 파일 쓰기 | `fs.writeFileSync(file, data)` | `await fs.writeFile(file, data)`. `fs`는 프로미스 기반이다 |

`page.getByRole('heading')`은 페이지에 `h1` 요소가 있어도 아무 요소도 찾지 못한다. 반면 `getByRole('link')`와
`getByRole('button')`은 동작한다. 제목은 `'h1, h2, [role=heading]'` 같은 CSS 선택자로 고른다.
