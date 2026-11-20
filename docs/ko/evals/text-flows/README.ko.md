# 글쓰기 흐름 비교

> 영어 원본: [README.md](../../../../evals/text-flows/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 평가는 사람이 읽는 글 세 종류, 즉 PR 설명(`T13`), 이슈 본문(`T15`), 최종 보고(`T20`)를 누가 쓰고, 검토하고, 고치는지
비교한다. 각 흐름은 `evals/e2e` 골든 하네스로 돌리는 플러그인 변형이고, 흐름과 글 종류마다 한 번씩 실행한다. `tf_pages.py`는
끝난 실행만 읽으며 모델 호출 비용이 없다.

| 흐름 | 쓰는 쪽 | 검토하는 쪽 | 고치는 쪽 | 호스트 |
|---|---|---|---|---|
| F1, 현재 흐름 | Claude | `text_review.py`를 통한 sol 승자의 Codex 모델 | Claude | Claude Code |
| F2 | Claude | `language` 역량으로 Codex 모델이 초안을 직접 고친 뒤의 Claude Opus | Claude | Claude Code |
| F3 | sol 승자의 Codex 모델 | `text_review.py`를 통한 Claude Opus | Codex 모델 | Codex |
| F4 | Claude | `text_review.py`를 통한 Claude Sonnet | Claude | Claude Code |
| F5 | Claude | 검토하면서 지적을 그 자리에 반영하는 Codex 모델 | Codex 모델 | Claude Code |

흐름은 F1과 `instructions/shared-text.md`의 글 수정 하나, 또는 `scripts/text_review.py`의 검토 모델 리터럴 하나만 다르므로,
하네스는 이를 변경 하나의 변형으로 기록한다.

## 판단

1. 형식 검사: 작업의 필수 검사 중 `text-review-clean`과 `ran-text-review`를 뺀 모두. 형식 검사에 실패한 글은 그 글 종류를 통과하지
   못한다.
2. 품질: 소유자가 글 종류마다 블라인드로 순위를 매긴다. `tf_pages.py`는 종류마다 페이지 하나를 중립 라벨로 쓰고, 순서는 종류별
   시드로 고정한다. 페이지 옆 `key.json`이 라벨별 흐름을 적으며 페이지에는 흐름 이름이 없다. 어떤 종류에서든 소유자가 F1보다 낮게
   매긴 흐름은 선택하지 않는다.
3. 형식 검사를 통과하고 F1보다 낮게 매겨지지 않은 흐름 중 통과한 글당 정가 비용이 가장 낮은 흐름이 이기고, 10퍼센트 또는
   $0.05 안이면 더 빠른 흐름이 이긴다(`docs/dev-rules/evaluation.md`).

```text
python3 evals/text-flows/tf_pages.py --run-root <root> --campaign <name> \
  --flows F1=f1:claude,F2=f2:claude,F3=f3:codex,F4=f4:claude,F5=f5:claude --out <folder>
```
