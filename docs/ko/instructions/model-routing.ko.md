# 모델 라우팅

> 영어 원본: [model-routing.md](../../../instructions/model-routing.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트는 실행 중 읽거나 사용하지 않는다.

이 파일은 공통 라우팅을 정의한다. 호스트 에이전트 규칙이 읽는 시점을 정하고 역할의 실행·검증 방법을
설명한다. 선택된 메인 모델이나 사고 강도를 바꾸지 않는다.

## 목적과 출력 위치에 따른 라우팅

위임할 작업의 목적과 결과를 저장할 위치를 함께 기준으로 삼는다.

| 작업 | 라우팅 |
|---|---|
| 메인이 맡는 작업 | [세션 소유권 규칙](session/common.ko.md)을 따른다. |
| 실제 저장소나 스킬을 수정하는 구현 | 호스트의 구현 실행 규칙과 고정된 구현 역할을 따른다. |
| UI 코드, 시각 디자인, 다이어그램이나 이미지, 기술 설계 문서 초안 작성 | `design` 기능을 쓴다. 다만 호스트 세션 파일이 메인 세션에 맡긴 종류는 예외다. |
| 실제 저장소나 스킬을 수정하는 구현, 또는 이슈 트래커와 풀 리퀘스트 서비스 같은 외부 도구 작업 | `implementation` 기능을 쓴다. |
| 범위가 한정된 로컬 근거 수집 | 위임이 허용되고 유용할 때 호스트의 scout 역할을 쓴다. |
| 공개 자료의 읽기 전용 조사 | 공개 도구를 사용할 수 있고 고정 설정을 확인한 경우에만 `investigation` 기능을 쓴다. 그렇지 않으면 메인 세션에서 계속한다. |
| 스킬 검토 역할(검토 페르소나, grader, comparator, analyzer) | 아래 표의 reviewer 경로를 쓴다. |
| Skill Builder 시험 실행 및 기타 비검토 참여자 | 아래 Skill Builder 어댑터에서 호스트의 상위 모델을 쓴다. |
| 임시 시험 결과물 | 평가 작업 공간에 둔다. 이를 승인된 구현으로 간주하지 않는다. |

공개 조사는 주장, 공개 URL이나 파일 위치, 뒷받침하는 근거, 모순, 공백을 수집한다. 계획, 아키텍처, 승인
결정은 내리지 않는다. 기존 서비스 접근 규칙을 계속 적용한다.

## 역할 설정 유지

GPT Luna는 `gpt-5.6-luna`와 `high` 또는 `xhigh`로만 명시적으로 고정하며, 다른 Luna 버전을 선택하지 않는다.
`max_effort`가 있는 항목은 하한인 `effort`에서 시작한다. 할당이 여러 컴포넌트에 걸치거나 공개 계약, 보안, 동시성, 파싱,
훅이나 가드에 영향을 주거나 낮은 사고 강도의 결과가 거부된 경우에만 실행기의 `--effort`나 Codex 생성 시 사고 강도로
`max_effort`까지 높인다. Claude Code 플러그인 에이전트를 포함해 `max_effort`가 없는 항목은 고정된 사고 강도를 유지한다.
사용자가 모델이나 사고 강도를 지정한 위임 작업은 예외이며, [Claude Code 에이전트](claude-agents.ko.md#요청한-모델이나-사고-강도)와
[Codex 에이전트](codex-agents.ko.md#요청한-모델이나-사고-강도)의 호스트 에이전트 규칙을 따른다. worker 설정은 허용된 값 중에서 사용자가 명시적으로 선택한 값이며, 실행 중에 바꿔 쓰는 대체가 아니다. 호스트에서 이 설정을
확인할 수 없으면 해당 위임을 중지하고 지정된 다른 모델 계열의 fallback이나 메인 세션을 사용한다. 최신 릴리스 자동 갱신에서도
이 사용자 지정 고정값을 제외한다.

별도로 승인된 비교 결과가 한정된 범위의 변경을 정당화하지 않는 한 다음 운영 설정을 사용한다.

| 역할 | Codex | Claude Code |
|---|---|---|
| 로컬 scout | `gpt-5.6-luna`, `high`(최대 `xhigh`) | 읽기 전용 `role_runner.py scout`로 `gpt-5.6-luna`, `high`(최대 `xhigh`). 대체 경로는 `scout`(`claude-sonnet-5-5`, `medium`) |
| 구현 worker | `role_runner.py implementation --host codex`로 `claude-sonnet-5-5`, `high`(최대 `xhigh`); 대체는 `codex_worker_model`·`codex_worker_effort` 설정(`gpt-5.6-luna` 또는 `gpt-6.1-sol`, `high` 또는 `xhigh`, 기본값 `gpt-5.6-luna`, `high`)의 `worker` 역할 | `implementation_worker`가 `auto`(기본값)이면 메인 세션이 할당마다 고른다. 쉬운 작업은 `worker_model`·`worker_effort` 설정(기본값 `claude-haiku-5-5`, `high`)의 `worker`, 보통이거나 어려운 작업은 `claude-sonnet-5-5`, `high`의 `sonnet-worker`를 쓴다. Claude 경로가 실패하거나 사용량 한도로 중단되면 `role_runner.py implementation --fallback`과 `gpt-6.1-sol`, `high`를 쓴다. 고정 설정은 한 경로를 강제한다: `sonnet`, `sol`, `codex`(`role_runner.py worker`와 `gpt-5.6-luna`), `haiku`(대체 경로는 `role_runner.py agent --name hei5enbug-agent-setup:worker --fallback`과 `gpt-6.1-sol`) |
| 공개 researcher | 웹 검색을 쓰는 `role_runner.py researcher`로 `gpt-5.6-luna`, `high`(최대 `xhigh`) | 웹 검색을 쓰는 `role_runner.py researcher`로 `gpt-5.6-luna`, `high`(최대 `xhigh`). 대체 경로는 웹 검색과 가져오기 도구를 가진 `scout`(`claude-sonnet-5-5`, `medium`) |
| Designer(`design` 기능) | `designer` 역할로 `gpt-6-astra`, `high`(최대 `xhigh`). 대체 경로는 `role_runner.py agent --name designer --fallback`으로 `claude-opus-5-5`, `high`(최대 `xhigh`) | `designer` 에이전트로 `claude-opus-5-5`, `xhigh`. 대체 경로는 `role_runner.py design`으로 `gpt-6-astra`, `high`(최대 `xhigh`) |
| Skill Builder 시험 실행 및 기타 비검토 참여자 | `gpt-6.1-sol`, `xhigh` | `claude-opus-5-5`, `high` |
| 스킬 검토 역할(검토 페르소나, grader, comparator, analyzer) | `role_runner.py review`로 `claude-opus-5-5`, `high`(최대 `xhigh`); 대체는 `gpt-6.1-sol`, `high`(최대 `xhigh`)의 `reviewer` | `role_runner.py reviewer`로 `review_model` 설정값(기본 `gpt-6-astra`), `high`(최대 `xhigh`); 대체는 `claude-opus-5-5`, `high`의 `reviewer` |

결과를 신뢰하기 전에 호스트 기록과 관련된 비밀이 아닌 설정으로 역할의 실제 모델과 사고 강도를 확인하거나, 호스트
에이전트 규칙이 정한 강제 장치(Mod의 역할 고정, 역할 실행기의 검증)에 의존한다. 요청한 값, 역할 이름, agent guard
승인만으로 실제 모델이 확인되지는 않는다. 설정이 없거나 충돌하거나 역할 요구보다 낮으면 허가된 메인 세션 대체 경로를
쓴다. 위임을 가능하게 하려고 모델이나 사고 강도를 조용히 바꾸거나 사용자 설정을 변경하지 않는다.

공개 조사를 맡기기 전에 호스트에 필요한 공개 검색 및 가져오기 도구가 노출되는지, researcher 역할이 고정된
모델과 사고 강도로 실행되는지 확인한다. 둘 중 하나라도 충족하지 않으면 기존 서비스 접근 규칙에 따라 메인
세션에서 계속한다.

## 스킬 검토와 실행

스킬 검토 역할은 검토 페르소나, grader, comparator, analyzer 등을 맡는 읽기 전용 판단 작업이다. 호스트의
스킬 작업자 규칙에 따라 먼저 표의 reviewer 경로를 사용한다. 그 경로가 없거나 인증되지 않았거나 사용량 제한에
걸리거나 지정한 모델을 시작하지 못하거나 시간 초과되거나 모델 근거가 없으면 표의 대체 모델로 플러그인의
`reviewer`를 사용한다. reviewer는 지적 결과만 반환한다. 메인 세션은 같은 자료를 한 번 직접 검토한 뒤 최종 판단한다.
추가 검토는 하지 않는다.

Skill Builder의 시험 실행과 기타 비검토 참여자는 표에 나온 호스트의 상위 모델을 사용한다. Skill Builder가
채점, 비교 또는 분석을 요청해도 검토 역할에는 reviewer 경로를 적용한다. 대상 스킬의 메타데이터와 frontmatter는
이 설정을 덮어쓰지 않는다. `scout`를 검토 역할로 쓰거나 `reviewer`에 시험 출력을 작성시키지 않는다.

일반적인 실행 방식 비교에서는 양쪽의 모델과 사고 강도를 고정한다. 구체적으로 승인된 모델 또는 사고 강도
비교에서는 임시 평가 작업 공간에서 미리 고정한 후보 설정 하나만 바꿀 수 있다. 이 비교로 운영 역할 설정을
변경하거나 시험 결과를 저장소에 반영해서는 안 된다. 충분한 근거가 없는 후보는 비활성 상태로 둔다. 시험한
작업 범위에서 변경을 정당화하는 결과 품질과 반복 실행 토큰의 비교 근거가 있을 때만 운영 설정을 바꾼다.

## 호스트와 모델 정체성 분리

메인 모델이 바뀌어도 실행 호스트는 그대로 유지된다.

메인 모델이나 프로필을 바꾼 뒤, 또는 세션 재개 후 위임 작업을 호출하기 전에 실제 역할 설정과 관련 도구의
사용 가능성을 다시 확인한다. 각 역할의 고정 모델과 사고 강도를 유지한다. worker의 모델을 메인 모델과
같게 바꾸지 않는다.

독립 검토자는 실행 호스트가 아니라 결과물을 작성한 실제 모델 계열을 기준으로 고른다. 검토자 범위, 시점, 승인은
[독립 모델 검증](independent-model-validation.ko.md)의 규칙을 따르며, 스킬 검토 역할에만 쓰는 `review_model` 설정은
쓰지 않는다. 두 계열이 모두 실질적으로 기여했으면 그 기여를 기록한다. 최종 작성자의
모델 계열이 검토자 한 명을 결정한다. 모든 기여자에 대한 독립성을 주장하거나 검토 호출을 추가하지
않는다.

## 기능별 고정값

이 고정값의 원본은 `config/model-registry.json`이며, 아래 표는 그 `capabilities` 항목과 같아야 한다.

| 기능 | Claude Code 기본 | Claude Code 대체 | Codex 기본 | Codex 대체 |
|---|---|---|---|---|
다섯 기능은 `investigation`(로컬과 공개 조사), `implementation`(저장소 수정과 외부 도구 작업), `design`(UI 코드,
시각 디자인, 다이어그램이나 이미지, 기술 설계 문서 초안 작성), `language`(텍스트 초안 작성과 다듬기), `review`(독립 검토)다.
모든 대체 항목은 다른 모델 계열이다. 다른 호스트의 모델이 필요한 대체 항목은 역할 실행기를 거치고, 현재 호스트에서 바로 실행할 수 있는 대체 항목은 이름이 붙은 에이전트를 쓴다. 실행기의 동작은 [Claude Code 에이전트](claude-agents.ko.md#역할-실행기)에 있다.

| 기능 | Claude Code 기본 | Claude Code 대체 | Codex 기본 | Codex 대체 |
|---|---|---|---|---|
| investigation | `gpt-5.6-luna` / `high`(최대 `xhigh`) (runner) | `claude-sonnet-5-5` / `medium` (`scout`) | `gpt-5.6-luna` / `high`(최대 `xhigh`) (`scout`) | `claude-sonnet-5-5` / `medium` (runner) |
| implementation | `claude-sonnet-5-5` / `high` (`sonnet-worker`) | `gpt-6.1-sol` / `high`(최대 `xhigh`) (runner) | `claude-sonnet-5-5` / `high`(최대 `xhigh`) (runner) | Codex worker model 설정, 레지스트리 쌍 `gpt-5.6-luna` / `high`(최대 `xhigh`) (`worker`) |
| design | `claude-opus-5-5` / `xhigh` (`designer`) | `gpt-6-astra` / `high`(최대 `xhigh`) (runner) | `gpt-6-astra` / `high`(최대 `xhigh`) (`designer`) | `claude-opus-5-5` / `high`(최대 `xhigh`) (runner) |
| language | `gpt-6.1-sol` / `high`(최대 `xhigh`) (runner) | `claude-opus-5-5` / `high`(최대 `xhigh`) (runner) | `gpt-6.1-sol` / `high`(최대 `xhigh`) (runner) | `claude-opus-5-5` / `high`(최대 `xhigh`) (runner) |
| review | `gpt-6-astra` / `high`(최대 `xhigh`) (runner) | `claude-opus-5-5` / `high` (`reviewer`) | `claude-opus-5-5` / `high`(최대 `xhigh`) (runner) | `gpt-6.1-sol` / `high`(최대 `xhigh`) (`reviewer`) |

Claude Code의 `review` 기본 항목은 기본 모델 대신 `review_model` 설정을 쓴다. 독립 검증은 이 설정을 쓰지 않는다. 이 기본 항목이 Claude 모델로 정해지면
Claude Code의 `review` 대체 항목은 `reviewer` 항목 대신 역할 실행기로 `gpt-6-astra` / `high`(최대 `xhigh`)를 실행한다. `(runner)`로
표시한 항목은 역할 실행기로 실행하고, 에이전트 이름으로 표시한 항목은 그 플러그인 에이전트를 고정된 모델과 사고 강도로
실행한다.
