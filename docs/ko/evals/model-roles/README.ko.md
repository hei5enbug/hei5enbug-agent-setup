# Claude 검토자와 토론 상대 비교

> 영어 원본: [README.md](../../../../evals/model-roles/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 평가는 세 역할이 고정하는 Claude 모델과 사고 강도를 정한다. 세 역할은 tiki-taka의 Claude 상대, 독립 모델 검증 규칙에서 GPT가
작성한 작업을 검토하는 더 강한 Claude 검토자, `docs/dev-rules/delegation.md` 최종 검토 표에서 복잡한 GPT 작성 변경의 행이다. 후보 네 개가 시드한 사례
다섯 개를 한 번씩 실행한다. 후보는 `claude-opus-5-5`와 `claude-fable-5-2`이며 각각 `high`와 `xhigh`로 돌린다. 모델 호출 비용이 드는
단계는 후보 실행을 시작하는 것뿐이다. 시드, 채점, 증거 읽기, 기록, 핀 검사는 비용이 들지 않으며 `tests/test_model_roles_cases.py`와
`tests/test_model_roles_record.py`가 이를 시험한다.

사례는 T89부터 T93까지의 ID를 쓴다. `evals/e2e`의 골든 하네스는 이 사례를 실행하지 않는다. 후보마다 그 역할이 쓰는 실행기로
실행하므로, 모델과 사고 강도는 그 실행기 자신의 호스트 기록에서 나온다.

## 사례

각 사례는 하네스가 `cases/<id>/`에서 고정된 커밋으로 만드는 저장소 하나이고, 실제 문제의 고정 목록이 `cases/<id>/case.json`에 있다.
목록에는 심은 문제, 그 문제가 다른 곳에 일으키는 직접적인 결과, 시드한 파일에서 검토자가 확인할 수 있는 그 밖의 실제 결함이 들어 있다.
후보는 저장소와 프롬프트만 보고 `case.json`은 보지 못한다.

| 사례 | 역할 | 시드한 자료 | 심은 문제 |
|---|---|---|---|
| T89 | reviewer | 스레드에 안전한 클래스에 `SeatMap.hold_many`를 더하는 GPT 스타일 변경 | `hold_many`가 잠금을 잡기 전에 점유 좌석과 수용 인원을 검사한다 |
| T90 | reviewer | 문서화된 응답 필드 `total_cents`의 이름을 바꾸는 GPT 스타일 변경 | 소비자 `reports/export.py`와 `docs/API.md`는 여전히 그 필드를 쓴다 |
| T91 | reviewer | 이슈 본문 | Proposal 2는 항목이 15분 뒤에만 만료되게 하는데, 수용 기준 2는 30초를 요구한다 |
| T92 | opponent | 웹훅 재시도 설계와 그것을 승인하는 호스트의 첫 발언 | 재시도마다 새 `X-Delivery-Id`를 받아 구독자가 반복된 이벤트를 알아볼 수 없다 |
| T93 | opponent | 주문 테이블을 고객별로 샤딩하는 설계와 그것을 승인하는 호스트의 첫 발언 | 한 고객이 쓰기의 41퍼센트를 만들어 한 샤드가 기본 DB가 버티는 초당 400건을 넘는다 |

후보는 두 조건을 모두 만족하면 사례를 통과한다.

- 지적이 심은 문제를 짚는다. 지적 하나가 심은 문제의 위치를 인용하고, 그 텍스트가 사례의 키워드 목록으로 문제와 그 효과를 말한다.
  실행기가 사용자의 언어를 따르므로 답이 영어일 수도 한국어일 수도 있어서, 키워드 목록은 영어와 한국어를 함께 담는다.
- 사례의 실제 문제 목록 밖에 있는 지적이 없다. 목록에 오른 심지 않은 실제 문제를 같은 위치와 키워드 규칙으로 짚은 지적은 목록 안에
  있다. 목록에 없는 줄의 의견 같은 다른 지적은 사례를 실패시키고, 실패한 사례는 그 지적을 `outside`에 남겨 조율 세션이 읽게 한다.

검토 답이나 토론 발언은 `location`(`path:line` 또는 `path:first-last`), `problem`, `effect`를 가진 지적의 `json` 코드 블록 하나로 끝난다.
채점기는 마지막 블록을 읽는다. 블록이 없거나 깨졌으면 `error`와 함께 사례가 실패한다. 검토 프롬프트에는 독립 모델 검증 규칙의 검토 항목이,
토론 프롬프트에는 tiki-taka 스킬의 고정 계약이 한 번의 교환에 맞게 줄어 들어 있다.

## 절차

모든 명령은 저장소 루트에서 실행하고, `WORK`는 저장소 밖의 빈 폴더다. 실행 폴더는 `T89-opus-high`처럼 사례와 후보로 이름 붙인다.
후보마다 모든 사례를 한 번씩 실행하므로 모두 20번이다.

검토 사례 T89부터 T91은 후보 네 개 각각에 대해, 시드한 저장소 폴더에서 실행한다.

```text
python3 evals/model-roles/mr_cli.py seed T89 --out $WORK/T89-opus-high
# $WORK/T89-opus-high/repo에서:
python3 <저장소 루트>/scripts/role_runner.py reviewer --model claude-opus-5-5 --effort high \
  --assignment $WORK/T89-opus-high/prompt.md --result $WORK/T89-opus-high/answer.md > $WORK/T89-opus-high/status.json
python3 evals/model-roles/mr_cli.py result T89 --candidate claude-opus-5-5/high \
  --answer $WORK/T89-opus-high/answer.md --status-line $WORK/T89-opus-high/status.json \
  --out $WORK/T89-opus-high.json
```

상대 사례 T92와 T93. 실행기는 플러그인 루트의 `config/model-registry.json`에서 상대 모델을 읽으므로, Claude 모델마다 그 모델을 담은
실행기 사본으로 실행하고 `--fast`가 `high`를 고른다.

```text
python3 evals/model-roles/mr_cli.py opponent-plugin --model claude-opus-5-5 --out $WORK/plugin-opus
python3 evals/model-roles/mr_cli.py opponent-plugin --model claude-fable-5-2 --out $WORK/plugin-fable
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --show-config --fast
python3 evals/model-roles/mr_cli.py seed T92 --out $WORK/T92-opus-high
STATE=$(mktemp -d /tmp/tiki-taka-state.XXXXXX)
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --state-dir $STATE \
  --repo $WORK/T92-opus-high/repo --max-exchanges 1 --fast \
  < $WORK/T92-opus-high/prompt.md > $WORK/T92-opus-high/answer.md
python3 evals/model-roles/mr_cli.py result T92 --candidate claude-opus-5-5/high \
  --answer $WORK/T92-opus-high/answer.md --state-dir $STATE --out $WORK/T92-opus-high.json
bash $WORK/plugin-opus/skills/tiki-taka/run-opponent.sh --opponent claude --state-dir $STATE --finish
```

`--finish`는 `result`가 읽는 상태를 지우므로 `result`를 먼저 실행한다. `xhigh` 후보는 `--fast`를 빼고, Fable 후보는
`$WORK/plugin-fable`을 쓴다. 첫 유료 호출 전에 `--show-config`가 후보의 모델과 사고 강도를 출력해야 한다.

`result`는 실행 기록이 후보와 다른 모델이나 사고 강도를 보이거나, 역할 실행기 상태 줄이 검증된 Claude 실행(exit 0)이 아니거나,
대화 기록이 없으면 종료 코드 2로 실패하고 파일을 쓰지 않는다. 원인을 고쳐 그 후보와 사례를 다시 실행한다. 답을 얻기 전에 실패한 실행도
한 번의 시도로 센다. 이전 시도마다 `mr_cli.py evidence --status-line <파일>` 또는 `--state-dir <폴더>`로 얻은 값을 `--attempts <n>`,
`--earlier-cost <usd>`, `--earlier-wall <초>`로 넘겨, 기록이 모든 시도의 비용과 시간을 세게 한다. `grade <사례> --answer <파일>`은 답의
채점을 출력하고 사례가 실패하면 1로 끝난다.

`mr_cli.py build --results <결과 파일 20개>`는 후보마다 사례당 결과가 하나씩 있을 때만 `record.json`을 쓴다.

## 기록

`record.json`은 `status`(만들기 전에는 `pending`, 만든 뒤에는 `recorded`), 후보 네 개, 사례와 역할의 대응, 후보와 사례마다 결과 하나를 담는다.

| 필드 | 의미 |
|---|---|
| `passed` | 마지막 시도의 채점 |
| `host_model`, `host_effort` | 실행의 Claude 대화 기록에 있는 모든 답의 모델과 사고 강도이며 후보와 같아야 한다 |
| `cost_usd` | 모든 시도의 목록 가격 비용이며 대화 기록의 토큰과 `evals/e2e/harness/pricing.py`로 계산한다 |
| `wall_seconds` | 대화 기록의 첫 기록부터 마지막 기록까지에 이전 시도를 더한 값 |
| `attempts` | 사례에 들인 실행 횟수 |

`roles`는 `reviewer`(T89부터 T91)와 `opponent`(T92와 T93) 각각에 대해, 후보별 통과 수와 자기 사례의 총비용과 총 시간, 그리고 역할의 결정을 담는다.
검증은 결과에서 `roles`를 다시 계산해 다른 값, 빠지거나 겹친 결과, 후보와 다른 호스트 모델이나 사고 강도, 음수 비용을 거부한다.

## 결정

`docs/dev-rules/evaluation.md`의 소유자 효율 규칙이 역할마다, 그 역할의 사례만 놓고 결정한다(reviewer는 T89부터 T91, opponent는 T92와 T93).

1. 자격이 있는 후보는 역할의 모든 사례를 통과한 후보다. 하나도 없으면 그 역할은 승자가 없고(`none`) 기준 핀을 유지한다.
2. 어느 사례에서든 그 사례에서 자격 있는 후보 중 가장 빠른 후보보다 1.5배를 넘고 60초를 넘게 느린 후보는 탈락한다. 1.5배를 넘어도
   60초 미만인 차이, 정확히 60초인 차이, 정확히 1.5배인 차이는 탈락시키지 않는다. 이 규칙이 자격 있는 후보를 모두 탈락시키면 그 역할은
   승자가 없다.
3. 남은 후보 중 통과한 사례당 목록 가격 비용이 가장 낮은 후보가 이긴다. 가장 낮은 비용과의 차이가 10퍼센트 이내이거나 0.05달러 이내이면
   동률이고, 역할의 사례에 걸린 시간의 합이 가장 짧은 후보가 동률을 이긴다. 시간도 같으면 그 역할은 `tie`다.

`none`과 `tie`는 소유자가 정할 때까지 기준 핀을 유지한다. Opus가 역할을 이기면 그 역할은 Opus를 적고, Fable은 사용자가 요청할 때만 쓸 수 있다.

`python3 evals/model-roles/mr_cli.py check`는 기록을 검증하고 저장소를 기록과 비교하며, `tests/test_model_roles_record.py`도 같은 비교를 한다.

- 기록이 대기 중이거나 역할이 `tie`나 `none`이면 모든 핀 위치가 기준을 유지한다. 기준은 `config/model-registry.json`과 tiki-taka 스킬에서 Claude 상대가
  `claude-fable-5-2`와 `xhigh`이고, 독립 모델 검증 규칙, 위임 문서, `docs/dev-rules/delegation.md` 최종 검토 표, 그 한국어 미러에서 Claude 검토자 행이
  `claude-opus-5-5`와 `claude-fable-5-2`를 적는 것이다. 기록이 생기기 전에는 핀이 바뀌지 않는다.
- 역할에 승자가 있으면 그 역할의 각 위치가 승자의 모델만 적고 비교의 다른 Claude 모델은 적지 않으며, 레지스트리가 승자의 모델과 사고 강도를
  담고, 검토 표 행이 승자의 사고 강도만 적는다. 모든 위치가 맞을 때까지 테스트가 실패하고, 줄을 더 찾지 못하는 앵커는 고칠 파일을 알려 준다.

결정을 적용할 때는 교체한 핀 문구를 단언하는 테스트도 함께 고치고, 상대 승자의 사고 강도가 `high`이면 Codex 상대가 `xhigh`를 유지하도록
상대 레지스트리 항목에 자기 사고 강도를 준다.

## 결과

2026-11-16. 1차(20회 실행)는 영어로만 된 키워드와 불완전한 실제 문제 목록 때문에 심어 둔 문제를 지목한 답까지 실패로
처리되어 폐기했다. 이는 커밋 8193708에서 고쳤고, 2차는 20회를 새로 실행했다.

| 역할 | 후보 | 통과 | 비용(USD) | 소요(초) |
|---|---|---|---|---|
| 검토자(사례 3개) | `claude-opus-5-5` `high` | 2 | 0.55 | 91 |
| 검토자 | `claude-opus-5-5` `xhigh` | 2 | 0.74 | 165 |
| 검토자 | `claude-fable-5-2` `high` | 3 | 1.43 | 140 |
| 검토자 | `claude-fable-5-2` `xhigh` | 3 | 1.93 | 233 |
| 토론 상대(사례 2개) | `claude-opus-5-5` `high` | 1 | 0.55 | 113 |
| 토론 상대 | `claude-opus-5-5` `xhigh` | 0 | 0.79 | 220 |
| 토론 상대 | `claude-fable-5-2` `high` | 1 | 1.27 | 162 |
| 토론 상대 | `claude-fable-5-2` `xhigh` | 0 | 3.14 | 451 |

검토자 승자는 `high`의 `claude-fable-5-2`다. 세 사례를 모두 통과한 후보는 Fable 두 개뿐이고 `high`가 `xhigh`보다
싸다. 토론 상대 역할은 두 사례를 모두 통과한 후보가 없어 승자가 없고, 기준선인 `xhigh`의 `claude-fable-5-2`를 유지한다.

측정의 한계: 2차에서도 키워드 매처는 목록의 문제를 다른 말로 다시 서술한 발견 약 8개(T92와 T93)를 목록 밖으로 센다.
Opus가 목록에 없는 의견 발견 때문에 T91에서 실패했으므로 이 중 어느 것도 검토자 결정을 바꾸지 않고, 토론 상대
결정은 어느 쪽이든 `none`이다.

## GPT 역할 비교 (2026-11-20)

`gpt-roles-record.json`은 각 역할이 고정하는 GPT 모델을 정하는 두 번째 비교를 기록한다. `gpt-6.1-sol`에 있던 역할은
`gpt-6.1-sol`, `gpt-6.2-sol`, `gpt-6.1-terra`, `gpt-6-luna`를 비교했고, scout, researcher, worker는 `gpt-6-luna`와
`gpt-5.6-luna`를 비교했다. 결과 필드는 `record.json`과 같고 `role`이 더해지며, 역할, 사례, 후보마다 결과 하나를 둔다(반복이
여럿이면 모두 통과해야 통과이고 비용과 시간은 평균이다). 효율 규칙도 같다. `mr_cli.py`는 이 파일을 검증하지 않으며, 위의
Fable 대 Opus 기록과는 별개다.

| 역할 | 사례 | 결정 |
|---|---|---|
| reviewer | T89~T91, S5 | `gpt-6.1-terra`: 4개 중 4개 통과, 0.061 USD, 68초. `gpt-6.2-sol`은 4개 중 4개, 0.265 USD이며 `gpt-6.1-sol`은 S5에서 실패한다 |
| opponent | T92, T93 | `gpt-6.1-sol` 유지: 두 사례를 모두 통과한 유일한 후보다 |
| worker | W1~W3 | `gpt-6-luna`: 모든 후보가 통과하고 비용은 0.020 USD로 `gpt-6.1-terra`의 0.101 USD보다 낮다 |
| scout, researcher | S7, SC1~SC3, R1 | `gpt-6-luna`: 4개 중 4개와 1개 중 1개 통과로, `gpt-5.6-luna`의 4개 중 2개와 1개 중 1개보다 낫고 비용도 낮다 |
| language | t1, t3, t5 | `gpt-6.1-terra`가 효율 규칙을 이기지만, 소유자가 초안을 블라인드로 비교하기 전에는 적용하지 않는다 |
| text_review | TR1, TR2 | 네 후보 모두 TR1에서 실패한다. TR1에는 실제 결함이 하나 더 있다(열 목록 문장은 diff가 보여 주는 이름의 목록이다). TR2만으로는 `gpt-6.1-terra`가 이기지만 적용하지 않는다 |

`gpt-6.2-sol`은 `gpt-6.1-sol`을 모든 곳에서 대체하지 못한다. `gpt-6.1-sol`이 통과하는 상대 사례 T92, T93과 language 사례
t1, t5에서 실패하고, 모든 sol 역할 사례의 비용(1.009 USD 대 1.031 USD)은 동률 범위 안이다.

## 모델 호출 없는 검사

```text
python3 -m pytest -q tests/test_model_roles_cases.py tests/test_model_roles_record.py
python3 evals/model-roles/mr_cli.py check
```
