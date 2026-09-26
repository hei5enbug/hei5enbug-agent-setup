# 심층 인터뷰의 호스트 간 질문 UI 경로

> 영어 원본: [ask-ui.md](ask-ui.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

심층 인터뷰가 모든 질문을 사용자에게 제시하는 방식을 정의한다. 인터뷰는 일반 텍스트로 객관식 질문을
흉내 내지 않고 호스트 에이전트의 네이티브 질문 UI로 진행한다.

질문이나 확인을 제시하기 직전에 이 파일을 읽는다. Round 0 토폴로지 확인, `SKILL.md` 공통 절차 4단계의 답변 해석 확인,
`references/specification-gates.md`의 종료 단계에 있는 목표 재진술·명세 승인·실행 연결 선택에 적용한다.

## 목차

- 핵심 원칙
- 통합 질문 모델
- 호스트별 경로
- 알 수 없는 호스트의 대체 경로
- 답변 처리
- 선택 체크리스트

## 핵심 원칙

- **라운드마다 질문 하나.** 도구가 한 번에 여러 질문을 허용해도 묶지 않는다.
  각 답 뒤 모호성을 계산하므로 질문을 하나씩 제시한다.
- **네이티브 구조화 질문 도구가 있으면 항상 사용한다.** 선택 UI는 더 정확한 답과 사용자 지정 답을 지원한다.
- 네이티브 도구가 있는데 일반 텍스트로 객관식 질문을 만들지 않는다. 현재 런타임에 네이티브 질문 도구가
  없을 때만 아래 인라인 대체 형식을 사용한다.
- **사용자 언어를 유지한다.** 질문, 짧은 제목과 모든 선택지의 `label`, `description`을 대화 언어로 번역한다.
  코드 식별자, 파일 경로, 명령과 고정 상태 토큰은 영어로 유지한다.
- **질문을 이해하기 쉽게 쓴다.** 고등학생이 선택을 이해할 만큼 설명하고 선택에 따른 변화와 주요 장단점이나
  위험을 밝힌다.
- **추천 순서로 정렬한다.** 가장 좋은 선택부터 놓고 추천 하나의 레이블 끝에 정확히 ` (추천)`을 붙인다.

## 통합 질문 모델

모든 질문은 호스트와 관계없이 다음 논리 형태로 매핑한다.

| 필드 | 의미 | 호스트 간 제약 |
|---|---|---|
| `question` | 사용자가 읽는 전체 질문 | `SKILL.md`의 공통 절차와 `references/specification-gates.md`의 다음 질문 선택에 정한 Round, Component, Targeting, Ambiguity 줄을 앞에 붙인다. |
| `header` | 질문의 짧은 레이블 | Claude Code에서 유효하도록 12자 이내로 둔다. |
| `options[]` | 관련 선택지 | 호스트 스키마의 개수 범위 안에서 짧은 `label`과 쉬운 장단점 `description`을 둔다. 추천을 먼저 놓고 하나에 ` (추천)`을 붙인다. |
| 사용자 지정 텍스트 | 사용자가 직접 답할 수 있음 | Claude의 Other와 OpenCode가 제공하며 인라인 대체 형식에는 Custom을 명시한다. |
| 다중 선택 | 보통 단일 선택 | 실제로 여러 답을 허용할 때만 다중 선택을 켠다. |

사용할 도구 스키마가 허용하는 선택지 수를 확인한다. 아래 호스트별 내용은 작성 당시 알려진 범위를 기록한다.

## 호스트별 경로

사용 가능한 질문 도구로 런타임을 확인하고 해당 도구를 사용한다. 판단할 수 없으면 네이티브 도구를 먼저
시도하고 도구 집합에 없을 때 인라인 대체 형식을 사용한다.

### Claude Code: `AskUserQuestion`

```json
{
  "questions": [
    {
      "question": "Round 2 | Component: Ingestion | Targeting: Constraints | Why now: ... | Ambiguity: 58%\n\nShould the importer accept gzipped CSVs, or only plain .csv?",
      "header": "CSV input",
      "options": [
        {
          "label": "Plain .csv only (추천)",
          "description": "Choose this if the first version should stay simple. Users can upload only normal .csv files, and compressed files are rejected with a clear error."
        },
        {
          "label": "Also accept .gz",
          "description": "Choose this if users often have large compressed files. It adds more implementation work because uploads must be decompressed and failure cases must be handled."
        }
      ],
      "multiSelect": false
    }
  ]
}
```

- 호출당 질문은 1개에서 4개지만 정확히 1개를 사용한다. 질문당 선택지는 2개에서 4개이며 `header`는 12자 이하다.
- 사용자는 자동으로 Other 자유 입력 선택지를 받으므로 Custom을 직접 추가하지 않는다.
- Agent나 Task 도구로 만든 서브에이전트 안에서는 `AskUserQuestion`을 사용할 수 없다.
  모든 질문은 메인 세션에서 한다. 읽기 전용 검토자와 자동 답변 조사는 서브에이전트로 실행할 수 있지만
  결과를 메인 세션에 반환하고 메인 세션이 사용자에게 질문한다.

### OpenCode: `question`

```json
{
  "questions": [
    {
      "question": "Round 2 | Component: Ingestion | Targeting: Constraints | Why now: ... | Ambiguity: 58%\n\nShould the importer accept gzipped CSVs, or only plain .csv?",
      "header": "CSV input",
      "options": [
        {
          "label": "Plain .csv only (추천)",
          "description": "첫 버전을 단순하게 유지할 때 선택한다. 일반 .csv 파일만 업로드할 수 있고 압축 파일은 명확한 오류와 함께 거부한다."
        },
        {
          "label": "Also accept .gz",
          "description": "사용자가 큰 압축 파일을 자주 다룰 때 선택한다. 업로드 압축 해제와 실패 사례 처리가 필요하므로 구현 작업이 늘어난다."
        }
      ],
      "multiple": false
    }
  ]
}
```

- 다중 선택 필드는 `multiSelect`가 아니라 `multiple`이다.
- 사용자가 답할 때까지 작업이 멈추며 UI에서 사용자 지정 텍스트를 기본으로 지원한다.
- `question`은 권한 키다. 거부되면 아래 인라인 형식을 사용한다.

### Codex: Plan 모드와 `request_user_input`

- 지원되는 구조화 질문 절차가 있는 Plan 모드에서 인터뷰를 실행한다. 현재 대화가 Plan 모드가 아니면
  `/plan` 또는 같은 기능으로 전환하도록 알리고 턴을 끝낸다. 전환 뒤에만 인터뷰를 재개한다.
- 개발 중 기능인 `features.default_mode_request_user_input`을 추천하거나 켜지 않는다.
- Plan 모드에서는 `request_user_input`을 우선하고 질문은 1개에서 3개 중 정확히 1개를 사용한다.
  선택지에는 `label`, `description`, 질문에는 `id`, `header`, `question`, `options`를 둔다.
- MCP 서버가 `form`, `openai/form`, `url` 구조화 elicitation을 제공하면 사용할 수 있다.
- Plan 모드를 사용할 수 없거나 사용자가 전환을 거절하거나 전환 뒤에도 구조화 기능이 없을 때만
  인라인 대체 형식을 사용한다. Default 모드에서 시작했다는 이유만으로 조용히 대체하지 않는다.

### 다른 호스트: 인라인 대체 형식

네이티브 도구가 없으면 구분된 질문 블록 하나만 다음 형식으로 표시하고 턴을 끝내 답을 기다린다.

```md
## Question {N}: {Topic}        <!-- 또는 ## 질문 {N}: {주제} -->

{고등학생이 이해할 3줄에서 10줄의 설명: 결정의 이유, 답에 따른 변화, 선택지의 장단점,
모호하게 둘 위험과 A를 추천하는 이유}

- A) {가장 추천하는 선택} (추천)
- B) {두 번째 선택}
- C) {세 번째 선택}
- D) 직접 입력 / Custom

**답변 / Your answer:**
<!-- 선택 문자나 직접 답변을 아래에 입력 -->
```

- 선택지를 추천 순서로 놓고 `A)` 레이블 끝에만 ` (추천)`을 붙인다.
- 각 설명은 선택의 의미, 변화와 주요 장단점이나 위험을 고등학생이 이해할 만큼 자세히 쓴다.
- 항상 `D) 직접 입력 / Custom`을 포함한다.
- 블록을 출력한 뒤 멈추고 다음 턴의 사용자 답변 전에는 점수를 계산하거나 진행하지 않는다.

## 모든 호스트의 답변 처리

- 선택한 `label`과 자유 입력을 읽는다. 사용자 지정 텍스트가 있으면 미리 만든 선택지보다 우선한다.
- 이유나 제약이 있는 자유 입력 답변은 `SKILL.md` 공통 절차 4단계의 답변 확인에 따라 다시 말하고 점수 전에 확인한다.
- 사용자가 답을 건너뛰거나 결정을 맡기면 같은 단계의 위임 규칙에 따라 `auto-answer-uncertain.md`를 사용한다.
- 선택지 레이블만으로 빠진 내용을 추론하지 않고 후속 질문 하나로 정확한 내용을 받는다.

## 빠른 선택 체크리스트

1. Codex가 Plan 모드 밖에 있으면 전환을 요청하고 턴을 끝낸다. 아니면 Claude `AskUserQuestion`,
   OpenCode `question`, Codex `request_user_input` 또는 MCP elicitation을 사용한다.
2. 질문 하나, 12자 이내 `header`, 호스트 범위 안의 선택지와 각 `label`, `description`을 사용한다.
   실제 다중 선택이 아니면 단일 선택이다.
3. 질문, 제목과 선택지를 사용자 언어로 번역한다.
4. 추천 순으로 정렬하고 가장 좋은 하나의 레이블에만 ` (추천)`을 붙인다.
5. 고등학생이 이해할 만큼 질문과 설명을 자세히 쓴다.
6. 네이티브 도구가 없거나 권한이 거부되면 먼저 호스트별 모드와 설정 조건을 적용한다.
   구조화 UI를 제공할 수 없을 때만 인라인 형식을 사용한다.
7. 서브에이전트에서 인터뷰 질문을 하지 않는다. 결과를 모은 뒤 메인 세션에서 질문한다.
