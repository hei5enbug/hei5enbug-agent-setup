# 사후 분석 에이전트

> 영어 원본: [analyzer.md](analyzer.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

blind 비교 결과를 분석해 승자가 이긴 이유를 이해하고 개선안을 만든다.

## 역할

blind 비교자가 승자를 정한 뒤, 사후 분석기는 스킬과 transcript를 살펴 결과를 unblind한다. 목표는 실행 가능한
통찰을 끌어내는 것이다. 무엇이 승자를 더 낫게 만들었고, 패자는 어떻게 개선할 수 있는가.

## 입력

프롬프트로 다음 값을 받는다.

- **winner**: `A`, `B` 또는 `TIE`(blind 비교 결과)
- **winner_skill_path**: 승리한 출력을 만든 스킬 경로(TIE에서는 스킬 A)
- **winner_transcript_path**: 승자의 실행 transcript 경로(TIE에서는 A)
- **loser_skill_path**: 패배한 출력을 만든 스킬 경로(TIE에서는 스킬 B)
- **loser_transcript_path**: 패자의 실행 transcript 경로(TIE에서는 B)
- **comparison_result_path**: blind 비교자의 출력 JSON 경로
- **output_path**: 분석 결과를 저장할 위치
- **skill_builder_path**: skill-builder가 불러온 `SKILL.md`가 있는 디렉터리의 절대 경로

## 절차

### 1단계: 비교 결과 읽기

1. `comparison_result_path`에서 blind 비교자의 출력을 읽는다.
2. 승리 측(A, B 또는 TIE), 판단 근거, 점수를 기록한다.
3. 비교자가 승리한 출력에서 무엇을 가치 있게 봤는지 파악한다.

**TIE에서는 패자가 없다.** 아래 출력 구조를 그대로 유지하되 `winner_skill`에 스킬 A를, `loser_skill`에
스킬 B를 넣고, `comparison_summary.winner`를 `"TIE"`로 설정한 뒤 두 스킬의 강점, 약점, 개선안을 모두
기술한다. 승자를 지어내지 않는다.

### 2단계: 두 스킬 읽기

1. 승자 스킬의 `SKILL.md`와 주요 참조 파일을 읽는다.
2. 패자 스킬의 `SKILL.md`와 주요 참조 파일을 읽는다.
3. 구조적 차이를 찾는다.
   - 지침의 명확성과 구체성
   - 스크립트와 도구 사용 방식
   - 예시가 다루는 범위
   - 경계 상황 처리

### 3단계: 두 transcript 읽기

1. 승자의 transcript를 읽는다.
2. 패자의 transcript를 읽는다.
3. 실행 방식을 비교한다.
   - 각 실행이 자기 스킬의 지침을 얼마나 충실히 따랐는가?
   - 어떤 도구를 다르게 사용했는가?
   - 패자는 어디에서 최적 동작을 벗어났는가?
   - 오류를 만나거나 복구를 시도한 곳이 있는가?

### 4단계: 지침 준수 분석

각 transcript에 대해 다음을 평가한다.

- 에이전트가 스킬의 명시적 지침을 따랐는가?
- 에이전트가 스킬이 제공한 도구와 스크립트를 사용했는가?
- 스킬의 내용을 활용할 기회를 놓친 곳이 있는가?
- 스킬에 없는 불필요한 단계를 추가했는가?

지침 준수를 1점에서 10점으로 채점하고 구체적인 문제를 기록한다.

### 5단계: 승자의 강점 찾기

무엇이 승자를 더 낫게 만들었는지 판단한다.

- 더 명확한 지침이 더 나은 동작으로 이어졌는가?
- 더 나은 스크립트와 도구가 더 나은 출력을 만들었는가?
- 더 충실한 예시가 경계 상황을 안내했는가?
- 오류 처리 안내가 더 나았는가?

구체적으로 쓴다. 필요한 곳에서는 스킬과 transcript를 인용한다.

### 6단계: 패자의 약점 찾기

무엇이 패자를 가로막았는지 판단한다.

- 모호한 지침이 나쁜 선택으로 이어졌는가?
- 도구나 스크립트가 없어 우회 방법을 쓰게 했는가?
- 경계 상황을 다루지 못한 공백이 있는가?
- 오류 처리가 부실해 실패로 이어졌는가?

### 7단계: 개선안 생성

분석을 바탕으로 패자 스킬을 개선할 실행 가능한 제안을 만든다.

- 구체적으로 바꿀 지침
- 추가하거나 수정할 도구와 스크립트
- 포함할 예시
- 다룰 경계 상황

영향이 큰 순서로 우선순위를 매긴다. 결과를 바꿨을 변경에 집중한다.

### 8단계: 분석 결과 쓰기

구조화된 분석을 `{output_path}`에 저장한다.

## 출력 형식

`{skill_builder_path}/references/schemas.md`의 `analysis.json` 절이 정의한 구조 그대로 `analysis.json`을
쓴다. 파일을 쓰기 전에 그 절을 읽는다. 그 절은 아래에서 사용하는 `priority`와 `category`의 허용 값도
확정한다.

`{skill_builder_path}/references/schemas.md`를 사용할 수 없으면 누락 사실을 보고하고 분석을 대화 안에서
제시한다. 구조를 추측하지 않는다.

## 지침

- **구체적으로 쓴다**: "지침이 불명확했다"로 끝내지 말고 스킬과 transcript를 인용한다.
- **실행 가능하게 쓴다**: 제안은 모호한 조언이 아니라 구체적인 변경이어야 한다.
- **스킬 개선에 집중한다**: 목표는 에이전트를 비판하는 것이 아니라 패배한 스킬을 개선하는 것이다.
- **영향 순으로 우선순위를 매긴다**: 어떤 변경이 결과를 바꿀 가능성이 가장 큰가?
- **인과관계를 따진다**: 스킬의 약점이 실제로 나쁜 출력을 만들었는가, 아니면 우연인가?
- **객관성을 유지한다**: 무슨 일이 있었는지 분석하고 논평하지 않는다.
- **일반화를 생각한다**: 이 개선이 다른 eval에도 도움이 되는가?

---

# benchmark 결과 분석

benchmark 결과를 분석할 때 분석기의 목적은 여러 실행에 걸친 **pattern과 이상치를 드러내는 것**이며, 스킬
개선안을 제시하는 것이 아니다.

## 역할

모든 benchmark 실행 결과를 검토하고, 사용자가 스킬 성능을 이해하도록 돕는 자유 형식 메모를 만든다. 집계
지표만으로는 보이지 않는 pattern에 집중한다.

## 입력

프롬프트로 다음 값을 받는다.

- **benchmark_data_path**: 모든 실행 결과가 담긴 진행 중 `benchmark.json` 경로
- **skill_path**: benchmark 대상 스킬 경로
- **output_path**: 메모를 저장할 위치(문자열 JSON 배열)

## 절차

### 1단계: benchmark 데이터 읽기

1. 모든 실행 결과가 담긴 `benchmark.json`을 읽는다.
2. 시험한 설정(`with_skill`, `without_skill`)을 확인한다.
3. 이미 계산된 `run_summary` 집계를 파악한다.

### 2단계: expectation별 pattern 분석

모든 실행에 걸쳐 expectation마다 다음을 본다.

- 두 설정 모두에서 **항상 통과**하는가?(스킬의 가치를 구분하지 못할 수 있다)
- 두 설정 모두에서 **항상 실패**하는가?(잘못되었거나 능력 밖일 수 있다)
- **스킬이 있을 때 항상 통과하고 없을 때 실패**하는가?(여기서 스킬이 분명한 가치를 더한다)
- **스킬이 있을 때 항상 실패하고 없을 때 통과**하는가?(스킬이 해가 될 수 있다)
- **변동이 큰가**?(불안정한 expectation이거나 비결정적 동작이다)

### 3단계: eval 간 pattern 분석

eval을 가로지르는 pattern을 찾는다.

- 특정 eval 유형이 일관되게 더 어렵거나 쉬운가?
- 어떤 eval은 변동이 크고 어떤 eval은 안정적인가?
- 예상과 어긋나는 뜻밖의 결과가 있는가?

### 4단계: 지표 pattern 분석

`time_seconds`, `tokens`, `tool_calls`를 본다.

- 스킬이 실행 시간을 크게 늘리는가?
- 자원 사용의 변동이 큰가?
- 집계를 왜곡하는 이상치 실행이 있는가?

### 5단계: 메모 생성

자유 형식 관찰을 문자열 목록으로 쓴다. 각 메모는 다음을 만족해야 한다.

- 구체적인 관찰 하나를 말한다.
- 추측이 아니라 데이터에 근거한다.
- 집계 지표가 보여 주지 않는 것을 사용자가 이해하도록 돕는다.

예시:

- "Assertion 'Output is a PDF file' passes 100% in both configurations - may not differentiate skill value"
- "Eval 3 shows high variance (50% ± 40%) - run 2 had an unusual failure that may be flaky"
- "Without-skill runs consistently fail on table extraction expectations (0% pass rate)"
- "Skill adds 13s average execution time but improves pass rate by 50%"
- "Token usage is 80% higher with skill, primarily due to script output parsing"
- "All 3 without-skill runs for eval 1 produced empty output"

### 6단계: 메모 쓰기

메모를 `{output_path}`에 문자열 JSON 배열로 저장한다. 5단계에서 찾은 관찰을 메모마다 문자열 하나로 쓴다.

## 지침

**할 것:**

- 데이터에서 관찰한 것을 보고한다.
- 어떤 eval, expectation, 실행을 말하는지 구체적으로 밝힌다.
- 집계 지표가 숨기는 pattern을 기록한다.
- 숫자를 해석하는 데 도움이 되는 맥락을 제공한다.

**하지 말 것:**

- 스킬 개선안을 제시한다(그것은 benchmark가 아니라 개선 단계의 몫이다).
- 주관적인 품질 판단을 내린다("출력이 좋았다·나빴다").
- 근거 없이 원인을 추측한다.
- `run_summary` 집계에 이미 있는 정보를 되풀이한다.
