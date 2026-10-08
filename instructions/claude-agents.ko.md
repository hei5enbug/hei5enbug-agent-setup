# Claude Code 계획 및 에이전트

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

## 조사

- 세션의 위임 규칙이 선택한 범위가 한정된 조사는 계획 중이든 실행 중이든 Luna scout로 실행한다. 세션 폴더에서
  할당을 stdin으로 넘긴다.

  ```text
  codex exec -m gpt-6-luna -c model_reasoning_effort="xhigh" -s read-only -C <session folder> --json -o <result file> - < <assignment file>
  ```

  할당은 Codex가 이 세션의 읽기 전용 scout라고 알리며 시작한다. 에이전트, 커밋, 푸시, 네트워크, 파일 수정은
  금지하고 할당이 정한 결과를 반환하게 한다. 이어서 플러그인 `agents/scout.md` 본문을 역할 지침으로 넣는다.
  `--add-dir`를 붙이거나, 명령 앞에 `cd`를 실행하거나, `--ephemeral`을 전달하지 않는다. rollout의 `turn_context`에
  `gpt-6-luna`와 `xhigh`가 있을 때만 결과를 인정한다.
- 각 scout에 질문 하나와 좁은 검색 범위 하나를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 대화에서 확인한다.
- `codex`가 없거나, 로그인되어 있지 않거나, 인증·사용량 한도·모델·시간 초과 오류로 끝나거나, 근거가 없으면
  `hei5enbug-agent-setup:scout`를 사용하고 대체 사실을 한 번 보고한다. 정의에 `claude-sonnet-5-5`와 `medium`이
  고정되어 있다. 호출 단위 모델은 정의보다 우선하므로 넘기지 않는다. 둘 다 사용할 수 없으면 메인 대화에서
  조사한다.
- 범위가 한정된 공개 조사에는 공개 검색·가져오기 도구를 사용할 수 있을 때만 `hei5enbug-agent-setup:researcher`를
  사용한다. 호출 단위 모델은 전달하지 않는다. 정의에 `claude-haiku-5-5`와 `medium`이 고정되어 있다. 결과를
  신뢰하기 전에 그 정의, 비밀이 아닌 실제 설정, 호스트의 서브에이전트 기록을 확인한다. 조건을 충족하지 못하면
  메인 대화에서 계속한다.

## 스킬 작업자

- 스킬이 맡긴 검토 역할(검토 페르소나, grader, comparator, analyzer)은 읽기 전용 판단 작업이다. 세션 폴더에서
  할당을 표준 입력으로 전달해 다른 모델 계열 검토자를 실행한다.

  ```text
  codex exec -m gpt-6.1-sol -c model_reasoning_effort="xhigh" -s read-only -C <session folder> --json -o <result file> - < <assignment file>
  ```

  할당은 Codex가 "Assigned workers" 규칙의 작업자라고 알리며 시작한다. 에이전트, 커밋, 푸시, 네트워크, 파일 수정은
  금지하고 역할의 출력 계약에 따라 지적 결과만 반환하게 한다. `--add-dir`는 붙이지 않는다. 읽기
  전용 샌드박스는 세션 폴더 밖 파일도 이미 읽을 수 있다. 명령 앞에 `cd`를 실행하거나 `--ephemeral`을 전달하지 않는다. rollout의
  `turn_context`에 `gpt-6.1-sol`과 `xhigh`가 있을 때만 결과를 인정한다.
- `codex`가 없거나 로그인되지 않았거나 인증·사용량 한도·모델·시간 초과 오류로 끝나거나 근거가 없으면
  `hei5enbug-agent-setup:reviewer`를 사용한다. 정의에 `claude-opus-5-5`와 `high`가 고정되어 있다. 서브에이전트
  기록을 확인하고 대체 사실을 한 번 보고한다. reviewer는 지적 결과만 반환한다. 메인 세션은 같은 자료를 한 번
  직접 검토한 뒤 최종 판단한다. 추가 검토는 하지 않는다.
- 로컬 근거 조사 티켓은 "조사"의 scout 경로, 공개 자료 조사는 공개 도구와 실제 설정을 확인한 뒤 `researcher`에 맡긴다.
  검토 역할에는 `scout`를 사용하지 않는다. 비공개·인증 원격 접근과 모든 수정은 메인 대화에서 처리한다.
- Skill Builder의 시험 실행과 기타 비검토 참여자에는 평가 어댑터에서 호스트의 상위 모델을 사용한다. 시험 출력을
  쓰는 작업자는 서브에이전트 대신 스킬이 지정한 모델과 사고 강도로 별도 `claude -p` 프로세스를 실행한다.

## 구현

구현은 [구현 실행 규칙](implementation-execution.ko.md)에 따라 조정한다. 이 섹션은 Claude Code worker 연동만 덧붙인다.

- 위임한 구현은 세션 줄 "Implementation worker route"에 지정된 경로를 따른다. 기본은 Codex worker(아래 "Codex worker" 참조),
  `haiku`일 때는 Haiku worker인 `hei5enbug-agent-setup:worker`, `sonnet`일 때는
  `hei5enbug-agent-setup:sonnet-worker`를 쓴다. 사용자가 한 경로를 요청하면 그 요청에만 적용한다. UI 코드,
  시각 디자인, 다이어그램 작업은 여전히 `hei5enbug-agent-setup:designer`가 맡는다. `worker` 정의에는
  `claude-haiku-5-5`와 `high`, `sonnet-worker`에는 `claude-sonnet-5-5`와 `high`, `designer`에는
  `claude-opus-5-5`와 `xhigh`가 고정되어 있다. 호출 단위 모델은 정의보다 우선하므로 호출이나 재개할 때 넘기지
  않는다. 그 밖의 에이전트는 쓰지 않는다.
