# 역할 실행기 scratch 폴더 평가

> 영어 원본: [README.md](../../../../evals/role-runner-scratch/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 평가는 `scripts/role_runner.py`의 scratch 폴더와 `--validation` 변경에서 모델을 실제로 돌리는 실행을 위한 시드 저장소와
결정적 검사를 담는다. 모델 호출 비용이 드는 단계는 실행을 시작하는 것뿐이다. 시드, 스냅샷, 검사는 비용이 들지 않으며
`tests/test_role_runner_demo.py`가 이를 시험한다.

## 사례

각 사례는 한 번의 실행이고, 아래 고정 조건이 통과 또는 실패 기준이다.

| 사례 | 실행 | 통과 조건 |
|---|---|---|
| Codex의 검증 | 설치된 환경이 없는 시드 저장소에서 `pricing.py`를 검토하도록 맡긴 `role_runner.py reviewer --model gpt-6.1-sol --validation` | 도구 기록에 테스트 명령과 시드한 단언 실패가 있고, 검토가 `test_bulk_discount`를 지목하며, 저장소 스냅샷이 그대로다 |
| Claude의 검증 | 환경을 설치한 채(`seed --with-env`) 같은 실행 | 막힘: 소유자가 Claude 셸의 쓰기를 가두는 방법을 정하기 전에는 실행기가 Claude 모델의 `--validation`을 거부한다 |
| Codex의 heredoc scout | `--validation` 없이 `role_runner.py scout`에 `data/orders.csv`의 `quantity * unit_cents` 합계를 heredoc Python 명령으로 계산하도록 맡긴다 | 도구 기록에 임시 파일 때문에 실패하지 않은 heredoc Python 명령이 있고, 결과가 기대 합계를 담으며, 테스트나 설치 명령이 없고, 저장소 스냅샷이 그대로다 |

## 절차

```text
python3 evals/role-runner-scratch/demo.py seed /tmp/work/demo-a
python3 evals/role-runner-scratch/demo.py snapshot /tmp/work/demo-a /tmp/work/before.txt
# /tmp/work/demo-a에서 역할 실행기를 실행한 뒤:
python3 evals/role-runner-scratch/demo.py check <validation|scout> /tmp/work/demo-a \
  --records <rollout 또는 transcript> --result <결과 파일> --before /tmp/work/before.txt
```

`check`는 `pass`와 실패 목록을 담은 JSON 한 줄을 출력하고, 실패가 남으면 1로 끝난다. 시드한 결함은 할인이 11개부터
시작하는 것으로, docstring과 `test_bulk_discount`는 10개부터라고 말한다.
