# 엔드투엔드 골든 평가

> 영어 원본: [README.md](../../../../evals/e2e/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 하네스는 플러그인을 하나의 코딩 에이전트 하네스로 보고 전체를 측정한다. 실행마다 플러그인 리비전 하나를
불러온 `claude -p`를 시작하고, 버려도 되는 가상 저장소에서 현실적인 개발 작업을 맡긴 뒤 결과를 채점한다.
두 변형이 같은 작업을 같은 조건에서 실행하므로 결과를 비교할 수 있다.

이 하네스는 실제 에이전트 세션을 실행하고 실제 모델 사용량을 쓴다. 저장소 README의 개발 검사에는 들어가지
않으며, 개발 검사에 들어가는 것은 이 하네스의 단위 테스트뿐이다.

## 실행 한 번에 하는 일

1. 하네스는 변형의 플러그인 리비전을 `git archive <ref>`로
   `<run root>/plugins/<sha>/hei5enbug-agent-setup/`에 내보낸다. 내보낼 때 `evals/`, 그 한국어 미러
   `docs/ko/evals/`, `tests/test_e2e_eval_*.py`는 빼므로, 플러그인 소스를 읽는 에이전트도 숨은 테스트, 기준 해답,
   기대 답변을 볼 수 없다.
2. 작업의 픽스처를 `fixtures/`에서 `<run root>/<campaign>/work/<run id>/repo/`로 복사하고, 고정된 가상 작성자와
   날짜로 커밋한 뒤, 작업에 설정 스크립트가 있으면 실행한다.
3. 그 폴더에서 에이전트를 시작한다.

   ```text
   claude -p --model claude-opus-5-5 --effort high --output-format stream-json --verbose
     --include-hook-events --plugin-dir <exported plugin> --settings <run>/settings.json
     --mcp-config <run>/mcp.json --permission-prompt-tool mcp__eval_approver__approve
     --max-budget-usd <task limit> -- <prompt>
   ```

   프롬프트는 `--` 뒤에 오므로 `--version ...`처럼 대시로 시작하는 프롬프트도 옵션으로 읽히지 않는다.

   `settings.json`은 설치된 `hei5enbug-agent-setup@hei5enbug` 플러그인을 끈다. 기본 권한 모드, 다른 플러그인,
   MCP 서버, Codex를 포함해 사용자 환경의 나머지는 그대로 둔다. 하네스는 `ORCA_*` 변수만 지운다. 그래서 실행이
   자신을 시작한 Orca 터미널에 상태를 알리거나 메시지를 보낼 수 없다. 우회 모드, `--bare`,
   `--permission-mode`는 절대 넘기지 않는다.
4. 작업마다 정한 실제 경과 시간 제한에 걸리면 에이전트에 SIGINT, SIGTERM, SIGKILL을 차례로 보낸다. 신호는
   에이전트의 프로세스 그룹과, role runner 자식처럼 에이전트가 별도 세션으로 시작한 모든 프로세스에 가고, 하네스는
   남은 프로세스가 없는지 확인한다.
5. 실행이 끝나면 하네스는 메인 대화 기록, 서브에이전트 기록, role runner 지시 파일, role runner 실행의 Claude 대화
   기록, 그리고 실행 중에 실행 폴더에서 시작된 Codex rollout을 복사한다.
6. 결정적 채점기가 최종 저장소를 검사한다. 숨은 테스트는 이때 저장소 사본에만 복사한다. rollout의 Codex 명령도
   대화 기록 보기에 합쳐지므로 채점기가 함께 본다. 두 작업은 블라인드 루브릭 채점도 받는다.
7. 하네스는 원본 기록 옆에 `view.json`, `grade/grade.json`, `metrics.json`을 쓴다.

### 승인

실제 사용에서는 사용자가 권한 질문에 답한다. 하네스는 작은 stdio MCP 서버인 `harness/approval_mcp.py`를
`--permission-prompt-tool`로 넘겨 사용자를 대신한다. 이 서버는 모든 요청을 승인하고 `approvals.jsonl`에 기록한다.
줄 수가 승인 질문 수이고, 마찰 지표로 쓴다. 플러그인 훅이 `ask`를 돌려주면 이 도구에 도달한다. 파일럿에서
강제 `git clean -f`로 이를 확인했다. 권한 모드나 플러그인 가드가 질문 없이 허용한 호출은 이 도구에 오지 않으므로
세지 않는다.

하네스는 에이전트가 `AskUserQuestion`으로 묻는 질문에 답할 수 없다. 승인 도구는 호출을 통과시키고, 실행은 질문에
답을 받지 못한 채 끝난다. 그래서 작업 프롬프트는 결과를 바꿀 결정을 열어 두지 않는다.

## 명령

모든 명령은 저장소 루트에서 실행한다. 기본 run root는 `~/.local/state/hei5enbug-agent-setup/harness-eval/runs`이고,
`--run-root`로 바꿀 수 있다.

| 목적 | 명령 |
|---|---|
| 계획과 정확한 명령 보기 | `python3 evals/e2e/harness/cli.py run --campaign <name> --dry-run` |
| 캠페인 실행 또는 재개 | `python3 evals/e2e/harness/cli.py run --campaign <name> --variants baseline --reps 3` |
| 일부 작업만 실행 | `--tasks T01,T03` 추가 |
| 끝난 실행 다시 실행 | `--only-rerun T03-baseline-r1,T03-baseline-r2` 추가 |
| 채점기 수정 후 다시 채점 | `python3 evals/e2e/harness/cli.py regrade --campaign <name> [--run-ids ...]` |
| 기록을 다시 복사한 뒤 채점 | `regrade`에 `--recollect` 추가 |
| 작업이나 변형을 바꾼 뒤 재개 | `run`에 `--allow-changed-inputs` 추가 |
| 실행마다 파일럿 사실 확인 | `python3 evals/e2e/harness/cli.py pilot-check --campaign <name>` |
| 표 출력 | `python3 evals/e2e/harness/cli.py summarize --campaign <name> [--out file.md]` |
| 두 변형 비교 | `python3 evals/e2e/harness/cli.py summarize --campaign <name> --compare baseline,<other>` |
| 리비전 내보내기만 하기 | `python3 evals/e2e/harness/cli.py export-plugin --ref <ref>` |

`--parallel`은 동시에 실행할 수를 정한다(기본 3). 변형이 여럿이면 작업과 반복마다 순서를 번갈아(ABAB, 다음은
BABA) 시간대 영향이 고르게 퍼지게 한다.

같은 `run` 명령을 다시 실행하면 캠페인을 이어서 한다. 끝난 실행은 건너뛴다. 인프라 문제로 실패했거나 사용량
한도에 걸린 실행은 다시 시작하고, 이전 기록과 작업 폴더는 `attempts/rep<k>/<n>/`으로 옮긴다. 어떤 실행이 사용량
한도를 보고하면 하네스는 새 실행을 시작하지 않고, 진행 중인 실행이 끝나기를 기다린 뒤 종료 코드 75로 끝난다.

첫 `run`은 변형마다 해석한 리비전과, 변형과 작업 입력의 지문을 `campaign.json`에 저장한다. 입력이 달라진 상태로
재개하면 멈춘다. `--allow-changed-inputs`를 주면 멈추지 않고 그 변경을 `campaign.json`에 기록한다.

### 변형

변형은 `variants/` 안의 JSON 파일이다: `{"name", "ref", "settings", "env", "extra_args"}`. `ref`는 시험할 플러그인
리비전이다. `settings`는 실행의 `--settings` 파일에, `env`는 에이전트 환경에, `extra_args`는 명령줄에 합쳐진다.
우회 플래그, `--bare`, `--permission-mode`, 또는 하네스가 직접 정하는 플래그를 넣은 변형은 거부한다. `settings`에
무엇이 있어도 설치된 플러그인은 꺼진 채로 둔다.

## 실행 기록

```text
<run root>/<campaign>/
  campaign.json  state.json
  work/<run id>/repo/                      에이전트 작업 폴더, 실행 뒤에도 남김
  rubric/<opaque id>/                      이름으로 변형을 알 수 없는 루브릭 채점 폴더
  results/<task>/<variant>/rep<k>/
    run.json  prompt.txt  command.json  settings.json  mcp.json  env.json
    stream.jsonl  stderr.txt  approvals.jsonl
    transcripts/main.jsonl  transcripts/subagents/  transcripts/runner/  codex/  assignments/
    view.json  grade/grade.json  grade/rubric.json  metrics.json
```

`env.json`에는 Claude Code와 Codex CLI 버전, 설치된 플러그인 목록, Claude와 Codex 설정 파일의 SHA-256 해시(내용은
남기지 않음), 지운 변수의 이름, 하네스 리비전을 기록한다.

## 지표

`metrics.json`은 측정값과 추정값을 나눠 적는다.

| 지표 | 출처 |
|---|---|
| 성공, 정확도, 테스트 통과율, 회귀 | 채점기. 성공은 필수 검사를 모두 통과했고, 루브릭 작업이면 루브릭 평균이 합격선에 닿았다는 뜻이다. 정확도는 통과한 검사의 가중 비율이다. |
| 모델별, 출처별 토큰 | 메시지 ID로 중복을 없앤 메인 대화 기록과 서브에이전트 기록, rollout별 Codex `token_count` 이벤트. |
| `claude_total_cost_usd` | `claude -p` 결과 메시지의 값으로, 클라이언트 쪽 추정이다. |
| `claude_list_cost_usd` | `harness/pricing.py`의 공식 Claude 정가(2026-10-25 확인)로 계산한 토큰 비용. |
| `codex_list_cost_usd_estimate` | OpenAI API 정가(2026-10-25 확인)로 계산한 Codex 토큰 비용. Codex는 토큰당 과금하지 않는 ChatGPT 요금제로 실행하므로 추정값이다. |
| 경과 시간, 턴, 도구별 호출, 유형별 서브에이전트 실행 | 하네스 시계와 스트림. Codex 도구 호출은 따로 센다. |
| 역할과 종료 코드별 role runner 호출 | `role_runner.py` Bash 호출과 그 상태 줄. |
| 재시도 | 실패한 Bash 명령의 재실행, 오류 뒤 같은 에이전트 유형의 재실행, 0이 아닌 종료 뒤 role runner 재실행. |
| 승인 질문, 권한 거부 | `approvals.jsonl`과 결과 메시지. |
| 시도 포함 지출, 성공당 비용 | 요약에만 있다. 작업의 모든 시도를 합친 지출과, 그 지출을 성공 수로 나눈 값. |
| 인계 손실 | 메인 세션이 알던 작업 제약 가운데 위임 프롬프트에 없던 것, 그리고 그 때문에 실패한 검사. |

## 채점기

`harness/graders.py`의 채점기는 최종 저장소를 기준 커밋과 비교해 검사한다. 검사 종류에는 기존 테스트(수정이 있어도
픽스처 원래 테스트 파일로 되돌려 실행), 숨은 테스트, 바뀐 경로 제한, 텍스트 검사, 커밋 검사, 라인 커버리지, 대화
기록 속 금지 명령과 노출된 값이 있다. 작업별 사용자 정의 검사는 `tasks/custom/`에 있다.

루브릭 채점은 스크립트로 판단할 수 없는 것만 맡는다. T01은 설계 품질, T10은 답변 품질이다. 지시에는 작업
프롬프트, 루브릭, 산출물이 들어가고 변형 이름, 리비전, 모델 이름은 들어가지 않는다. 이름으로 변형을 알 수 없는
`<campaign>/rubric/<opaque id>/` 폴더에서 `python3 scripts/role_runner.py reviewer --model gpt-6-astra --effort xhigh`로
실행한다. 러너가 3이나 4로 끝나면
`claude-opus-5-5`가 대신 채점하고, `rubric.json`에 대체 사실을 기록한다.

`tests/test_e2e_eval_graders.py`는 작업마다 채점기를 증명한다. 수정하지 않은 픽스처는 실패하고
`tasks/reference/`의 기준 해답은 통과한다.

## 골든 작업

프롬프트는 실제 사용자처럼 한국어로 쓴다. 픽스처는 실제 저장소의 관례를 갖춘 가상 저장소다. README, 한국어 미러
규칙이 있는 `AGENTS.md`, 테스트, 한국어 미러가 있다.

| 작업 | 픽스처 | 확인하는 경로 | 요청 |
|---|---|---|---|
| T01 | inventory-service | 설계 스킬 | 재고 예약 설계 문서 |
| T02 | inventory-service | 워커 위임 | 여러 파일에 걸친 배송비 정책과 테스트 |
| T03 | inventory-service | 조사 후 수정 | 실패 테스트 없이 사용자 제보로 받은 버그 수정 |
| T04 | notes-cli | 여러 파일 편집 | 코드, 문서, 한국어 미러의 memo를 note로 이름 바꾸기 |
| T05 | inventory-service | 병렬 실행 | 한 요청 안의 독립 변경 두 개 |
| T06 | inventory-service | 테스트 작성 | 테스트 없는 모듈을 라인 커버리지 90퍼센트까지 |
| T07 | ledger-lite | 실패 복구 | 처음에는 환경 문제로 테스트가 실패 |
| T08 | notes-cli | 쉬운 작업 경로 | 설정 한 줄 변경 |
| T09 | webapp-cleanup | 안전 | 커밋하지 않은 작업과 가짜 비밀이 있는 상태에서 정리 |
| T10 | inventory-service | 읽기 전용 조사 | 주문 취소가 재고를 복구하는 방식 설명 |
| T11 | notes-cli | 커밋 스킬 | 작은 변경 후 메시지 규칙을 지킨 커밋 |
| T12 | inventory-service | 최종 리뷰 | 변경 후 보고 전에 독립 리뷰 |

## 알려진 한계

- 사용자의 권한 모드에서 질문 없이 통과한 호출은 승인으로 세지 않는다. 그래서 승인 수는 가드가 다룬 모든 호출이
  아니라 사용자가 실제로 보게 될 질문 수를 잰다.
- Codex 비용은 API 정가로 계산한 추정값이고, 긴 문맥 요금 구간은 요청마다 입력 크기로 고른다. 실행 폴더에서
  시작하지 않은 rollout의 Codex 토큰은 모으지 않는다.
- 위임 프롬프트에 제약의 키워드가 하나도 없으면 그 제약이 빠진 것으로 센다. 키워드 없이 바꿔 말한 경우도 빠진
  것으로 센다.
- 모든 실행이 사용자의 Claude와 Codex 계정을 함께 쓰므로 사용량 한도와 서비스 부하가 모든 변형에 영향을 준다.
- 캠페인을 멈추는 것은 에이전트 자신의 Claude 세션이 낸 사용량 한도뿐이다. 실행 안에서 생긴 Codex 할당량 실패는
  에이전트 결과의 일부이고, role runner 종료 코드로 나타난다.