- 아래 항목은 플러그인 에이전트가 실행될 때 적용한다. Codex 대체로 실행하는 Haiku worker,
  Sonnet worker, designer가 해당한다.
- 실행에서 처음 호출하기 전에 환경 변수와 모든 설정 파일에서 비밀이 아닌 다음 입력만 살펴본다. worker 정의,
  `CLAUDE_CODE_SUBAGENT_MODEL`과 `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`,
  `CLAUDE_CODE_EFFORT_LEVEL` 같은 사고 강도 재정의, `maxEffortLevel`이나 조직 한도 같은 사고 강도 상한, 대체나 폴백
  경고다. 사용자 설정은 바꾸지 않는다.
- Claude Code는 세션 도중에 설정을 다시 읽을 수 있고, 강제된 서브에이전트 모델은 정의보다 우선한다.
  구현 작업을 담은 후속 메시지를 보낼 때마다 이 입력을 다시 확인한다.
- Claude Code의 메인 모델을 GPT로 바꿔도 이 호스트, 도구, 권한, 에이전트 정의, 실행 규칙은 바뀌지 않는다.
  각 worker 정의의 고정 모델과 사고 강도를 유지한다.
- `/tasks`나 서브에이전트 transcript 같은 호스트 기록은 호출한 정의의 고정 모델과 `high` 사고 강도를
  기록할 때만 인정한다. `worker`는 `claude-haiku-5-5`, `sonnet-worker`는 `claude-sonnet-5-5`다.
  `designer`의 근거는 `claude-opus-5-5`와 `xhigh`다. 제공자 내부의 추론 원격 측정은 필요하지 않다. 기록된
  모델이 다르거나, 고정된 사고 강도보다 낮은 상한, 모순된 재정의, 알 수 없는 실제 우선순위가 있으면 근거로
  부족하다.
- 그 기록은 Claude 설정 디렉터리(`CLAUDE_CONFIG_DIR` 또는 `~/.claude`)의 `projects/<project>/` 아래 transcript에서
  읽는다. 세션 transcript의 시작 결과에 worker의 `agentId`와 `resolvedModel`이 있고,
  `<session-id>/subagents/agent-<agentId>.jsonl`의 각 assistant 항목에 `model`과 `effort`가 있다.
- 세션 컨텍스트에 `hei5enbug-agent-setup mod: role pinning active`가 있으면 플러그인 Mod가 요청마다 각 역할의
  모델과 사고 강도를 고정하고, 다른 모델로 응답한 서브에이전트의 도구 호출을 막는다. 준비 확인 전용 호출 없이
  할당을 바로 보낸다.
- 그 줄이 없으면 시작 결과에는 모델이 나오지 않으므로 각 worker는 준비 확인 전용 할당으로 시작한다. 기록 확인을
  통과하면 같은 worker에게 구현 할당을 보낸다. 이 경로는 그 후속 메시지가 고정 모델을 유지할 때만 사용한다.
  이런 이어 보내기를 쓸 수 없으면 두 단계 경로 대신 세션의 대체 처리 규칙을 적용한다. 재개한 뒤에는 설정을 다시
  확인한다.
- 두 경우 모두 첫 호출 전의 설정 점검을 유지하고, 위임한 작업을 받아들이기 전에 서브에이전트 기록을 읽어 실제
  모델과 사고 강도를 확인한다.
- 호스트 한도는 `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`다. 실행 중인 서브에이전트는 세지만 메인 세션은 세지 않는다.
  현재 값과 남은 자리를 기준으로 하고 이 값을 바꾸지 않는다.
- 플러그인 worker나 서브에이전트 기록이 없으면 해당 위임을 멈추고 세션의 대체 처리 규칙을 적용한다.

## Codex worker

- 할당을 파일로 쓴 뒤, 세션 폴더에서 그 파일을 표준 입력으로 넘겨 Codex를 백그라운드로 실행한다.
  `codex exec -m gpt-6-luna -c model_reasoning_effort="xhigh" -s workspace-write -C <session folder> --json -o <result file> - < <assignment file>`.
  앞에 `cd`를 붙이거나 `--ephemeral`을 쓰지 않는다.
- 작업이 써야 하는 세션 폴더 밖 디렉터리에만 `--add-dir <dir>`을 붙인다. 플러그인 Mod는 그런 디렉터리마다 세션당
  한 번 묻는다. `danger-full-access`, `--dangerously-bypass-approvals-and-sandbox`, 샌드박스나 네트워크 설정을 바꾸는
  `-c` 재정의는 넘기지 않는다.
- 할당은 Codex가 "Assigned workers" 규칙의 할당받은 worker라고 알리며 시작한다. 에이전트를 시작하지 않고, 커밋이나
  푸시를 하지 않고, 네트워크를 쓰지 않고, 허용된 경로만 수정하며, 변경한 경로·검사 결과·막힌 점으로 끝낸다. 할당에는
  일반 할당 항목을 모두 담는다.
- 근거: `thread.started` JSON 이벤트에서 `thread_id`를 가져온다. `CODEX_HOME`(기본 `~/.codex`)의 `sessions/` 아래에서 이름에 그
  ID가 들어 있는 rollout 파일의 `turn_context` 항목이 `gpt-6-luna`와 `xhigh`를 명시해야 한다. 그 밖의 것은 인정하지
  않는다.
- 대체: `codex`가 없거나 로그인되어 있지 않을 때, 실행이 인증·사용량 한도·모델·시간 초과 오류로 끝날 때, 근거가 없을
  때는 부분 diff를 살펴본 뒤 작업을 Haiku worker인 `hei5enbug-agent-setup:worker`에게 넘기고 대체 사실을 한 번 보고한다.
