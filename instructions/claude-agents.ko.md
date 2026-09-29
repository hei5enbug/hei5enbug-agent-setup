# Claude Code 계획 및 에이전트

> 영어 원본: [claude-agents.md](claude-agents.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

[독립 모델 검증](independent-model-validation.ko.md)이 정한 검토자 호출은 아래 시점, 에이전트 선택, worker 규칙의 예외다.

## 조사

- 내장 `Explore`, `Plan` 서브에이전트와 포괄형 `general-purpose`, `claude` 서브에이전트를 사용하지 않는다.
- 계획하는 동안 조사에만, 그리고 세션 지침의 위임 기준을 충족할 때만 `hei5enbug-agent-setup:scout`를 사용한다.
- 각 `hei5enbug-agent-setup:scout`에 질문 하나와 좁은 검색 범위 하나를 지정한다.
- 결과에 파일 경로, 코드 심볼과 구체적인 근거를 요구한다.
- 결과를 단서로 취급한다. 계획하거나 결정하기 전에 핵심 주장을 메인 대화에서 확인한다.
- 플러그인이 `hei5enbug-agent-setup:scout`를 함께 설치한다. 사용할 수 없으면 메인 대화에서 조사한다.

## 구현

구현은 [구현 실행 규칙](implementation-execution.ko.md)에 따라 조정한다. 이 섹션은 Claude Code worker 연동만 덧붙인다.

- 구현에는 `hei5enbug-agent-setup:worker`만 사용한다. 호출하거나 재개할 때마다 `sonnet` 별칭을 호출 단위 모델로
  전달한다. 다른 에이전트로 바꾸지 않는다.
- 필수 계열은 가장 새로운 정식 Claude Sonnet이다. 공식 [모델 설정 문서](https://code.claude.com/docs/en/model-config)의
  Sonnet 매핑과 여기서 연결한 모델 정보로 전체 ID를 확정한다.
- 실행에서 처음 호출하기 전에 환경 변수와 모든 설정 파일에서 비밀이 아닌 다음 입력만 살펴본다. worker 정의,
  `CLAUDE_CODE_SUBAGENT_MODEL`과 `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
  `CLAUDE_CODE_EFFORT_LEVEL` 같은 사고 강도 재정의, `maxEffortLevel`이나 조직 한도 같은 사고 강도 상한, 대체나 폴백
  경고다. 사용자 설정은 바꾸지 않는다.
- Claude Code는 세션 도중에 설정을 다시 읽을 수 있고, 강제된 서브에이전트 모델은 호출 단위 모델보다 우선한다.
  구현 작업을 담은 후속 메시지를 보낼 때마다 이 입력을 다시 확인한다.
- `/tasks`나 서브에이전트 transcript 같은 호스트의 서브에이전트 기록이 확정한 전체 ID를 실제 모델로, `xhigh`를
  사고 강도로 기록하고 설정이 그 사고 강도를 낮출 수 없으면 근거로 인정한다. 제공자 내부의 추론 원격 측정은
  필요하지 않다. 기록된 모델이 다르거나, `xhigh`보다 낮은 상한, 모순된 재정의, 알 수 없는 실제 우선순위가 있으면
  근거로 부족하다.
- 시작 결과에는 모델이 나오지 않으므로 각 worker는 준비 확인 전용 할당으로 시작한다. 기록 확인을 통과하면 같은
  worker에게 구현 할당을 보낸다. 이 경로는 그 후속 메시지가 호출 단위 모델을 유지할 때만 사용한다. 이런 이어
  보내기를 쓸 수 없으면 두 단계 경로를 건너뛰고 아무것도 수정하지 않는다. 재개한 뒤에는 설정을 다시 확인한다.
- 호스트 한도는 `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`다. 실행 중인 서브에이전트는 세지만 메인 세션은 세지 않는다.
  현재 값과 남은 자리를 기준으로 하고 이 값을 바꾸지 않는다.
- 플러그인 worker나 서브에이전트 기록이 없으면 영향을 받는 구현을 막는다. 막힌 기능을 정확히 보고하고 아무것도
  수정하지 않는다.
