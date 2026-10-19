# Claude Code 에이전트

> 영어 원본: [claude-agents.md](../../../instructions/claude-agents.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

[독립 모델 검증](independent-model-validation.ko.md)이 정한 검토자 호출은 아래 시점, 에이전트 선택, worker 규칙의 예외다.

[공유 모델 라우팅](model-routing.ko.md)은 스킬 검토 역할이나 Skill Builder 참여자를 호출하거나, 독립 검토자를
선정하거나, 메인 모델·프로필 변경이나 세션 재개 후 처음 호출할 때 읽는다. 마지막 경우에는 먼저 실제 설정 검사를
적용한다. 그 밖의 호출에는 이 파일만 필요하다.

## 내장 서브에이전트

- `general-purpose`, `Explore`, `Plan`, `claude`, fork를 포함한 내장 서브에이전트는 사용하지 않는다. 예외는
  `claude-code-guide`와 `statusline-setup`이며, 목적이 좁아 `scout`나 `worker`와 겹치지 않는다. 종류를 비우면
  `general-purpose`가 실행되므로 서브에이전트 종류를 항상 지정한다.
- 플러그인의 에이전트 차단 훅은 종류를 비운 호출과, 위 두 예외를 뺀 모든 내장 종류를 거부한다. 플러그인 에이전트나
  사용자·프로젝트·CLI·관리 설정이 제공하는 정의처럼 그 밖의 모든 종류는 통과시킨다. 호출이 거부되면 맞는 플러그인
  에이전트를 쓰거나 메인 대화에서 작업한다.

## 역할 실행기

scout, researcher, reviewer, Codex worker 역할은 역할 실행기로 실행한다. 할당을 파일로 쓴 뒤 세션 폴더에서 다음을
실행한다. 다른 작업을 이어갈 수 있으면 백그라운드로 실행한다. `<Source directory>`는 세션 컨텍스트의 그 줄이다.

```text
python3 <Source directory>/scripts/role_runner.py <scout|researcher|reviewer|worker> --assignment <file> --result <file>
```

실행기는 역할을 고정된 모델, 사고 강도, 권한으로 실행하고 호스트 기록을 검증한 뒤 JSON 한 줄로 끝난다. 앞에 `cd`를
실행하지 않는다. `--model <id>`는 `reviewer`에만, `--add-dir <dir>`은 `worker`, 쓰기 기능, `write` 에이전트에만 붙인다.

에이전트 모드는 플러그인 에이전트의 다른 모델 계열 대체 항목을 실행하며, 역할 대신 에이전트의 레지스트리 이름이나 설치된 플러그인이
선언한 역할 이름을 받는다.

```text
python3 <Source directory>/scripts/role_runner.py agent --name <name> --fallback --assignment <file> --result <file>
```

`write` 에이전트가 편집할 디렉터리마다 `--add-dir <dir>`을 붙이고, `--mcp`는 할당이 MCP 도구나 네트워크를 쓸 때만 붙인다.

역할 대신 레지스트리의 기능 이름(capability)을 받을 수도 있다. 이때 `--instructions <file>`이 역할 정의를 대신한다.
실행기는 [기능별 고정값 표](model-routing.ko.md)가 `--host claude|codex`에 맞게 고르는 항목을 실행한다.
`--host`를 생략하면 `CODEX_THREAD_ID`가 있을 때 `codex`, 없을 때 `claude`를 쓴다. `--fallback`은 대체 항목을 고른다.
고른 항목이 `via: runner`가 아니면 실행기는 종료 코드 2를 반환하므로 agent 경로나 메인 대화에서 계속한다.
`--resume <session_id>`는 상태 줄의 `evidence.session`으로 Claude 또는 Codex 실행을 이어 가며, 같은 모델, 사고 강도,
샌드박스 설정을 쓴다.

| 종료 코드 | 처리 |
|---|---|
| 0 | 결과 파일을 받아들인다. |
| 2 | 호출을 고쳐 다시 실행한다. |
| 3 또는 4 | 결과 파일을 읽지 않고 아래 대체 경로를 쓴다. |

| 역할 | 종료 코드 3 또는 4일 때 대체 경로 |
|---|---|
| `scout` | `hei5enbug-agent-setup:scout` |
| `researcher` | 공개 검색·가져오기 도구를 사용할 수 있을 때만 `hei5enbug-agent-setup:scout` |
| 스킬 검토 역할의 `reviewer` | `hei5enbug-agent-setup:reviewer` |
| 독립 검증의 `reviewer` | 없음. 독립 검증을 수행하지 못했다고 보고한다. |
| `worker` | 부분 diff를 살펴본 뒤 `hei5enbug-agent-setup:worker` |

대체 경로도 쓸 수 없으면 메인 대화에서 계속한다.

## 기능 실행

기능 항목은 [capability 표](model-routing.ko.md#기능별-고정값)에서 `claude` 항목을 찾는다. 기능은 `investigation`,
`implementation`, `design`, `language`, `review` 다섯 개다. 아래 '대체' 절의 대체 규칙을 적용한다.

[기능별 고정값 표](model-routing.ko.md#기능별-고정값)에서 Claude Code 쪽 해당 기능 항목을 찾는다.

- `via: runner`: `--instructions <file>`을 붙여 위의 역할 실행기로 기능을 실행한다.
- `via: agent`: 항목의 `agent` 필드에 적힌 에이전트를 띄운다. `pin`은 그 항목이 쓰는 에이전트 고정값을 가리킨다.
  실행이 실패하면 그 에이전트의 다음 시작은 한 번 거부되며, 거부 이유에 역할 실행기의 대체 명령이 적힌다.
- 그 경로가 실패하면 기능의 대체 항목을 한 번 쓰고, 그래도 안 되면 메인 대화에서 계속한다.

## 대체

모든 대체 항목은 다른 모델 계열이다. 다른 호스트의 모델이 필요한 대체 항목은 역할 실행기를 거치고, 현재 호스트에서 바로 실행할
수 있는 대체 항목은 이름이 붙은 에이전트를 쓴다. 플러그인 에이전트의 다른 계열 대체는 `role_runner.py agent --name <name> --fallback`으로,
기능의 `via: runner` 대체는 `role_runner.py <capability> --fallback`으로 실행한다. `--mcp`는 할당이 MCP 도구나 네트워크를 쓸 때만
붙인다. 실행기가 종료 코드 3 또는 4로 끝나면 메인 대화에서 계속한다.

## 조사

- 세션의 위임 규칙이 선택한 범위가 한정된 조사는 계획 중이든 실행 중이든 `scout` 역할로 실행한다. 각 scout에 질문 하나와
  좁은 검색 범위 하나를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 대화에서 확인한다.
- 범위가 한정된 공개 조사는 capability 표의 `investigation` 기능 경로를 쓴다. 그 Claude 대체 항목은 웹 검색과 가져오기
  도구를 가진 `scout` 에이전트다. 조건을 충족하지 못하면 메인 대화에서 계속한다.

## 스킬 작업자

- 스킬이 맡긴 검토 역할(검토 페르소나, grader, comparator, analyzer)은 읽기 전용 판단 작업이다. 세션 줄 "Review model"의
  모델을 `--model`로 지정해 `reviewer` 역할을 실행한다.
- 독립 검증은 독립 모델 검증에 따른 확인 게이트를 통과한 뒤, 그 파일이 고른 검토자를 `--model`로 지정해 `reviewer` 역할로
  실행한다. Claude가 작성한 결과라면 "Review model" 줄의 모델이다.
- 로컬 근거 조사 티켓과 공개 자료 조사는 `investigation` 기능으로 맡긴다. 검토 역할에는 `scout`를 사용하지
  않는다. 비공개·인증 원격 접근과 이슈 트래커, 풀 리퀘스트 서비스 같은 외부 도구 작업은 `implementation` 기능으로,
  수정은 스킬이 지정한 기능 작업자로 보낸다. 그 밖에는 메인 대화에서 처리한다.
- Skill Builder의 시험 실행과 기타 비검토 참여자에는 평가 어댑터에서 호스트의 상위 모델을 사용한다. 시험 출력을
  쓰는 작업자는 서브에이전트 대신 스킬이 지정한 모델과 사고 강도로 별도 `claude -p` 프로세스를 실행한다.

## 구현

위임한 구현은 [구현 위임 규칙](implementation-delegation.ko.md)에 따라 조정한다. 이 섹션은 Claude Code worker 연동만 덧붙인다.

- 위임한 구현은 세션 줄 "Implementation worker route"에 지정된 경로를 따른다. 줄이 `sonnet`이면 Sonnet worker인
  `hei5enbug-agent-setup:sonnet-worker`, `codex`이면 Codex worker(아래 "Codex worker" 참조), `haiku`이면
  `hei5enbug-agent-setup:worker`, `sol`이면 Sol worker(아래 "Sol worker" 참조)를 쓴다.
  `auto`이면 할당마다 고른다. 쉬운 작업(수정 내용이 명시되고 검사로 전체를 확인할 수 있는 하나의 일관된 변경)은 `worker` 에이전트,
  보통이거나 어려운 작업(동작 변경, 여러 파일, 파싱, 보안 또는 동시성)은 Sol을 쓴다. Codex 주간 사용률이 70퍼센트를
  넘거나 Sol을 사용할 수 없으면 Sol 대신 Sonnet을 쓴다. 사용률은 [독립 모델 검증](independent-model-validation.ko.md)과
  같은 방식으로 읽는다. Claude 경로가 사용량 한도로 중단되면 Sol을 쓴다. 사용자가 한 경로를 요청하면 그 요청에만 적용한다.
  UI 코드, 시각 디자인, 다이어그램 작업은 여전히 `hei5enbug-agent-setup:designer`가 맡는다. 다만 Claude Code 세션 파일이
  메인 세션에 맡긴 종류는 예외다. 그 밖의 에이전트는 쓰지 않는다.
- `worker` 에이전트는 세션 줄 "Worker agent model"에 적힌 모델과 사고 강도로 실행한다(기본값은 Haiku, `high`).
- 호출 단위 모델은 정의보다 우선하므로 플러그인 에이전트를 호출하거나 재개할 때 넘기지 않는다. 정의에는 공유 모델
  라우팅이 정리한 모델과 사고 강도가 고정되어 있다.
- 아래 항목은 플러그인 에이전트가 실행될 때마다 적용한다. 실행기의 대체 경로, `worker`와 Sonnet worker, designer가 해당한다.
- 세션 컨텍스트에 `hei5enbug-agent-setup mod: role pinning active` 줄이 있으면 등록된 플러그인 mod의
  `prompt.context` 훅이 역할 고정 활성 상태를 확인한 것이다. mod는 서브에이전트 요청마다 레지스트리와 설치된 플러그인이 선언한
  `model-roles.json`에서 각 역할의 모델과 사고 강도를 고정한다. 다른 모델이 응답했거나 모델 증거가 없는 실행은 실패로 처리되어
  그 뒤의 턴이 거절되고, mod는 다른 모델로 응답한 서브에이전트의 도구 호출을 막는다. 실패한 실행의 결과는 경고로 바뀌고, 그 역할의
  다음 시작은 한 번 거부되며 거부 이유에 역할 실행기의 대체 명령이 적힌다. 그 뒤의 시작은 다시 기본 고정을 쓴다. Agent 호출이 오류를 반환했거나 마지막 턴이 오류로 끝난 실행도 같은
  방식으로 실패로 기록하되, 그 오류 결과는 그대로 둔다. 세션당 한 번만 환경 변수와 모든
  설정 파일에서 강제 모델과 사고 강도 한도(`CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  `CLAUDE_CODE_EFFORT_LEVEL` 같은 사고 강도 재정의, `maxEffortLevel`이나 조직 한도 같은 사고 강도 상한)만 확인한다.
  강제 모델이나 고정 사고 강도보다 낮은 상한이 있으면 플러그인 에이전트 위임을 멈춘다. 그렇지 않으면 할당을 바로
  보낸다. Mod의 고정과 차단이 수락 근거이므로 위임마다 설정이나 서브에이전트 기록을 읽지 않는다.
- 그 줄이 없으면 시작 결과에 모델이 나오지 않는다. 실행에서 처음 호출하기 전에 위의 비밀이 아닌 입력과 에이전트 정의,
  대체나 폴백 경고만 살펴보고, 구현 위임 규칙의 준비 확인 경로를 따른다. Claude Code는 세션 도중에 설정을 다시 읽을
  수 있으므로 구현 작업을 담은 후속 메시지를 보낼 때마다 다시 확인한다.
- mod가 없으면 `/tasks`나 서브에이전트 transcript 같은 호스트 기록을 호출한 정의의 고정 모델과 사고 강도를 기록할 때만
  인정한다. 그 기록은 Claude 설정 디렉터리(`CLAUDE_CONFIG_DIR` 또는 `~/.claude`)의
  `projects/<project>/<session-id>/subagents/agent-<agentId>.jsonl`에서 읽고, 각 assistant 항목의 `model`과 `effort`가
  맞아야 한다. 제공자 내부의 추론 원격 측정은 필요하지 않다. 기록된 모델이 다르거나, 고정된 사고 강도보다 낮은 상한,
  모순된 재정의, 알 수 없는 실제 우선순위가 있으면 근거로 부족하다.
- 호스트 한도는 `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`다. 실행 중인 서브에이전트는 세지만 메인 세션은 세지 않는다.
  현재 값과 남은 자리를 기준으로 하고 이 값을 바꾸지 않는다.
- 플러그인 worker나 서브에이전트 기록이 없으면 해당 위임을 멈추고 세션의 대체 처리 규칙을 적용한다.
  사용자 설정은 바꾸지 않는다.

## Sol worker

- 일반 할당 항목을 담은 할당을 파일로 쓰고, 허용된 경로가 있는 폴더에서
  `python3 <Source directory>/scripts/role_runner.py implementation --fallback --instructions
  <Source directory>/agents/worker.md --assignment <file> --result <file>`을 실행한다. 공유 모델 라우팅의 기능별 표가
  Claude Code 대체 항목으로 지정한 모델을 실행하며, 해당 폴더에 쓰기 권한을 부여한다.
- 작업이 써야 하는 해당 폴더 밖 디렉터리에만 `--add-dir <dir>`을 붙인다. 승인 가드는 세션 쓰기 승인을 한 번 묻는다.

## Codex worker

- 일반 할당 항목을 담은 할당을 파일로 쓰고 `worker` 역할을 실행한다.
- 작업이 써야 하는 세션 폴더 밖 디렉터리에만 `--add-dir <dir>`을 붙인다. 플러그인 Mod는 세션당 한 번 묻는다.
