# 설명 최적화

> 영어 원본: [description-optimization.md](description-optimization.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

frontmatter 설명은 대부분의 스킬 호스트에서 주요 호출 신호다. 스킬 동작이 안정된 뒤에만 최적화한다.
모든 경로는 스킬 루트 기준이며 `<skill-builder-path>`는 불러온 `SKILL.md`가 있는 디렉터리다.
[실행 방식](execution-methods.ko.md)의 평가 모델 정책을 사용한다.

## 호출 평가 집합

`should_trigger: true`, `false`가 균형을 이룬 실제 질의 약 20개를 만든다.

- 표현, 길이, 상세 수준과 가벼운 오타를 다양하게 한다.
- 드물지만 유효한 사용을 포함한다.
- 이 스킬이 이겨야 할 가까운 경쟁 작업을 포함한다.
- 같은 단어를 쓰지만 다른 절차가 필요한 어려운 비호출 사례를 포함한다.

너무 쉬운 호출 사례와 명백히 무관한 비호출 사례를 피한다. 배열은 JSON으로 저장한다.

```json
[
  {"query": "a realistic user request", "should_trigger": true},
  {"query": "a difficult near-miss", "should_trigger": false}
]
```

브라우저나 아티팩트 표시가 있으면 `assets/eval_review.html`로 검토한다. 유일한
`__EVAL_REVIEW_DATA__` 자리에 `skill_name`, `description`, `evals`를 가진 JSON 객체를 넣고 `<`는
script 종료를 막도록 `\u003c`로 쓴다. 정확한 명령은 파일의 header comment를 따른다.

## 이식 가능한 model runner

optimizer는 특정 vendor CLI를 가정하지 않는다. 전체 프롬프트를 stdin으로 읽고 응답만 stdout으로 쓰는
명령을 제공한다.

```bash
python <skill-builder-path>/scripts/run_loop.py \
  --eval-set <trigger-eval.json> \
  --skill-path <path-to-skill> \
  --runner-command '<your-model-command>' \
  --max-iterations 5 \
  --verbose
```

명령 인수에 `{model}`이 있으면 `--model <model-id>`도 전달한다. 반복해서 옵션을 쓰는 대신
`SKILL_BUILDER_RUNNER_COMMAND`를 설정할 수 있다. headless 환경에서는 `--no-open`을 사용한다.

모델 호출 전에 입력을 검사한다. eval 집합은 문자열 `query`와 boolean `should_trigger`를 가진 비어 있지 않은
목록이어야 하며 중복 질의에 충돌하는 기대를 둘 수 없다. 작업자 수, timeout, 질의당 실행 수와 반복 수는
양의 정수다. threshold는 0에서 1 사이의 유한값, holdout은 0 이상 1 미만의 유한값이다.
시작 설명은 비어 있지 않고 1,024자 이하다.

같은 질의는 항상 같은 split에 들어가고 결과는 질의가 아니라 case ID로 연결한다. true와 false 태그를 모두
포함한 응답은 결정이 아니라 runner 오류다. 빈 설명이나 1,024자를 넘는 새 설명은 한 번 재시도한 뒤 거부한다.

runner는 셸 없이 stdin·stdout 계약으로 실행한다. 호스트 adapter는 optimizer를 바꾸지 않고 CLI, 로컬 모델
서버 또는 API를 연결할 수 있다. 호출 평가는 스킬 이름, 설명, 질의만 사용하는 안정적인 시뮬레이션이며
호스트의 비공개 라우팅을 대신하는 proxy다. 가능하면 호스트 네이티브 호출 검사를 추가하고 호스트 간 비교에는
이식 가능한 benchmark를 유지한다.

모든 점수는 이식 가능한 라우팅 시뮬레이션이라고 표시한다. 특정 호스트에서 같은 동작을 주장하려면 네이티브
검사가 필요하다고 밝힌다. loop는 층화된 train·test split, 반복 판정과 holdout 점수 선택으로 과적합을 줄인다.
출력의 `best_description`을 적용하고 이전·이후 점수를 보고한다.

반복되고 격리된 시험에는 runner, 작은 평가에는 직접 프롬프트를 사용할 수 있다. 두 방식 모두 holdout 질의를
개선 모델에 숨긴다. 같은 컨텍스트가 이미 봤다면 오염을 밝히고 새 사례로 교체한다. 직접 실행은 인라인 평가로
표시하고 없는 기능이나 지표를 알린다. 실행 방식 비교 없이 더 빠르거나 저렴하다고 주장하지 않는다.
