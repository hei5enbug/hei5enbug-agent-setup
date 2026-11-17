# Claude 검토자·상대역 평가

> 영어 원본: [README.md](../../../../evals/claude-reviewer-opponent/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 평가는 `claude-fable-5-2`가 `claude-opus-5-5`보다 더 잘 검토하고 더 잘 토론하는지 측정한다. tiki-taka 상대역과
GPT가 작성한 결과물의 검토자가 쓰는 Claude 모델과 사고 강도가 버전을 올린 결과가 아니라 기록된 비교에 근거하게
하려는 것이다. 이슈 #84에 답한다. 실제 모델 세션을 실행하고 실제 사용량을 쓰므로 저장소 README의 개발 검사에는
들어가지 않으며, 개발 검사에 들어가는 것은 단위 테스트 `tests/test_reviewer_opponent_eval.py`뿐이다.

## 질문

역할마다, `claude-opus-5-5`와 `claude-fable-5-2`를 각각 `high`와 `xhigh`로 둔 후보 네 개 가운데 그 역할의 고정
사례를 가장 많이 통과하는 것은 무엇인가? 통과 수가 같은 후보 가운데서는 그 역할 사례의 목록 가격 비용이 가장 낮은
후보가 이긴다. 검토자 역할은 검토 사례 세 개와 그 비용만, 상대역 역할은 토론 사례 두 개와 그 비용만 센다.

## 사례

`cases.json`은 사례 다섯 개를 고정한다. 각 사례는 가상의 자료로 만든 실제 문제의 고정 목록을 가진다.

| 사례 | 역할 | 산출물 | 심은 문제 |
|---|---|---|---|
| `r1` | 검토 | GPT가 쓴 diff | `JobStore.claim_next`가 다른 모든 메서드가 잡는 잠금 없이 공유 상태를 읽고 바꾼다 |
| `r2` | 검토 | GPT가 쓴 diff | `export_report`가 `docs/api.txt`와 CLI 사용처가 요구하는 `str` 대신 `bytes`를 돌려준다 |
| `r3` | 검토 | 이슈 본문 | 제안은 재시도를 고정 대기로 3회까지 제한하는데 인수 기준 2는 횟수 제한 없는 재시도와 두 배씩 늘어나는 대기를 요구한다 |
| `d1` | 토론 | 설계 제안 | 라운드 로빈 로드 밸런서 뒤에서 복제본 3개가 도는데 멱등 키가 프로세스별 집합에 있다 |
| `d2` | 토론 | 설계 제안 | 한도를 시작할 때 한 번만 읽는데 요구 사항 R2는 변경이 60초 안에 적용되기를 요구한다 |

`cases/` 아래 각 사례 폴더에는 후보가 보는 자료가 있다. 후보가 읽을 수 있는 `workspace/`와, 검토 사례의
`change.diff` 또는 `issue.txt`다. `accepted_related`는 후보에게 불리하게 세지 않는 사실에 맞는 관련 관찰이고,
`real_problems`와 `accepted_related` 밖의 지적은 후보에게 불리하게 센다. 사례나 목록은 새 고정 집합으로만 바꾸고,
모든 후보를 다시 실행한다.

## 실행기

`cr_run.py`에는 명령이 세 개 있다. 저장소 루트에서 실행한다. 후보는 모두 Claude 모델이므로 Claude Code CLI가
필요하고 Codex CLI는 필요 없다.

```text
python3 evals/claude-reviewer-opponent/cr_run.py run     --out <folder> [--candidates opus-high,fable-xhigh] [--cases r1,d1] [--parallel 4]
python3 evals/claude-reviewer-opponent/cr_run.py summary --out <folder>
python3 evals/claude-reviewer-opponent/cr_run.py decide  --out <folder>
```

후보 식별자는 `opus-high`, `opus-xhigh`, `fable-high`, `fable-xhigh`다. 기존 출력 폴더는 이어서 실행한다. 끝난 실행은
다시 실행하지 않는다.

| 설정 | 값 |
|---|---|
| 검토 호출 | 사례 작업 공간 사본에서 `scripts/role_runner.py reviewer --model <id> --effort <effort>`를 실행하고, 사례의 의도, 근거, 완성된 초안, 실행 시점에 읽은 `instructions/independent-model-validation.md`의 "Review checks"를 준다 |
| 토론 호출 | 레지스트리에 후보를 적은 스킬 사본의 바뀌지 않은 `skills/tiki-taka/run-opponent.sh --opponent claude --max-exchanges 1`을 실행하고, 스킬의 교환 1 프롬프트와 문제를 찾지 못했다는 호스트 발언을 준다 |
| 검증 | 실행기가 Claude Code 기록에서 모델과 사고 강도를 확인한다. 모델이나 강도가 다른 실행은 검증되지 않은 것이며 아무것도 결정하지 않는다 |
| 비용 | 세션 기록에서 `evals/e2e/harness/usage.py`의 가격표로 구한 목록 가격이다 |
| 한도 | 호출당 900초이며, 각 후보는 사례를 순서대로 실행하고 후보끼리는 병렬로 실행한다 |
| 예산 | 실행 20회, 후보 4개가 사례 5개를 한 번씩 실행한다. 재시도도 센다. 검증되지 않은 실행을 조용히 바꾸지 않는다 |

출력 폴더에는 후보와 사례마다 검토의 `assignment.txt`, `answer.txt`, `runner.log`, 검증된 모델·사고 강도·초·비용이 든
`status.json`이 있다.

## 채점

각 `answer.txt`를 사례의 고정 목록과 대조해 읽고, `<folder>/grades.json`을
`{"<후보 식별자>": {"<사례 식별자>": true 또는 false}}` 형식으로 쓴다.

- 검토 사례는 어떤 지적이 심은 문제를 위치와 영향과 함께 짚고, 어떤 지적도 `real_problems`와 `accepted_related`
  밖에 있지 않으면 통과한다.
- 토론 사례는 후보의 첫 발언이 심은 결함을 짚고, `real_problems`와 `accepted_related` 밖의 반론을 제기하지 않으면
  통과한다.

## 결정 규칙

`decide`는 역할별로 후보를 통과 수로, 같으면 그 역할 사례의 가장 낮은 비용으로 순위를 매겨 첫 후보를 그 역할의
승자로 정한다. 그 역할의 실행이 하나라도 없거나, 검증되지 않았거나, 모델이나 강도가 다르거나, 비용이 없거나, 채점되지
않았으면 승자가 없다. 인프라 실패는 통과도 실패도 아니기 때문이다. Opus가 한 역할에서 이기면 그 역할은 Opus를
이름으로 쓰고, Fable은 사용자가 요청할 때만 쓸 수 있다.

## 결과

아직 실행하지 않았다.
