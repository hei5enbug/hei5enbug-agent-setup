# 위임과 최종 검토

> 영어 원본: [delegation.md](../../../dev-rules/delegation.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 저장소 개발 규칙은 `AGENTS.md`를 보완한다. 아래 역할에 대해서는 플러그인의 모델 및 추론 강도 경로를 덮어쓰고,
기계적인 문서 작업을 `writer`에 배정하며, 최종 검토자는 최종 검토 표가 고른다. 플러그인의 나머지 작업 소유권, 권한,
검증 규칙은 계속 적용한다.

## 역할

저장소 구현에는 Claude Code 플러그인 작업자 서브에이전트를 기본으로 사용한다. 나머지 경로는 `.codex/agents/`의 Codex
프로젝트 역할을 사용한다.

| 역할 | 기본 이름 | 모델 / 추론 강도 | fallback 이름 | 모델 / 추론 강도 |
|---|---|---|---|---|
| 범위가 정해진 구현 및 디버깅(쉬운 작업) | `haiku_worker` | `claude-haiku-5-5` / `xhigh` | `worker` | `gpt-6.1-sol` / `high` |
| 범위가 정해진 로컬 읽기 전용 근거 조사 | `scout` | `gpt-5.6-luna` / `xhigh` | `haiku_scout` | `claude-haiku-5-5` / `xhigh` |
| 승인된 내용을 반영하는 기계적인 문서 편집 | `writer` | `gpt-6.1-sol` / `high` | `haiku_writer` | `claude-haiku-5-5` / `xhigh` |
| 아래 최종 검토 표가 `gpt-6.1-sol` `high`를 고를 때 한 번 읽기 전용으로 최종 검토 | `code_reviewer` | `gpt-6.1-sol` / `high` | `opus_code_reviewer` | `claude-opus-5-5` / `high` |

- `haiku_worker`와 `sonnet_worker`는 플러그인의 `hei5enbug-agent-setup:worker`와
  `hei5enbug-agent-setup:sonnet-worker` 서브에이전트를 가리킨다. 나머지 `haiku_*` 이름과 `opus_code_reviewer`는 별도
  Claude Code CLI 프로세스에 붙이는 과제 이름이며, 등록된 `--agent` 이름이 아니다. `worker`, `scout`, `writer`,
  `code_reviewer`는 Codex 프로젝트 역할이며 새 Codex 세션부터 적용된다.
- 쉬운 작업은 범위가 정해진 로컬 읽기 전용 근거 조사에 `scout`을, 코디네이터가 승인한 기계적인 Markdown 및 미러 편집에
  `writer`를 사용한다. Claude Code에서는 `writer`를 역할 정의를 `--instructions`로 넘긴 `role_runner.py language`로
  실행한다.
- 문제 정의, 복잡한 근본 원인 분석, 계획, 설계와 RFC, 승인 결정은 메인 세션에서 처리한다. `designer`, `reviewer` 역할은
  기존 호스트 경로를 그대로 사용한다.
- 호스트가 지원하면 표에 나온 모델과 추론 강도를 명시적으로 요청하고, 기본 역할이든 fallback 역할이든 결과를 사용하기
  전에 실제 호스트 실행 기록을 확인한다. 플러그인 에이전트의 정의를 덮어쓰거나 Anthropic 모델을 Codex 역할에 넣지 않는다.

## 구현 작업자

메인 세션은 구현을 배정하기 전에 원인, 수정 가능한 경로, 변경 요구사항, 실행 가능한 완료 검사를 정하고, 난이도와
사용량에 따라 작업자를 고른다.

| 작업 | 작업자 |
|---|---|
| 쉬움: 편집 내용이 정해져 있고 검사가 모두 확인하는 응집된 변경 하나 | `haiku_worker`: 세션 줄 "Worker agent model"이 `claude-haiku-5-5`의 `xhigh`를 보일 때 `hei5enbug-agent-setup:worker` 서브에이전트, 그렇지 않으면 `sonnet_worker` |
| 보통 또는 어려움: 동작 변경, 여러 파일, 파싱, 보안, 동시성 | `sonnet_worker`: `hei5enbug-agent-setup:sonnet-worker` 서브에이전트(`claude-sonnet-5-5` / `high`) |
| Claude 사용 한도에 걸리거나 Claude worker를 사용할 수 없음 | `worker`(`gpt-6.1-sol` / `high`): Claude Code에서는 허용 경로가 든 폴더에서 `role_runner.py implementation --fallback --instructions <worker 역할 정의>`를 실행하고, Codex에서는 `worker` 역할을 쓴다 |

- `claude -p` 프로세스 대신 이 플러그인 서브에이전트를 띄운다.
- 작업자의 결과를 사용하기 전에 기존 준비 확인과 실제 호스트 기록 검사를 따른다. 작업자는 범위를 넓히는 대신 새 원인이나
  누락된 결정을 메인 세션에 보고한다.
- 선택한 구현 경로의 대안을 명시적으로 비교할 때는 완전히 해결한 과제 수를 먼저 보고, 완료율이 비슷하면 성공 건당 비용과
  추가로 얻는 코드 품질을 비교한다. 실패한 시도의 비용도 포함한다. 품질과 비용을 임의의 비율로 합치거나 보고서의 측정
  한계를 무시하지 않는다.

## fallback

- 각 역할에는 Claude에서 GPT로, GPT에서 Claude로 전환하는 다른 모델 계열의 fallback 하나만 둔다. 기본 실행 파일, 인증,
  할당량, 역할, 요청한 설정 또는 신뢰할 수 있는 설정 근거를 사용할 수 없을 때만 지정된 fallback을 사전 승인된 경로로
  사용한다.
- 전환 이유와 선택한 경로를 알린다. 기본 작업자가 이미 시작됐다면 먼저 중지하고 부분 결과를 확인한 뒤, 확인된 미완료
  작업만 같은 범위, 권한, 검사와 함께 넘긴다.
- 과제마다 표에 지정된 fallback 하나를 최대 한 번 시도하고, 그것도 사용할 수 없으면 메인 세션에서 진행한다. 기본 경로와
  같은 인증, 할당량 또는 기능 문제에 막힌 것이 확인된 fallback은 시도하지 않는다.
- fallback으로 사용자 결정 누락을 해결하거나 권한 제한이나 실패한 완료 검사를 우회하지 않는다.
- 기본 역할에 고정된 모델을 덮어써 fallback을 호출하지 말고, 지정된 경로를 해당 호스트에서 실행한다.
- 이 선택은 복구 정책이며 fallback의 품질이나 비용 우위를 측정해 입증한 주장이 아니다.

Claude fallback은 다음을 따른다.

- 대응하는 기본 Codex 역할의 `developer_instructions`와 범위가 정해진 과제를 stdin으로 전달해, 각 역할의 범위를 원본
  하나에서 유지한다.
- `claude -p`에 표의 전체 모델 ID와 추론 강도,
  `--output-format json --permission-mode dontAsk --strict-mcp-config`를 지정한다.
- `haiku_scout`과 `opus_code_reviewer`에는 `--tools Read Grep Glob --allowedTools Read Grep Glob`를 추가한다.
- `haiku_writer`에는 `--tools Read Grep Glob Edit Write --allowedTools Read Grep Glob`와 함께 배정된 각 Markdown 파일과
  미러에 대한 `Edit(//<absolute allowed path>)`를 추가한다. Edit 규칙은 Write에도 적용되고, `//`는 절대 경로를 뜻한다.
- 배정된 검사는 메인 세션이 실행한다. 이 fallback에는 셸, 네트워크, 위임 도구를 제공하지 않는다.
- JSON `modelUsage`가 요청한 모델을 나타내고 기존 실제 설정 검사에서 추론 강도를 확인했을 때만 결과를 사용한다.

CLI로 재개할 때는 언제나 모델과 추론 강도를 다시 적용하고, Claude fallback이면 도구 제한과 과제 범위도 다시 적용한다.

## 최종 검토

합쳐진 최종 diff에 대해 변경 크기와 작성 모델 계열에 맞춰 읽기 전용 최종 검토를 한 번 실행한다.

| 변경 | 최종 검토 |
|---|---|
| 사소함: 오타, 문구, 버전, 메타데이터 수정, 번역, 또는 검사가 모두 확인하는 기계적 수정 | 없음 |
| 사소하지 않음, Claude 작성 | `role_runner.py reviewer`에 `--model gpt-6.1-sol`이나 `gpt-6-astra`, `--effort high`나 `xhigh`를 붙이며, 플러그인의 독립 모델 검증 규칙에 따라 변경마다 범위와 위험에 맞게 고른다 |
| GPT 작성(`gpt-6.1-sol`로 작성한 작업 포함) | `role_runner.py reviewer --model claude-fable-5-2 --effort high` |

- 이 검토는 요청의 모든 작업이 끝나고 검사를 통과한 뒤 합쳐진 최종 diff를 대상으로 자동으로 한 번 실행한다. 더 이른
  검토에는 사용자의 승인이 필요하다.
- 검토자에게 최종 diff, 요구사항, 검사 근거를 전달한다.
- Claude가 작성한 변경에서 고른 검토자를 사용할 수 없으면 두 모델 중 다른 하나를 쓴다.
- 메인 세션이 지적 사항을 검증하고 완료 여부를 결정하며, 두 번째 검토는 시작하지 않는다.

## 근거

다음 기록은 위 경로를 설명할 뿐 규칙이 아니다.

- 이 라우팅은 이 저장소의 정책이며 벤치마크 결과나 일반적인 모델 우위 주장이 아니다. 사용자는 범위가 정해진 구현에
  Haiku `xhigh`를, 범위 한정 최종 검토에 Sol `high`를 역할 선호로 골랐다. 이는 Haiku가 Frontier v4의 완료율이나 비용
  효율에서 앞선다거나 구현 점수가 리뷰 정확도를 입증한다는 주장이 아니다.
- Frontier v4는 모델과 추론 강도별로 23개의 까다로운 동작 재현 과제를 한 번씩 수행한다. 쉬움/보통/어려움 등급을
  정의하지 않고, 문서 작업을 평가하지 않으며, 최종 검토의 정확도도 재지 않았다. 보고서마다 하네스 버전과 비용 기준이
  다르므로 비용은 구독 요금이 아닌 API/목록 가격 추정치다.
  [Haiku 비교](https://vulcanbench.com/benchmarks/swe-v4-haiku55-vs-frontier.html),
  [Luna 비교](https://vulcanbench.com/benchmarks/swe-v4-gpt55-luna-v35.html),
  [VulcanBench 방법론](https://vulcanbench.com/methodology.html)을 참조한다.
- `scout`의 `gpt-5.6-luna`/`xhigh` 고정값은 사용자가 명시적으로 선택한 값이며, 이전 로컬 비교가 그 품질을 입증하는
  것은 아니다.
- 2026-10-17, `writer`: 미러 편집 과제 세 개를 블라인드로 비교한 뒤 `writer`를 `gpt-6.1-sol`/`high`로 바꿨다. Sol은
  기대 항목 18개 중 17개를 통과하고 고칠 곳이 한 곳이며 토큰도 적었고, Luna는 9개를 통과하고 고칠 곳이 19곳이었다.
- 2026-10-17, 구현: 실제 승인 가드 과제 세 개(분류, 세션 상태, 모드)를 Sonnet `high`와 Sol `high`로 한 번씩 돌렸다.
  여섯 실행 모두 코디네이터의 검사를 통과했다. 블라인드 검토에서 고칠 곳은 Sol이 모두 5곳, Sonnet이 10곳이었고, Sol은
  Sonnet의 출력 토큰 30~54%를 쓰고 더 빨리 끝났다. 이어서 쉬운 작업 두 개를 Haiku, Sonnet, Sol `high`로 한 번씩
  돌렸다. 설정 편집은 어느 모델도 고칠 곳이 없었고 Haiku의 API 비용은 Sonnet의 약 9분의 1이었다($0.018 대 $0.159).
  파일·파싱 경계 처리가 있는 사용량 기록 읽기 스크립트는 고칠 곳이 Sol 1곳, Haiku 4곳, Sonnet 6곳이었다. 모델과
  과제마다 한 번씩만 돌린 근거는 얇고 Sol의 비용은 금액으로 재지 못했다. 플러그인의 `implementation_worker` `auto`
  경로가 같은 규칙을 런타임에 적용한다.
- 2026-10-20: 사용자는 구현은 Claude에, 조사와 최종 검토는 GPT에 유지하도록 보통·어려운 작업을 Sonnet으로 옮겼으며,
  Sol은 대체 경로가 되었다.
- 2026-10-22: auto 모드 분류기는 승인 가드를 고치는 `claude -p` 작업자를 자기 수정으로 막았고, `dontAsk`는 가드가 묻는
  명령에서 작업자를 멈췄다. 반면 `sonnet-worker` 서브에이전트는 같은 종류의 변경을 막힘 없이 했고, 서브에이전트 기록에
  `claude-sonnet-5-5`의 `high`가 남았다.
