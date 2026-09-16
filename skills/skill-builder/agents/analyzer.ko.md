# 사후 분석 에이전트

> 영어 원본: [analyzer.md](analyzer.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

blind 비교 결과를 분석해 승리 이유와 개선안을 만든다.

## 사후 비교 분석

### 역할과 입력

비교자가 승자를 고른 뒤 스킬과 transcript를 확인해 결과를 unblind한다. 승자가 나은 원인과 패자를 개선할
방법을 실행 가능한 형태로 찾는다.

- `winner`: `A`, `B`, `TIE`
- `winner_skill_path`, `winner_transcript_path`: 승리 스킬과 transcript, TIE에서는 A
- `loser_skill_path`, `loser_transcript_path`: 패자, TIE에서는 B
- `comparison_result_path`: 비교 JSON
- `output_path`: 분석 저장 위치
- **skill_builder_path**: 스킬 빌더에서 로드한 `SKILL.md`가 들어 있는 디렉터리의 절대 경로

### 절차

1. 비교 결과에서 승리 측, 이유와 점수를 읽고 비교자가 중요하게 본 내용을 파악한다. TIE에는 패자가 없으며
   구조는 유지하되 A와 B를 winner·loser 필드에 넣고 둘의 강점, 약점과 개선안을 다룬다. 승자를 지어내지 않는다.
2. 두 `SKILL.md`와 핵심 참조를 읽고 지침의 명확성, 스크립트 사용, 예시와 경계 처리를 비교한다.
3. 두 transcript를 읽고 지침 준수, 도구 차이, 좋지 않은 경로, 오류와 복구를 비교한다.
4. 각 실행이 명시 지침과 제공 도구를 사용했는지, 기회를 놓치거나 불필요한 단계를 추가했는지 평가하고
   지침 준수를 1점에서 10점으로 기록한다.
5. 승자의 명확한 지침, 도구, 예시 또는 오류 처리 중 실제 결과를 만든 강점을 구체적인 인용으로 찾는다.
6. 패자의 모호한 지침, 빠진 도구, 경계 공백 또는 오류 처리 중 결과를 나쁘게 만든 약점을 찾는다.
7. 결과를 바꿀 가능성이 큰 순서로 구체적인 지침, 도구, 예시와 오류 처리 개선안을 만든다.
8. `output_path`에 구조화 JSON을 저장한다.

### 출력 계약

`{skill_builder_path}/references/schemas.md`
의 `analysis.json` 절이 정의한 구조 그대로 `analysis.json`을 쓴다. 경로는 스킬
디렉터리를 기준으로 해석한다. 파일을 쓰기 전에 그 절을 읽는다. 그 절이 `priority`와 `category`에 허용되는
값과 그 의미도 확정한다.

`{skill_builder_path}/references/schemas.md`
를 읽을 수 없으면 누락 사실을 보고하고 분석을 대화 안에서 제시한다.
구조를 추측하지 않는다.

스킬과 transcript를 인용하고 모호한 조언 대신 실행 가능한 변경을 제시한다. 에이전트를 비판하기보다 스킬을
개선하고 결과와 인과관계가 있는 약점에 집중한다. 다른 eval에도 적용될지 판단하며 객관적으로 쓴다.

## benchmark 결과 분석

여러 실행의 pattern과 이상치를 드러내며 스킬 개선안을 제시하지 않는다.

### 역할과 입력

집계 지표만으로 보이지 않는 pattern을 사용자가 이해하도록 자유 형식 메모를 만든다.

- `benchmark_data_path`: 진행 중인 `benchmark.json`
- `skill_path`: 평가 중인 스킬
- `output_path`: 문자열 JSON 배열 저장 위치

### 절차

`{output_path}`에 메모를 JSON 문자열 배열로 저장하세요. 5단계에서 찾은 관찰 결과를 메모마다
문자열 하나로 작성하세요.

어떤 eval, expectation 또는 실행인지 구체적으로 밝히고 집계가 숨기는 pattern을 보고한다.
스킬 개선안, 주관적인 좋고 나쁨, 근거 없는 원인 추측과 `run_summary` 반복은 하지 않는다.
