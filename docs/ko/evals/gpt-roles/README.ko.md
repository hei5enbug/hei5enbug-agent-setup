# GPT 역할 모델 비교

> 영어 원본: [README.md](../../../../evals/gpt-roles/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 평가는 2026-11-20 소유자 규칙에 따라 레지스트리의 각 역할이 어떤 GPT 모델을 쓸지 정한다. `gpt-6.1-sol`을 쓰는 역할은
`gpt-6.1-sol`, `gpt-6.2-sol`, `gpt-6.1-terra`, `gpt-6-luna`를 비교하고, `gpt-5.6-luna`를 쓰는 역할은 `gpt-5.6-luna`와
`gpt-6-luna`를 비교한다. 모델 호출 비용이 드는 단계는 실행을 시작하는 것뿐이다. 결정, 채점, 비용 읽기는 비용이 들지 않으며
`tests/test_gpt_roles.py`가 이를 시험한다. 후보에 Astra 모델은 없다.

## 사례

각 사례는 역할의 레지스트리 노력 수준에서 후보 하나를 한 번 실행하고, 고정된 통과 또는 실패 규칙으로 채점한다. 역할의 결정은 그
역할의 사례만 읽는다.

| 역할 | 사례 | 출처 | 실행 경로 |
|---|---|---|---|
| `reviewer` | T89, T90, T91, S5 | `evals/model-roles` 사례와 scratch 사례 5 | `role_runner.py reviewer` |
| `text_review` | TR1, TR2 | 신규: 결함 하나를 심은 초안 | `text_review.py review --model` |
| `language` | t1, t3, t5 | `evals/korean-writing` 작업, Claude 채점기 하나 | `kw_run.py` |
| `worker` | W1, W2, W3, 더 어려운 W4, W5, W6 | 신규: 숨은 테스트가 있는 시드 저장소. W4부터 W6은 각각 docstring에만 적힌 요구, 바뀌는 소스 파일 수 상한, 얕은 수정을 떨어뜨리는 숨은 테스트를 가진다 | `role_runner.py worker` |
| `scout` | S7, SC1, SC2, SC3 | scratch 사례 7과 T103~T105의 scout-demo 질문 | `role_runner.py scout` |
| `researcher` | R1, 더 어려운 R2, R3 | 신규: 웹 검색 질문 하나. R2와 R3은 공식 문서의 정확한 사실 여러 개와 공식 주소가 필요하다 | `role_runner.py researcher` |

역할 실행기는 레지스트리에 적힌 모델만 시작하므로, 모든 실행은 `git archive`로 내보낸 플러그인 사본을 쓰고, 그 사본의
`runner.review_models`에는 모든 후보도 적혀 있다. 저장소의 레지스트리는 바꾸지 않는다.

## 실행

```text
python3 evals/gpt-roles/gr_cli.py plan
python3 evals/gpt-roles/gr_cli.py run T89 gpt-6.2-sol --out $WORK
python3 evals/gpt-roles/gr_cli.py language-results --out $WORK
python3 evals/gpt-roles/gr_cli.py decide --out $WORK
```

`run`은 결과를 썼으면 사례 통과 여부와 관계없이 0으로 끝나고, 채점할 수 없었으면 3으로 끝난다. 채점할 수 없는 경우는 검증된 상태
줄이 없거나, 롤아웃에 후보가 아닌 모델이 있거나, 정가가 없는 모델인 경우다. 비용은 실행 자체의 Codex 롤아웃에 있는 모든
요청의 정가(`harness/pricing.py`)이고, 경과 시간은 실행기 자체의 소요 시간이다. 반복이 여러 번인 사례는 모든 반복이 통과해야
통과로 세고 평균 비용과 시간으로 센다.

scratch 사례 7의 검사는 합계를 천 단위 구분 기호 없이 비교한다. `3,075`처럼 맞는 답이 원래 검사에서 실패했기 때문이다.

## 결정

`decide`는 `docs/dev-rules/evaluation.md`를 역할별로 적용한다. 모든 사례를 통과하고, 한 사례라도 가장 빠른 후보보다 1.5배
넘고 60초 넘게 느리면 탈락하며, 가장 싼 후보를 고르고, 10퍼센트 또는 $0.05 안이면 더 빠른 후보가 이긴다. 그 뒤 바꿀 레지스트리
행을 출력한다.

- `gpt-6.2-sol`은 모든 sol 역할에서 `gpt-6.1-sol`이 통과하는 모든 사례를 통과하고, 어느 사례에서도 탈락하지 않으며, 모든 sol 역할
  사례의 비용이 동률 밴드 밖으로 낮을 때만 모든 곳에서 `gpt-6.1-sol`을 대체한다. `gpt-6.1-terra`나 `gpt-6-luna`가 규칙으로 이긴 역할은
  그 모델 하나만 쓴다.
- `gpt-6-luna`는 `gpt-5.6-luna`가 통과하는 모든 사례를 통과하고, 탈락하지 않으며, 동률 밴드 밖으로 더 비싸지 않으면 그 역할에서
  `gpt-5.6-luna`를 대체한다. `runner.role_model`은 모든 luna 역할이 바뀔 때만 바뀐다.
- 새 language 승자는 그 초안과 현재 초안을 소유자가 블라인드로 비교하는 단계를 여전히 거친다.
