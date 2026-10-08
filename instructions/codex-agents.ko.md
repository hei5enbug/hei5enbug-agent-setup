# Codex 계획 및 에이전트

> 영어 원본: [codex-agents.md](codex-agents.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

메인 세션의 계획 모드에서 계획한다.

[독립 모델 검증](independent-model-validation.ko.md)이 정한 검토자 호출은 아래 시점 규칙과 worker 규칙의 예외다.

에이전트나 모델 runner를 호출하기 전에 [공유 모델 라우팅](model-routing.ko.md)을 읽으며
[작업 효율](work-efficiency.ko.md)의 지침 재사용 규칙을 따른다. 메인 모델·프로필 변경이나 세션 재개 후에는
호출 전에 해당 계약의 실제 설정 검사를 적용한다.

## 내장 에이전트

- 내장 `default`, `explorer` 에이전트는 사용하지 않는다. `agent_type`을 비우면 `default`가 실행되므로 항상 지정한다.
- 세션 훅은 플러그인의 `scout`, `worker`, `researcher`, `designer`, `reviewer` 역할이 `~/.codex/agents/`에 없을 때 설치하고,
  이전 버전의 수정하지 않은 복사본만 바꾸며, 사용자가 고친 파일은 덮어쓰지 않는다. 설치한 역할은 다음 Codex
  세션부터 쓸 수 있다.
- 플러그인의 에이전트 차단 훅은 종류를 비운 호출, `default`, `explorer`, Codex 에이전트 디렉터리에 역할 파일이 없는
  모든 종류를 거부한다. 그래서 플러그인 역할이 생기기 전까지는 내장 `worker`도 거부한다.

## 조사

- 세션의 위임 규칙이 선택한 범위가 한정된 읽기 전용 조사에는 계획 중이든 실행 중이든 `scout` 에이전트를 사용한다.
- 생성할 때마다 `gpt-6-luna`와 `xhigh`를 명시적으로 전달한다. 함께 배포하는 역할 파일은 모델을 지정하지 않으므로
  생성할 때 넘긴 값이 적용된다.
- 구체적인 질문 하나와 좁은 검색 범위를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 세션에서 확인한다.
- `scout`를 사용할 수 없거나 Codex 에이전트 디렉터리의 역할 파일이 다른 모델이나 사고 강도를 지정하면 메인
  세션에서 조사한다.
- 범위가 한정된 공개 조사에는 공개 검색·가져오기 도구가 노출될 때만 `researcher`를 사용한다. researcher를 생성할
  때마다 `gpt-6-luna`와 `xhigh`를 명시적으로 전달한다. 역할 파일은 모델을 지정하지 않는다. 결과를 신뢰하기 전에
  비밀이 아닌 researcher 역할·설정 값을 점검하고 호스트 rollout 기록이 `gpt-6-luna`와 `xhigh`를 보고하는지
  확인한다. 조건을 충족하지 못하면 메인 세션에서 계속한다.

## 스킬 작업자

- 스킬이 맡긴 검토 역할 하나(검토 페르소나, grader, comparator, analyzer)는 읽기 전용 판단 작업이다. 저장소
  루트에서 할당을 표준 입력으로 전달해 다른 모델 계열 검토자를 실행한다.

  ```text
  claude -p --model claude-opus-5-5 --effort high --output-format json --tools Read Grep Glob --strict-mcp-config --permission-mode dontAsk --allowedTools Read Grep Glob
  ```

  결과는 JSON의 `modelUsage`에 `claude-opus-5-5`가 있을 때만 인정한다. `claude`가 없거나 로그인되지 않았거나,
  인증·사용량 한도·모델·시간 초과 오류로 끝나거나 근거가 없으면 플러그인 `reviewer` 역할을 `gpt-6.1-sol`과
  `xhigh`를 명시해 시작한다. rollout 기록에 해당 설정이 있는지 확인하고 대체 사실을 한 번 보고한다. reviewer는
  지적 결과만 반환한다. 메인 세션은 같은 자료를 한 번 직접 검토한 뒤 최종 판단한다. 추가 검토는 하지 않는다.
- 로컬 근거 조사 티켓은 `scout`, 공개 자료 조사는 공개 도구와 설정을 확인한 뒤 `researcher`에 맡긴다. 비공개 자료나
  인증이 필요한 원격 접근은 메인 세션에서 처리한다.
- Skill Builder의 시험 실행과 기타 비검토 참여자에는 평가 어댑터에서 호스트의 상위 모델을 사용한다. 검토 역할을
  `scout`이나 시험 출력 작성자에게 맡기지 않는다.
- 시험 출력을 쓰는 작업자는 스킬이 지정한 모델과 사고 강도로 별도의 `codex exec` 프로세스를 실행한다.

## 구현

구현은 [구현 실행 규칙](implementation-execution.ko.md)에 따라 조정한다. 이 섹션은 Codex worker 연동만 덧붙인다.

- 구현을 위임할 때는 플러그인 `worker` 역할만 사용한다. 역할 파일은 모델을 지정하지 않으므로 생성할 때마다 고정된
  `gpt-6-luna`와 `xhigh`를 명시적으로 전달한다.
- 전체 기록 fork는 부모의 모델과 사고 강도를 물려받고 재정의를 거부한다. worker를 이 방식으로 생성하지 않는다.
  `fork_turns`를 `"none"`이나 양의 정수로 두거나 `fork_context`를 끄고, 범위를 한정한 작업 맥락은 할당에 담는다.
- 실행에서 처음 생성하기 전에 설정 계층의 `model`, `model_reasoning_effort`, 관련 `[agents]` 기본값 항목만 살펴본다.
  개인 또는 프로젝트 Codex 에이전트 디렉터리의 `worker` 역할 파일도 포함한다. 이 파일은 생성 값을 재정의할 수
  있으므로, 그래도 `gpt-6-luna`와 `xhigh`로 확정되어야 한다.
- 이미 있는 `~/.codex/agents/worker.toml`이나 `.codex/agents/worker.toml`은 덮어쓰지 않고, 전역 모델 기본값도
  바꾸지 않는다.
- 명시적인 생성 인수와 worker의 rollout 기록을 근거로 인정한다. 이 기록은 `CODEX_HOME`(기본값 `~/.codex`) 아래
  sessions 디렉터리에서 찾는다. 기록의 `session_meta`에는 조정자의 `CODEX_THREAD_ID`인 부모 스레드와 worker의
  에이전트 경로가, `turn_context`에는 실제 `model`과 `effort`가 있다. worker가 스스로 보고한 내용은 이 기록이 아니다.
- 생성 결과에는 모델이 나오지 않으므로 각 worker는 준비 확인 전용 할당으로 시작한다. 기록 확인을 통과하면 같은
  worker 스레드에 후속 메시지로 구현 할당을 보낸다. 이 경로는 그 후속 메시지가 설정을 유지할 때만 사용한다. 이런
  이어 보내기를 쓸 수 없으면 두 단계 경로 대신 세션의 대체 처리 규칙을 적용한다. 재개한 뒤에는 설정을 다시 확인한다.
- 호스트 한도는 `agents.max_concurrent_threads_per_session`이다. 생성한 스레드는 세지만 메인 스레드는 세지 않는다.
  현재 값과 남은 자리를 기준으로 하고 이 값을 바꾸지 않는다.
- worker 도구가 없거나, `worker` 역할 파일이 없거나, 모델이나 `xhigh`를 쓸 수 없거나, 사용자 설정이 맞지 않거나,
  실제 설정을 확인하지 못하면 해당 위임을 멈추고 세션의 대체 처리 규칙을 적용한다.
- Codex는 사용자, `AGENTS.md` 또는 스킬 지침이 요청할 때만 서브에이전트를 생성한다. 플러그인의 세션 훅이
  `~/.codex/AGENTS.md`에 표시된 블록을 유지하며 그 블록이 이 권한을 부여한다. `HEI5ENBUG_SUBAGENT_POLICY=off`이면
  블록을 제거하고, 변경은 다음 세션부터 적용된다. 승인이 없으면 세션의 대체 처리 규칙에 따라 메인 세션에서
  계속한다.
- 훅은 `default_mode_request_user_input`도 켜므로 `request_user_input`을 다음 세션부터 Default 모드에서 쓸 수 있다.

## 디자인 작업

UI 코드, 시각 디자인, 다이어그램 작업은 저장소 루트에서 별도 프로세스를 실행하고 할당을 stdin으로 전달한다.

```text
claude -p --model claude-opus-5-5 --effort xhigh --output-format json --permission-mode dontAsk --allowedTools Read Grep Glob "Edit(<allowed path>/**)" "Write(<allowed path>/**)"
```

- 샌드박스가 네트워크를 막으면 일반 Codex 승인 흐름으로 네트워크 접근을 요청한다.
- JSON `modelUsage`에 `claude-opus-5-5`가 있을 때만 결과를 받아들인다.
- `claude`가 없거나, 프로세스가 인증·사용량 한도·모델 오류로 끝나거나, 그 근거가 없으면 대신 플러그인 `designer`
  역할을 `gpt-6-astra`와 `xhigh`로 생성한다. `worker`와 같은 방식으로 rollout 기록을 확인하고 대체 사실을
  보고한다.
