# Aside Browser 작업

> 영어 원본: [SKILL.md](../../../../skills/aside-browser-tasks/SKILL.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

에이전트 자체 도구로 브라우저 작업을 끝낼 수 없을 때, 필요할 때만 실행하는 `aside` CLI를 통해 사용자가 로그인해 둔
Aside Browser를 사용한다. 연결된 도구로 할 수 없는 Jira나 Confluence 작업, 실행 중인 페이지의 프런트엔드나 시각적 검사,
웹 가져오기로 열 수 없거나 로그인이 필요한 URL, 내장 검색만으로는 정보가 부족한 웹 검색이나 참고 자료 조회가 해당한다.
Slack, Gmail, Notion, Google Docs, Sheets, YouTube처럼 Aside 사이트 스킬이 다루는 사이트에 연결된 도구가 없을 때도 사용한다.

이 컴퓨터에서 Aside Browser 앱이 실행 중이어야 하며, 로그인된 `aside` CLI 1.26.1023 이상과 셸이 필요하다.
macOS에서 측정했다.

이 영어 `SKILL.md`만 실행 원본으로 사용한다.

Aside는 사용자의 로그인 상태를 유지하는 브라우저다. `aside` CLI는 Aside 자체 에이전트에 작업을 맡기거나
(`aside exec`), 브라우저에서 Playwright 스타일 JavaScript를 실행한다(`aside repl`).
각 명령은 시작해서 작업을 마치고 종료하므로, 사용 사이에 계속 실행되는 것은 없다.

## 사용 시점

해당 작업을 담당하는 도구를 먼저 시도하고, 실패하거나 결과가 부족하거나 작업을 수행할 수 없으면 Aside로 전환한다.

| 필요한 작업 | 먼저 시도할 도구 | Aside 경로 |
|---|---|---|
| Jira나 Confluence | 연결된 Atlassian 도구 | REPL REST fetch. 웹 UI에서만 가능한 작업은 에이전트 |
| 실행 중인 페이지의 프런트엔드나 디자인 검사 | 없음 | REPL 스냅샷과 스크린샷 |
| 웹 가져오기로 열 수 없는 URL: 401, 403, 로그인 장벽, 스크립트 렌더링 페이지, 로컬 서버 | 웹 가져오기. 로컬 서버의 원시 HTML에는 `curl` | 특정 사실은 에이전트, 전체 페이지는 REPL 스냅샷 |
| 웹 검색이나 참고 자료 조회 | 내장 웹 검색 | 조사 질문은 에이전트, 원시 검색 결과 링크는 REPL `googleSearch` |
| Slack, Gmail, Notion, Google Docs나 Sheets, YouTube, LinkedIn | 해당 서비스에 연결된 도구 | `aside skills show <name>`을 읽은 뒤 거기에 설명된 REPL 전역 객체 |

사용하는 경로와 그 이유를 사용자에게 한 줄로 알린다.

## 경로 선택

2026-10-28에 CLI 1.26.1023으로 측정했다.

| 경로 | 시간 | 컨텍스트에 들어오는 출력 |
|---|---|---|
| 아래 최종 답변 절차를 적용한 에이전트 | 16~34 s | 약 100 bytes의 최종 답변만 들어온다. 원시 출력은 4~15 KB의 도구 실행 기록이다 |
| 브라우저 쿠키로 사이트 JSON API를 호출하는 REPL `fetch` | 1~2 s | 출력한 필드만 들어온다 |
| REPL 대화형 스냅샷 | 약 2 s | 약 10 KB |
| 이슈 페이지의 REPL 전체 스냅샷 | 약 9 s | 약 17 KB |
| REPL `googleSearch`, 결과 다섯 개 | 약 10 s | 약 1.5 KB |
| REPL 스크린샷 | 약 1.5 s | 이미지 읽기 한 번 |

- 페이지, API, 요소를 알고 있으면 REPL을 사용한다. 더 빠르고 결정적이며, 출력이 증거가 된다.
- 사이트 안에서 어떤 경로로 이동해야 할지 모르거나 여러 페이지에 걸쳐 있고 짧은 답변이 필요하면 에이전트를 사용한다.
  Aside 자체 모델로 실행되므로, 출처 URL을 요청하고 결과의 근거가 되는 사실을 검증한다.
- 시각적 검사처럼 페이지를 직접 봐야 할 때는 항상 REPL을 사용한다.
- 원시 `aside exec` 출력을 컨텍스트로 읽지 않는다. 아래 절차를 사용한다.

## 쓰기

모든 경로는 실제 사이트에서 사용자 권한으로 동작한다. 사용자가 변경을 요청한 경우가 아니면 작업을 읽기 전용으로 유지한다.
변경을 요청했다면 외부 쓰기에 대한 호스트의 승인 규칙을 따른다. 에이전트 프롬프트에 정확한 변경 내용을 명시한다.
REPL `fetch`로 변경 요청을 보내지 않는다. 사이트 UI나 연결된 도구를 사용한다. Aside 설정이나 메모리는 절대 수정하지 않는다.

## 에이전트 실행 절차

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

- 이 절차는 최종 답변만 출력한다. 실행이 실패하거나 답변이 없으면 대신 실행 출력의 마지막 40줄을 출력하므로, 그 실패를 보고한다.
- 실행 시간은 호스트의 명령 제한 시간으로 제한한다. 1분보다 오래 걸릴 수 있는 작업은 백그라운드에서 실행하고,
  약 1분마다 사용자에게 짧게 진행 상황을 알린다.
- `aside session resume <id> "<prompt>"`로 같은 작업을 이어 가고 같은 방법으로 답변을 추출한다.
  `aside session stop <id>`로 중지한다.

## REPL 실행 절차

전체 흐름을 한 번의 `aside repl "<code>"` 호출로 실행한다. 다음 제약은 각각 검증했다.

- 호출마다 새 세션이다. 변수, 호출에서 연 탭, 연결한 탭은 호출이 끝나면 종료되며, 한 번의 호출에는 120 s 제한이 있다.
- 코드는 인자로 전달한다. 표준 입력을 사용하면 대화형 셸이 열린다.
  긴 스크립트는 파일에 쓴 뒤 `aside repl "$(cat <file>)"`로 실행한다.
- 코드에서 예외가 발생해도 종료 코드는 0이다. 출력에 `[error |`가 있으면 실패로 처리한다.
- 모든 결과를 `console.log()`로 출력한다.
- `page.screenshot`, `page.pdf`, `fs`는 해당 호출의 세션 폴더 안에만 파일을 쓰며, 호출이 끝나도 파일은 남는다.
  상대 경로를 사용하고 `path.resolve(<file>)`을 출력한 뒤, 그 절대 경로에서 파일을 읽는다.
- `page`는 처음에 설정되어 있지 않다. `openTab(url)`로 페이지를 연다.
  사용자가 이미 열어 둔 탭은 `listBrowserTabs()`를 호출한 뒤 `attachBrowserTab(targetId)`로 연결하고, 그 탭을 열어 둔다.
- 뷰포트나 미디어 에뮬레이션은 없다. 반응형 레이아웃은 프로젝트 자체 브라우저 테스트 도구로 검사한다.
- 먼저 `snapshot(page, { interactive: true })`로 읽고, 텍스트가 필요할 때만 `snapshot(page)`를 가져온다.
  스냅샷은 자르지 말고 전체를 출력한다.
- `fetch(url)`은 탭을 열지 않고 브라우저 쿠키를 보낸다.
  작업에서 지정한 사이트에 대한 GET이나 HEAD 요청에만 사용하고, 필요한 필드만 출력한다.
- `googleSearch`나 `slack`, `gmail` 같은 사이트 전역 객체를 사용하기 전에 `aside skills show <name>`을 읽고 따른다.
  Google 쿼리는 한 번에 하나만 실행한다. 병렬 쿼리는 CAPTCHA를 유발한다.
- 기다리기, 여러 요소의 텍스트 읽기, placeholder나 역할(role)로 요소 찾기, 파일 쓰기를 하는 REPL 코드를 쓰기 전에
  `references/repl-api-gaps.md`를 읽는다.
- 다른 API는 `aside guide repl`을 읽는다.

REST로 Jira 이슈 조회:

```bash
aside repl "const r1 = await fetch('https://<site>.atlassian.net/rest/api/3/issue/ABC-123?fields=summary,status,assignee'); const j1 = await r1.json(); console.log(r1.status, j1.fields?.summary, j1.fields?.status?.name, j1.fields?.assignee?.displayName)"
```

Confluence 페이지도 같은 방식으로 `https://<site>.atlassian.net/wiki/api/v2/pages/<id>?body-format=storage`를 사용한다.

프런트엔드 검사:

```bash
aside repl "await openTab('http://localhost:3000/settings'); const s1 = await snapshot(page, { interactive: true }); console.log(s1.tree); await page.screenshot({ path: 'settings.png', fullPage: true }); console.log('saved', path.resolve('settings.png')); console.log(await page.locator('button[type=submit]').evaluate(el => getComputedStyle(el).backgroundColor))"
```

그런 다음 저장된 이미지를 읽고 요청에 맞는 레이아웃인지 판단한다.

## 실패 처리

- `aside`가 없거나 알 수 없는 명령이라고 보고하면 사용자에게 알리고 중지한다. CLI 설치나 업데이트는 사용자가 결정한다.
- 호스트 샌드박스가 CLI와 앱의 연결을 막으면 호스트의 권한 상승 절차로 다시 실행한다.
- 로그인 페이지가 나타나면 보고하고 사용자에게 Aside에서 로그인해 달라고 요청한다. 자격 증명을 직접 입력하지 않는다.
