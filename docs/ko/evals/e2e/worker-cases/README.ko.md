# worker 모델 사례

> 영어 원본: [README.md](../../../../../evals/e2e/worker-cases/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

어려운 작업에서 코딩 에이전트 모델을 비교하는 가상 픽스처 과제 열 개, `T68`부터 `T77`까지다.
[이슈 87](https://github.com/hei5enbug/hei5enbug-agent-setup/issues/87)의 사례로, `claude-sonnet-5-5`와
`claude-opus-5-5`를 `high`에서 사례마다 한 번씩 실행한다. 이후 코딩 에이전트 모델을 비교할 때마다 이 사례를 다시
쓴다. 과제 구성은 [골든 작업](../README.ko.md#골든-작업)과 같지만, `--tasks`로 이름을 주지 않으면 `run`이 이 사례를
고르지 않으므로 기본 캠페인은 달라지지 않는다.

## 사례

각 과제 파일에는 `"worker_case": true`와 다섯 기준 중에서 고른 `"worker_criteria"` 라벨이 있다. 다섯 기준은
`components`(여러 구성 요소), `public-contract`(공개 계약), `security`, `concurrency`, `hook-guard`(훅이나 가드 변경)다.
필수 숨은 검사 둘, 즉 `hidden-tests`와 `regressions`가 모두 통과하면 그 모델이 사례를 통과한 것이다. 픽스처와 값은
모두 가상이며, 사례는 이 저장소의 최근 30일 기록이 보여 주는 작업을 본떴고 다른 저장소는 쓰지 않았다.

| 과제 | 픽스처 | 기준 | 요청 | 본뜬 작업 |
|---|---|---|---|---|
| T68 | guard-kit | hook-guard, security | 링크 뒤의 실제 경로로 쓰기를 판정 | 설치된 플러그인 코드로 풀리는 쓰기를 거부하는 승인 가드 |
| T69 | guard-kit | hook-guard, public-contract | 훅이 제한 시간의 절반 안에 명확한 거부나 무응답으로 끝남 | 시간 안에 끝나고 훅 이름을 밝히며 거부하는 훅 |
| T70 | guard-kit | security | 나가는 범위의 모든 커밋을 검사 | 범위가 들여오는 모든 파일 버전을 보는 공개 경계 검사 |
| T71 | job-queue | concurrency | 긴 잠금은 보내는 동안만 잡고 상태는 짧은 잠금 아래에서 갱신 | 보내는 동안에만 세션 잠금을 잡는 새로고침 도우미 |
| T72 | job-queue | concurrency, public-contract | 작업마다 프로세스 사이에서 한 번만 가져가고 배치 가져오기를 추가 | 새로고침과 승인 코드의 공유 상태 잠금 |
| T73 | plugin-host | components, public-contract | 매니페스트, 컨텍스트, 경로 문구, 문서, 미러에 걸쳐 옵션 값을 추가 | 새 경로 값을 처음부터 끝까지 추가한 작업 |
| T74 | plugin-host | components | 조건부 규칙을 항목 한 줄 뒤로 옮기고 미러도 갱신 | 상시 로드 규칙에서 질문 방법 상세를 옮긴 작업 |
| T75 | plugin-host | public-contract | 도구의 `-h`, `--help`, 알 수 없는 옵션, 종료 코드 | `-h`를 경로로 읽지 않고 사용법을 출력하는 도구 |
| T76 | guard-kit | hook-guard, security | push 명령이 보내는 ref를 읽음 | push 검사에서 리다이렉션과 ref 없는 push를 읽는 작업 |
| T77 | job-queue | concurrency, hook-guard | 승인을 잃지 않는 저장소와 예외를 던지지 않는 훅 | 승인 상태 잠금과 실패하는 대신 묻는 훅 |

모든 기준은 사례 하나 이상이 담는다. `tests/test_e2e_eval_worker_cases.py`가 과제마다 증명한다. 수정하지 않은
픽스처는 `hidden-tests`에서 실패하고 `regressions`는 통과하며, `tasks/reference/<과제>/`의 참조 해법은 둘 다 통과한다.

## 실행의 위임 방식

각 프롬프트는 할당이다. 허용 경로, 실행할 검사, 범위를 넓히지 말고 보고하라는 지시가 들어 있다. 변형
`worker-sonnet`과 `worker-opus`는 `HEI5ENBUG_ASSIGNED_ROLE=worker`를 설정해 플러그인이 세션에 할당받은 worker
컨텍스트를 주게 하고, Claude Code 모델만 다르게 둔다. 그래서 시험 대상 모델이 같은 시작 상태, 같은 플러그인
리비전, 같은 검사, 같은 effort에서 스스로 작업하며 다시 위임하지 않는다.

## 실행과 기록

```text
python3 evals/e2e/harness/cli.py run --campaign worker-models --tasks T68,T69,T70,T71,T72,T73,T74,T75,T76,T77 --variants worker-sonnet,worker-opus --reps 1
python3 evals/e2e/harness/cli.py pilot-check --campaign worker-models
python3 evals/e2e/harness/cli.py worker-results --campaign worker-models
```

`worker-results`는 실행마다 호스트 기록에서 모델과 effort를 읽는다. 끝난 실행이 없거나, 메인 세션 외의 역할을
시작했거나, 다른 모델이나 effort로 돈 사례가 있으면 쓰지 않고 거부한다. 통과하면 여기에 `results.json`을 쓴다. 파일에는
사례·모델별 `passed`, `model`, `effort`, `cost_usd`와, 모델별로 모든 시도의 `cost_usd`, 해결한 수 `solved`,
`cost_per_solved_task`가 들어 있다. 하나도 풀지 못한 모델의 `cost_per_solved_task`는 `null`이다. 측정하기 전의 파일은
`"measured": false`인 대기 형태뿐이다.

## 규칙

기준을 담은 사례 중에서 Opus가 Sonnet보다 엄밀하게 더 많이 통과할 때만 그 기준을 어려운 작업으로 센다. 어려운
작업은 `opus-worker`, 쉬운 작업은 `worker`, 그 밖의 모든 작업은 동률일 때도 `sonnet-worker`가 맡는다.
`worker-results`는 규칙이 돌려준 기준을 출력하고, `tests/test_worker_tier_rule.py`는 규칙이 기준을 하나 이상
돌려줄 때만 저장소에 Opus worker 정의, 레지스트리 항목, 경로 문구가 있는지 확인한다. 기준이 하나도 없으면 Opus
계층을 더하지 않고 그 결과를 여기에 적는다.

결과: 아직 측정하지 않았다.

## Opus worker 후보

후보는 측정이 정하기 전까지 `agents/`, 레지스트리, 경로 문구 밖에 둔다. `opus-candidate/`에는 공유 worker 본문과
`claude-opus-5-5`, `high` 고정을 담은 `opus-worker.md.candidate`와 그 한국어 미러가 있다. `opus_candidate.py`는 어려운
작업으로 판정된 기준을 받아 후보를 체크아웃에 적용하고, `tests/test_worker_tier_rule.py`는 후보가 현재 worker
정의와 같게 유지되는지 확인한다.

```text
python3 evals/e2e/worker-cases/opus_candidate.py <저장소 루트> <기준>[,<기준>...]
```

이 스크립트는 에이전트와 미러를 더하고, `sonnet-worker`와 같은 실행기 대체 항목으로 `claude_agents`에 등록하며,
`instructions/claude-agents.md`와 `instructions/model-routing.md`의 경로 문장을 고친다. 같은 변경에서 그 문장들의 한국어
미러, worker 에이전트를 나열하는 문서, 보호 절 밖의 `AGENTS.md` worker 표, 매니페스트 설명, 이전 문장을 고정한 테스트도
함께 갱신한다.
