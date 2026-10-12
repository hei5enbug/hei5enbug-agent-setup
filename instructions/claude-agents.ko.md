# Claude Code 에이전트

> 영어 원본: [claude-agents.md](claude-agents.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

[독립 모델 검증](independent-model-validation.ko.md)이 정한 검토자 호출은 아래 시점, 에이전트 선택, worker 규칙의 예외다.

에이전트나 모델 runner를 호출하기 전에 [공유 모델 라우팅](model-routing.ko.md)을 읽으며
[작업 효율](work-efficiency.ko.md)의 지침 재사용 규칙을 따른다. 메인 모델·프로필 변경이나 세션 재개 후에는
호출 전에 해당 계약의 실제 설정 검사를 적용한다.

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
실행하지 않는다. `--model <id>`는 `reviewer`에만, `--add-dir <dir>`은 `worker`에만 붙인다.

| 종료 코드 | 처리 |
|---|---|
| 0 | 결과 파일을 받아들인다. |
| 2 | 호출을 고쳐 다시 실행한다. |
| 3 또는 4 | 결과 파일을 읽지 않고 아래 대체 경로를 쓴다. |

| 역할 | 종료 코드 3 또는 4일 때 대체 경로 |
|---|---|
| `scout` | `hei5enbug-agent-setup:scout` |
| `researcher` | 공개 검색·가져오기 도구를 사용할 수 있을 때만 `hei5enbug-agent-setup:researcher` |
| 스킬 검토 역할의 `reviewer` | `hei5enbug-agent-setup:reviewer` |
| 독립 검증의 `reviewer` | 없음. 독립 검증을 수행하지 못했다고 보고한다. |
| `worker` | 부분 diff를 살펴본 뒤 `hei5enbug-agent-setup:worker` |

대체 경로도 쓸 수 없으면 메인 대화에서 계속한다.

## 조사

- 세션의 위임 규칙이 선택한 범위가 한정된 조사는 계획 중이든 실행 중이든 `scout` 역할로 실행한다. 각 scout에 질문 하나와
  좁은 검색 범위 하나를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 대화에서 확인한다.
- 범위가 한정된 공개 조사는 웹 검색 도구만 쓰고 셸 네트워크는 쓰지 않는 `researcher` 역할로 실행한다. 조건을
  충족하지 못하면 메인 대화에서 계속한다.

## 스킬 작업자

- 스킬이 맡긴 검토 역할(검토 페르소나, grader, comparator, analyzer)은 읽기 전용 판단 작업이다. 세션 줄 "Review model"의
  모델을 `--model`로 지정해 `reviewer` 역할을 실행한다.
- 독립 검증은 사용자가 독립 모델 검증에 따라 승인한 뒤, 그 파일이 고른 검토자를 `--model`로 지정해 `reviewer` 역할로
  실행한다. Claude가 작성한 결과라면 "Review model" 줄의 모델이다.
- 로컬 근거 조사 티켓은 `scout` 역할, 공개 자료 조사는 `researcher` 역할에 맡긴다. 검토 역할에는 `scout`를 사용하지
  않는다. 비공개·인증 원격 접근과 모든 수정은 메인 대화에서 처리한다.
- Skill Builder의 시험 실행과 기타 비검토 참여자에는 평가 어댑터에서 호스트의 상위 모델을 사용한다. 시험 출력을
  쓰는 작업자는 서브에이전트 대신 스킬이 지정한 모델과 사고 강도로 별도 `claude -p` 프로세스를 실행한다.

## 구현

구현은 [구현 실행 규칙](implementation-execution.ko.md)에 따라 조정한다. 이 섹션은 Claude Code worker 연동만 덧붙인다.

- 위임한 구현은 세션 줄 "Implementation worker route"에 지정된 경로를 따른다. 기본은 Codex worker(아래 "Codex worker" 참조),
  `haiku`일 때는 Haiku worker인 `hei5enbug-agent-setup:worker`, `sonnet`일 때는
  `hei5enbug-agent-setup:sonnet-worker`를 쓴다. 사용자가 한 경로를 요청하면 그 요청에만 적용한다. UI 코드,
  시각 디자인, 다이어그램 작업은 여전히 `hei5enbug-agent-setup:designer`가 맡는다. 그 밖의 에이전트는 쓰지 않는다.
- 호출 단위 모델은 정의보다 우선하므로 플러그인 에이전트를 호출하거나 재개할 때 넘기지 않는다. 정의에는 공유 모델
  라우팅이 정리한 모델과 사고 강도가 고정되어 있다.
- 아래 항목은 플러그인 에이전트가 실행될 때마다 적용한다. 실행기의 대체 경로, Haiku·Sonnet worker, designer가 해당한다.
- 세션 컨텍스트에 `hei5enbug-agent-setup mod: role pinning active`가 있으면 플러그인 Mod가 요청마다 각 역할의
  모델과 사고 강도를 고정하고, 다른 모델로 응답한 서브에이전트의 도구 호출을 막는다. 세션당 한 번만 환경 변수와 모든
  설정 파일에서 강제 모델과 사고 강도 한도(`CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  `CLAUDE_CODE_EFFORT_LEVEL` 같은 사고 강도 재정의, `maxEffortLevel`이나 조직 한도 같은 사고 강도 상한)만 확인한다.
  강제 모델이나 고정 사고 강도보다 낮은 상한이 있으면 플러그인 에이전트 위임을 멈춘다. 그렇지 않으면 할당을 바로
  보낸다. Mod의 고정과 차단이 수락 근거이므로 위임마다 설정이나 서브에이전트 기록을 읽지 않는다.
- 그 줄이 없으면 시작 결과에 모델이 나오지 않는다. 실행에서 처음 호출하기 전에 위의 비밀이 아닌 입력과 에이전트 정의,
  대체나 폴백 경고만 살펴보고, 구현 실행 규칙의 준비 확인 경로를 따른다. Claude Code는 세션 도중에 설정을 다시 읽을
  수 있으므로 구현 작업을 담은 후속 메시지를 보낼 때마다 다시 확인한다.
- `/tasks`나 서브에이전트 transcript 같은 호스트 기록은 호출한 정의의 고정 모델과 사고 강도를 기록할 때만
  인정한다. 제공자 내부의 추론 원격 측정은 필요하지 않다. 기록된 모델이 다르거나, 고정된 사고 강도보다 낮은 상한,
  모순된 재정의, 알 수 없는 실제 우선순위가 있으면 근거로 부족하다.
- 그 기록은 Claude 설정 디렉터리(`CLAUDE_CONFIG_DIR` 또는 `~/.claude`)의 `projects/<project>/` 아래 transcript에서
  읽는다. 세션 transcript의 시작 결과에 worker의 `agentId`와 `resolvedModel`이 있고,
  `<session-id>/subagents/agent-<agentId>.jsonl`의 각 assistant 항목에 `model`과 `effort`가 있다.
- 호스트 한도는 `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`다. 실행 중인 서브에이전트는 세지만 메인 세션은 세지 않는다.
  현재 값과 남은 자리를 기준으로 하고 이 값을 바꾸지 않는다.
- 플러그인 worker나 서브에이전트 기록이 없으면 해당 위임을 멈추고 세션의 대체 처리 규칙을 적용한다.
  사용자 설정은 바꾸지 않는다.

## Codex worker

- 일반 할당 항목을 담은 할당을 파일로 쓰고 `worker` 역할을 실행한다.
- 작업이 써야 하는 세션 폴더 밖 디렉터리에만 `--add-dir <dir>`을 붙인다. 플러그인 Mod는 그런 디렉터리마다 세션당
  한 번 묻는다.
