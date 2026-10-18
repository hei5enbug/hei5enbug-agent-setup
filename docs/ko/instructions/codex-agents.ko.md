# Codex 에이전트

> 영어 원본: [codex-agents.md](../../../instructions/codex-agents.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

[독립 모델 검증](independent-model-validation.ko.md)이 정한 검토자 호출은 아래 시점 규칙과 worker 규칙의 예외다.

[공유 모델 라우팅](model-routing.ko.md)은 스킬 검토 역할이나 Skill Builder 참여자를 호출하거나, 독립 검토자를
선정하거나, 메인 모델·프로필 변경이나 세션 재개 후 처음 호출할 때 읽는다. 마지막 경우에는 먼저 실제 설정 검사를
적용한다. 그 밖의 호출에는 이 파일만 필요하다.

## 내장 에이전트

- 내장 `default`, `explorer` 에이전트는 사용하지 않는다. `agent_type`을 비우면 `default`가 실행되므로 항상 지정한다.
- 세션 훅은 플러그인의 `scout`, `worker`, `designer`, `reviewer` 역할이 `~/.codex/agents/`에 없을 때 설치하고,
  이전 버전의 수정하지 않은 복사본만 바꾸며, 사용자가 고친 파일은 덮어쓰지 않는다. 설치한 역할은 다음 Codex
  세션부터 쓸 수 있다.
- 플러그인의 에이전트 차단 훅은 종류를 비운 호출, `default`, `explorer`, Codex 에이전트 디렉터리에 역할 파일이 없는
  모든 종류를 거부한다. 그래서 플러그인 역할이 생기기 전까지는 내장 `worker`도 거부한다.

## 조사

- 세션의 위임 규칙이 선택한 범위가 한정된 읽기 전용 조사에는 계획 중이든 실행 중이든 `scout` 에이전트를 사용한다.
- 생성할 때마다 `gpt-5.6-luna`와 `xhigh`를 명시적으로 전달한다. 함께 배포하는 역할 파일은 모델을 지정하지 않으므로
  생성할 때 넘긴 값이 적용된다.
- 결과를 신뢰하기 전에 아래 '생성된 역할 검증' 절을 거친다.
- 구체적인 질문 하나와 좁은 검색 범위를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 세션에서 확인한다.
- `scout`를 사용할 수 없거나 Codex 에이전트 디렉터리의 역할 파일이 다른 모델이나 사고 강도를 지정하면 메인
  세션에서 조사한다.
- 범위가 한정된 공개 조사는 웹 검색을 쓸 수 있을 때만 역할 실행기의 `researcher` 역할을 실행한다:
  `python3 <Source directory>/scripts/role_runner.py researcher --assignment <file> --result <file>`. 이 역할은
  웹 검색으로 `gpt-5.6-luna`와 `xhigh`를 쓰며 세션 기록으로 두 값을 검증한다. 조건을 충족하지 못하면 메인 세션에서 계속한다.

## 스킬 작업자

- 스킬이 맡긴 검토 역할 하나(검토 페르소나, grader, comparator, analyzer)는 읽기 전용 판단 작업이다. 저장소
  루트에서 역할 파일과 할당 파일을 넘겨 기능 실행기를 실행한다.

  ```text
  python3 <Source directory>/scripts/role_runner.py review --host codex --instructions <role file> --assignment <file> --result <file>
  ```

  결과 파일은 종료 코드 0일 때만 인정하며, 실행기가 호스트 기록으로 모델을 검증한다. 종료 코드 3 또는 4이면 플러그인
  `reviewer` 역할을 `gpt-6.1-sol`과 `xhigh`를 명시해 시작한다. 아래 '생성된 역할 검증' 절을 거친다.
- 로컬 근거 조사 티켓은 `scout`, 공개 자료 조사는 웹 검색을 쓸 수 있고 설정을 확인한 뒤 `researcher` 실행기 역할에
  맡긴다. 비공개 자료나 인증이 필요한 원격 접근, 이슈 트래커와 풀 리퀘스트 서비스 같은 외부 도구 작업은
  `implementation` 기능으로, 수정은 스킬이 지정한 기능 작업자로 보낸다. 그 밖에는 메인 세션에서 처리한다.
- Skill Builder의 시험 실행과 기타 비검토 참여자에는 평가 어댑터에서 호스트의 상위 모델을 사용한다. 검토 역할을
  `scout`이나 시험 출력 작성자에게 맡기지 않는다.
- 시험 출력을 쓰는 작업자는 스킬이 지정한 모델과 사고 강도로 별도의 `codex exec` 프로세스를 실행한다.

## 구현

위임한 구현은 [구현 위임 규칙](implementation-delegation.ko.md)에 따라 조정한다. 이 섹션은 Codex worker 연동만 덧붙인다.

- 구현을 위임할 때는 플러그인 `worker` 역할만 사용한다. 역할 파일은 모델을 지정하지 않으므로 생성할 때마다 고정된
  `gpt-5.6-luna`와 `xhigh`를 명시적으로 전달한다.
- 전체 기록 fork는 부모의 모델과 사고 강도를 물려받고 재정의를 거부한다. worker를 이 방식으로 생성하지 않는다.
  `fork_turns`를 `"none"`이나 양의 정수로 두거나 `fork_context`를 끄고, 범위를 한정한 작업 맥락은 할당에 담는다.
- 실행에서 처음 생성하기 전에 설정 계층의 `model`, `model_reasoning_effort`, 관련 `[agents]` 기본값 항목만 살펴본다.
  개인 또는 프로젝트 Codex 에이전트 디렉터리의 `worker` 역할 파일도 포함한다. 이 파일은 생성 값을 재정의할 수
  있으므로, 그래도 `gpt-5.6-luna`와 `xhigh`로 확정되어야 한다.
- 이미 있는 `~/.codex/agents/worker.toml`이나 `.codex/agents/worker.toml`은 덮어쓰지 않고, 전역 모델 기본값도
  바꾸지 않는다.
- worker의 결과는 아래 '생성된 역할 검증' 절을 통과한 뒤에만 인정한다.
- 생성 결과에는 모델이 나오지 않으므로 구현 위임 규칙의 준비 확인 경로를 따라 같은 worker 스레드에 후속 메시지로
  구현 할당을 보낸다.
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

`design` 기능(UI 코드, 시각 디자인, 다이어그램이나 이미지, 기술 설계 문서 초안 작성)은 capability 표의 `codex` 항목을
따른다. 기본 경로는 플러그인 `designer` 역할을 `gpt-6-astra`와 `xhigh`를 명시해 생성하는 것이다. 아래 '생성된 역할
검증' 절을 거친다. 그 경로가 실패하면 대체 항목을 한 번 쓴다. 저장소 루트에서 역할 실행기로 실행한다.

```text
python3 <Source directory>/scripts/role_runner.py agent --name designer --fallback --host codex --add-dir <allowed path> --assignment <file> --result <file>
```

- 샌드박스가 네트워크를 막으면 일반 Codex 승인 흐름으로 네트워크 접근을 요청한다.
- 실행기가 종료 코드 3 또는 4로 끝나면 메인 세션에서 계속한다.

## 생성된 역할 검증

생성된 역할의 결과는 rollout이 검증된 뒤에만 인정한다. 역할이 끝나면 세션 폴더에서 다음을 실행한다. `<Source directory>`는
세션 컨텍스트의 그 줄이고, `<task_name>`, 모델, 사고 강도는 `spawn_agent`에 넘긴 값이며, `<sandbox_mode>`는 역할 TOML의 `sandbox_mode` 값이다.

```text
python3 <Source directory>/scripts/verify_spawn.py --parent "$CODEX_THREAD_ID" --agent-path /root/<task_name> --model <model> --effort <effort> --sandbox <sandbox_mode>
```

- 종료 코드 0은 rollout이 검증되었다는 뜻이다. 결과를 쓴다.
- 종료 코드 2는 호출이 잘못되었다는 뜻이다. 고쳐서 다시 실행한다.
- 종료 코드 4는 rollout이 없거나 다른 모델, 사고 강도, 샌드박스를 가리킨다는 뜻이다. 같은 역할을 다른 쌍으로 다시 생성하지
  않는다. 에이전트 가드가 Codex에서 대체 쌍을 거부하기 때문이다. 아래 '대체' 절에 따라 역할의 대체를 역할 실행기로 실행하거나
  메인 세션에서 계속한다.

## 기능 실행

기능 항목은 [capability 표](model-routing.ko.md#기능별-고정값)에서 `codex` 항목을 찾는다. 기능은 `investigation`,
`implementation`, `design`, `language`, `review` 다섯 개다. 아래 '대체' 절의 대체 규칙을 적용한다.

[기능별 고정값 표](model-routing.ko.md#기능별-고정값)에서 Codex 쪽 해당 기능 항목을 찾는다.

- `via: runner`: 아래 기능 실행기를 실행한다.
- `via: agent`: 항목의 `agent` 필드에 적힌 에이전트를 항목의 `model`과 `effort`를 명시해 띄운다. 그다음
  위의 생성된 역할 검증 절에 따라 검증한다.
- 그 경로가 실패하면 기능의 대체 항목을 한 번 쓰고, 그래도 안 되면 메인 세션에서 계속한다.

## 기능 실행기

Codex는 `via: runner` 항목을 가진 기능, 예를 들어 Claude 모델 기능에 역할 실행기를 호출한다.

```text
python3 <Source directory>/scripts/role_runner.py <capability> --host codex --instructions <file> --assignment <file> --result <file>
```

실행기는 `--host codex`에 대해 [기능별 고정값 표](model-routing.ko.md)가 고르는 항목을 실행하고, `--fallback`은
대체 항목을 고른다. 고른 항목이 `via: runner`가 아니면 실행기는 종료 코드 2를 반환하므로 에이전트 경로나 메인 세션에서
계속한다. `--resume <session_id>`는 상태 줄의 `evidence.session`으로 Codex 또는 Claude 실행을 이어 간다. 상태 줄과
종료 코드는 [Claude Code 에이전트](claude-agents.ko.md#역할-실행기)와 같다.

## 대체

모든 대체 항목은 다른 모델 계열이다. 다른 호스트의 모델이 필요한 대체 항목은 역할 실행기를 거치고, 현재 호스트에서 바로 실행할
수 있는 대체 항목은 이름이 붙은 에이전트를 쓴다. 플러그인 에이전트의 다른 계열 대체는
`python3 <Source directory>/scripts/role_runner.py agent --name <name> --fallback`으로, 기능의 `via: runner` 대체는
`python3 <Source directory>/scripts/role_runner.py <capability> --host codex --fallback`으로 실행한다. `--mcp`는 할당이 MCP 도구나
네트워크를 쓸 때만 붙인다. 실행기가 종료 코드 3 또는 4로 끝나면 메인 세션에서 계속한다.
