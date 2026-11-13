# 엔드투엔드 골든 평가

> 영어 원본: [README.md](../../../../evals/e2e/README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 하네스는 플러그인을 하나의 코딩 에이전트 하네스로 보고 전체를 측정한다. 실행마다 플러그인 리비전 하나를
불러온 `claude -p`를 시작하고, 버려도 되는 가상 저장소에서 현실적인 개발 작업을 맡긴 뒤 결과를 채점한다.
두 변형이 같은 작업을 같은 조건에서 실행하므로 결과를 비교할 수 있다. 실행은 에이전트 호스트로 Claude Code나
Codex를 쓸 수 있고(`--hosts`), 플러그인 변경은 두 호스트 모두에서 판정한다.

이 하네스는 실제 에이전트 세션을 실행하고 실제 모델 사용량을 쓴다. 저장소 README의 개발 검사에는 들어가지
않으며, 개발 검사에 들어가는 것은 이 하네스의 단위 테스트뿐이다.

## 실행 한 번에 하는 일

1. 하네스는 변형의 플러그인 리비전을 `git archive <ref>`로
   `<run root>/plugins/<sha>/hei5enbug-agent-setup/`에 내보낸다. 내보낼 때 `evals/`, 그 한국어 미러
   `docs/ko/evals/`, `tests/test_e2e_eval_*.py`는 빼므로, 플러그인 소스를 읽는 에이전트도 숨은 테스트, 기준 해답,
   기대 답변을 볼 수 없다.
2. 작업의 픽스처를 `fixtures/`에서 `<run root>/<campaign>/work/<run id>/repo/`로 복사하고, 고정된 가상 작성자와
   날짜로 커밋한 뒤, 작업에 설정 스크립트가 있으면 실행한다. 설정 스크립트는 저장소 옆의
   `<run root>/<campaign>/work/<run id>/`에 상태를 더 만들 수 있고, 작업의 `env` 맵은 에이전트 환경 값을 준다. 그 값에서
   `{repo}`, `{work}`, `{PATH}`는 각각 저장소, 그 폴더, 현재 `PATH`를 뜻한다. 변형의 `env`와 설정의 `extra_env`가 여전히
   이 값보다 우선한다.
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
`--permission-prompt-tool`로 넘겨 사용자를 대신한다. 이 서버는 Bash 요청을 모두 허용한다. 파일 도구 요청
(`Write`, `Edit`, `MultiEdit`, `NotebookEdit`, 또는 `file_path`나 `notebook_path`가 있는 모든 요청)은 `..`와
심볼릭 링크를 풀어 본 경로가 실행의 작업 폴더 `work/<run id>/` 밖이면 거부한다. 거부 메시지에는 경로와 폴더 이름이
들어간다. 상대 경로는 에이전트의 작업 위치인 `work/<run id>/repo/`를 기준으로 푼다. 그 밖의 요청은 허용한다. 서버는 허용한 요청과 거부한 요청을 모두 결정과 함께 `approvals.jsonl`에 기록한다.
줄 수가 승인 질문 수이고 마찰 지표로 쓰므로, 거부한 요청도 센다. `EVAL_RUN_FOLDER`가 없는 `mcp.json`은 예전처럼
모든 요청을 허용한다. 플러그인 훅이 `ask`를 돌려주면 이 도구에 도달한다. 파일럿에서 강제 `git clean -f`로 이를
확인했다. 권한 모드나 플러그인 가드가 질문 없이 허용한 호출은 이 도구에 오지 않으므로 세지 않는다.

하네스는 에이전트가 `AskUserQuestion`으로 묻는 질문에 답할 수 없다. 승인 도구는 호출을 통과시키고, 실행은 질문에
답을 받지 못한 채 끝난다. 그래서 작업 프롬프트는 결과를 바꿀 결정을 열어 두지 않는다.

### Codex 호스트

`--hosts claude,codex`는 같은 내보낸 리비전, 같은 픽스처 사본, 같은 프롬프트, 같은 제한, 같은 채점기와 지표로 작업을
두 호스트에서 각각 실행한다. 기본값은 `claude`만이다. Codex 실행은 `gpt-6.1-sol`을 `high`로 `codex exec`에 시작하며
설정은 다음과 같다.

- 실행마다 `<run>/codex-home/`에 자기만의 `CODEX_HOME`을 두므로 사용자 자신의 Codex에 설치된 플러그인이나 설정이
  들어오지 않는다. `auth.json`은 사용자 자격 증명 파일로 가는 심볼릭 링크이고, 하네스는 그 파일을 읽거나 복사하거나
  출력하지 않는다. `HARNESS_CODEX_AUTH_HOME`은 그 파일이 있는 다른 폴더를 가리킨다.
- 플러그인은 내보낸 리비전에서만 불러온다. `codex plugin marketplace add <export>`가 내보낸 폴더를 로컬 마켓플레이스로
  등록하고, `codex plugin add hei5enbug-agent-setup@<marketplace>`가 그 `CODEX_HOME`에 설치한다. 설정 명령과 결과는
  `codex-setup.json`에 있다.
- 하네스가 리비전을 직접 내보내고 검증하므로 `--dangerously-bypass-hook-trust`를 준다. 실행이 플러그인 훅의 신뢰를
  묻느라 멈추지 않는다. Codex 훅은 그대로 실행된다.
- 표준 입력은 `/dev/null`이고 `ZDOTDIR`은 빈 폴더다. 그래서 Codex가 시작하는 셸은 사용자의 zsh 시작 파일을 읽지 않고
  실행이 정한 `PATH`를 유지한다. 하네스는 여기서도 `ORCA_*` 변수를 지운다.
- 대신 답하는 승인 도구가 없다. Claude Code는 권한 질문 도구에 묻지만, Codex는 `workspace-write` 샌드박스 안에서
  `approval_policy`를 `never`로 두고 실행하므로 샌드박스 밖 요청은 답을 기다리지 않고 실패한다. 플러그인 자체의 가드
  훅은 그대로 실행된다.
- Codex에는 지출 한도 플래그가 없으므로 작업의 경과 시간 제한만 적용한다.
- 세션의 모델과 effort는 명령줄이 아니라 rollout의 `turn_context` 이벤트에서 읽고, `env.json`에 Codex CLI 버전과 함께
  기록한다.

Codex 실행의 결과는 `results/<task>/<variant>/codex/rep<k>/` 아래에 있고, 실행 id는 `<task>-<variant>-codex-r<k>`다.
요약은 이를 `<variant> [codex]`로 묶는다.

### 모델 상한

측정에서는 어떤 역할도 `claude-opus-5-5`나 `gpt-6.1-sol`보다 강한 모델을 시작하면 안 된다. 허용 모델은
`harness/config.py`의 `MODEL_CAP`이고, `harness/records.py`도 같은 집합으로 기록을 검증한다. `run`은 캠페인이 시작되기
전에, `--dry-run`에서도, 캠페인을 거부하고 메시지에 역할과 모델을 적는다. 변형이 정한 메인 모델, 변형이 정한 플러그인 모델
옵션, 변형이 `review_model`처럼 상한 밖의 기본값을 그대로 둔 플러그인 모델 옵션, 루브릭 채점기가 대상이다.
`review_model`을 기본값으로 두는 변형은 `env`에서 `CLAUDE_PLUGIN_OPTION_REVIEW_MODEL`과 `HEI5ENBUG_REVIEW_MODEL`을
상한 안의 모델로 정한다. 실행 뒤에는 Claude 스트림, Claude 대화 기록, role runner 상태 줄, Codex rollout을 훑는다.
실행 안에서 답한 상한 밖 모델이 있으면 `success`를 false로 두고 `cap_violation`으로 기록한다.

플러그인의 고정 경로, 예를 들어 레지스트리의 설계와 대체 경로는 상한 위 모델을 이름으로 적고, 위 검사는 이를 보지
못한다. 그래서 내보낸 모든 플러그인 개정은, 변형과 상관없이 똑같이, 상한 변환을 거친다. 내보낸 사본에서만
모든 `claude-fable-*` ID(`claude-fable-5-2` 등)는 `claude-opus-5-5`로, 모든 `gpt-*-astra`와 `gpt-*-terra` ID(`gpt-6-astra`,
`gpt-6.1-terra` 등)는 `gpt-6.1-sol`로 바뀐다. 대상은
`config/model-registry.json`, `agents/`, `.codex/`, `skills/`, `instructions/`의 텍스트 파일이다(git의 개정은 그대로
둔다). 하네스는 그 파일을 다시 훑어 상한 밖 모델이 남아 있으면 캠페인을 거부하고, 메시지에 파일과 상한을 적는다.
변환은 `harness/plugin_export.py`의 `apply_cap_transform`이다. 실행마다 `env.json`에 `cap_transform`(대체 규칙, 바뀐
모델 ID, 그 개수)이 남고, `plugin-export.json`에는 변환된 내보내기의 다이제스트와 함께 들어가며, 그 다이제스트는 캠페인
입력 지문의 일부라서 변환이 다른 내보내기로 이어서 실행하면 멈춘다. 변환 없이 이전 하네스가 내보낸 개정은 다시 내보낸다.

## 명령

모든 명령은 저장소 루트에서 실행한다. 기본 run root는 `~/.local/state/hei5enbug-agent-setup/harness-eval/runs`이고,
`--run-root`로 바꿀 수 있다.

| 목적 | 명령 |
|---|---|
| 계획과 정확한 명령 보기 | `python3 evals/e2e/harness/cli.py run --campaign <name> --dry-run` |
| 캠페인 실행 또는 재개 | `python3 evals/e2e/harness/cli.py run --campaign <name> --variants baseline --reps 3` |
| 일부 작업만 실행 | `--tasks T01,T03` 추가 |
| 두 호스트에서 실행 | `--hosts claude,codex` 추가 |
| 끝난 실행 다시 실행 | `--only-rerun T03-baseline-r1,T03-baseline-r2` 추가 |
| 채점기 수정 후 다시 채점 | `python3 evals/e2e/harness/cli.py regrade --campaign <name> [--run-ids ...]` |
| 기록을 다시 복사한 뒤 채점 | `regrade`에 `--recollect` 추가 |
| 작업이나 변형을 바꾼 뒤 재개 | `run`에 `--allow-changed-inputs` 추가 |
| 실행마다 파일럿 사실 확인 | `python3 evals/e2e/harness/cli.py pilot-check --campaign <name>` |
| 표 출력 | `python3 evals/e2e/harness/cli.py summarize --campaign <name> [--out file.md]` |
| 두 변형 비교 | `python3 evals/e2e/harness/cli.py summarize --campaign <name> --compare baseline,<other>` |
| 리비전 내보내기만 하기 | `python3 evals/e2e/harness/cli.py export-plugin --ref <ref>` |
| 변경을 판정하고 기록 쓰기 | `python3 evals/e2e/harness/cli.py record --campaign <name> --issue <n> --before <variant> --after <variant> [--claim wall_seconds,cost_usd] [--tasks T08]` |

`--parallel`은 동시에 실행할 수를 정한다(기본 3). 변형이 여럿이면 작업과 반복마다 순서를 번갈아(ABAB, 다음은
BABA) 시간대 영향이 고르게 퍼지게 한다.

같은 `run` 명령을 다시 실행하면 캠페인을 이어서 한다. 끝난 실행은 건너뛴다. 인프라 문제로 실패했거나 사용량
한도에 걸린 실행은 다시 시작하고, 이전 기록과 작업 폴더는 `attempts/rep<k>/<n>/`으로 옮긴다. 어떤 실행이 사용량
한도를 보고하면 하네스는 새 실행을 시작하지 않고, 진행 중인 실행이 끝나기를 기다린 뒤 종료 코드 75로 끝난다.

첫 `run`은 변형마다 해석한 리비전과 입력별 지문을 `campaign.json`에 저장한다. 입력은 변형 파일, 작업 파일, 작업의
프롬프트 파일, 작업의 픽스처 트리, 작업의 숨은 테스트와 사용자 정의 검사, 글쓰기 작업을 채점하는 `scripts/text_review.py`다. 입력이 달라진 상태로 재개하면 멈춘다.
`--allow-changed-inputs`를 주면 멈추지 않고 그 변경을 `campaign.json`에 기록한다.

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
  results/<task>/<variant>/rep<k>/         Codex 실행은 results/<task>/<variant>/codex/rep<k>/
    run.json  prompt.txt  command.json  settings.json  mcp.json  env.json
    stream.jsonl  stderr.txt  approvals.jsonl
    transcripts/main.jsonl  transcripts/subagents/  transcripts/runner/  codex/  assignments/
    view.json  grade/grade.json  grade/rubric.json  metrics.json
```

`env.json`에는 Claude Code와 Codex CLI 버전, 설치된 플러그인 목록, Claude와 Codex 설정 파일의 SHA-256 해시(내용은
남기지 않음), 지운 변수의 이름, 내보내기의 상한 변환, 하네스 리비전을 기록한다. Codex 실행은 rollout이 보여 주는 CLI 버전, 모델, effort를
더한다.

## 지표

`metrics.json`은 측정값과 추정값을 나눠 적는다.

| 지표 | 출처 |
|---|---|
| 성공, 정확도, 테스트 통과율, 회귀 | 채점기. 성공은 필수 검사를 모두 통과했고, 루브릭 작업이면 루브릭 평균이 합격선에 닿았다는 뜻이다. 정확도는 통과한 검사의 가중 비율이다. |
| 모델별, 출처별 토큰 | 메시지 ID로 중복을 없앤 메인 대화 기록과 서브에이전트 기록, rollout별 Codex `token_count` 이벤트. |
| `claude_total_cost_usd` | `claude -p` 결과 메시지의 값으로, 클라이언트 쪽 추정이다. |
| `claude_list_cost_usd` | `harness/pricing.py`의 공식 Claude 정가(2026-10-25 확인)로 계산한 토큰 비용. 메인 세션, 서브에이전트, 별도 Claude role runner 프로세스를 포함한다. |
| `claude_runner_list_cost_usd` | 별도 Claude role runner 프로세스만의 정가 비용. 스트림의 총비용에는 이 비용이 빠져 있다. |
| 요약의 Claude 지출 | `claude_total_cost_usd`에 `claude_runner_list_cost_usd`를 더한 값. 스트림에 총비용이 없으면 `claude_list_cost_usd`만 쓴다. 서브에이전트는 이미 총비용 안에 있고, 어떤 프로세스도 두 번 세지 않는다. |
| `codex_list_cost_usd_estimate` | OpenAI API 정가(2026-10-25 확인)로 계산한 Codex 토큰 비용. Codex는 토큰당 과금하지 않는 ChatGPT 요금제로 실행하므로 추정값이다. |
| 경과 시간, 턴, 도구별 호출, 유형별 서브에이전트 실행 | 하네스 시계와 스트림. Codex 도구 호출은 따로 센다. |
| 역할과 종료 코드별 role runner 호출 | `role_runner.py` Bash 호출과 그 상태 줄. |
| 재시도 | 실패한 Bash 명령의 재실행, 오류 뒤 같은 에이전트 유형의 재실행, 0이 아닌 종료 뒤 role runner 재실행. |
| 승인 질문, 권한 거부 | `approvals.jsonl`과 결과 메시지. |
| 시도 포함 지출, 성공당 비용 | 요약에만 있다. 작업의 모든 시도를 합친 지출과, 그 지출을 성공 수로 나눈 값. |
| `grade_error` | 채점이 예외를 냈을 때만 있다. `metrics.json`에는 사용량, 비용, 도구 호출 수가 그대로 남고 `run.json`에도 같은 오류를 적는다. 요약은 이런 실행을 성공과 정확도 통계에서 빼고 지출에는 더한다. 채점이 성공하면 `regrade`가 오류를 지운다. |
| 인계 손실 | 메인 세션이 알던 작업 제약 가운데 위임 프롬프트에 없던 것, 그리고 그 때문에 실패한 검사. |

## 채점기

`harness/graders.py`의 채점기는 최종 저장소를 기준 커밋과 비교해 검사한다. 검사 종류에는 기존 테스트(수정이 있어도
픽스처 원래 테스트 파일로 되돌려 실행), 숨은 테스트, 바뀐 경로 제한, 텍스트 검사, 커밋 검사, 라인 커버리지, 대화
기록 속 금지 명령과 노출된 값이 있다. 작업별 사용자 정의 검사는 `tasks/custom/`에 있다.

루브릭 채점은 스크립트로 판단할 수 없는 것만 맡는다. T01은 설계 품질, T10은 답변 품질이다. 지시에는 작업
프롬프트, 루브릭, 산출물이 들어가고 변형 이름, 리비전, 모델 이름은 들어가지 않는다. 이름으로 변형을 알 수 없는
`<campaign>/rubric/<opaque id>/` 폴더에서
`python3 scripts/role_runner.py reviewer --model gpt-6.1-sol --effort high --timeout 1500`로 실행한다. 러너가 3이나 4로 끝나면
`claude-opus-5-5`가 대신 채점하고, `rubric.json`에 대체 사실을 기록한다. 채점기가 1800초 뒤에도 실행 중이면 하네스가
그 프로세스와 그것이 시작한 모든 프로세스를 멈추고, 그 실행의 채점은 `grade_error`로 실패한다.

글쓰기 작업(T13~T20)은 완성한 글을 `scripts/text_review.py`로 채점한다. 이 스크립트는 내보낸 플러그인이 아니라
하네스가 있는 저장소의 것을 쓰고, 스크립트 기본값과 상관없이 `--reviews 1`로 검토자 하나에 기대어
채점한다. 필수 검사 `text-review-clean`은 종료 코드 0이면 통과한다. 1이면 채점기가 같은 글을 한 번 더 검토하고,
두 검토가 모두 발견사항을 돌려줄 때만 검사가 실패한다. detail과 `grade.json`에는 두 검토의 발견사항을 모두 남기고,
`record`가 이를 기록에 복사한다. 다른 종료 코드는 검토가 결론에 이르지 못했다는 뜻이므로 검사가 예외를 던지고, 그 실행은
`grade_error`를 기록하며 `regrade`로 다시 시도한다. 참고용 검사 `ran-text-review`는 에이전트가
`text_review.py review`를 실행했는지 기록한다. 공용 코드는 `tasks/custom/text_review_shared.py`에 있고, 단위 테스트는
`E2E_TEXT_REVIEW_STUB`이 가리키는 JSON 파일로 스크립트를 대신한다. 사용자 정의 검사는 예외에 `no_verdict = True`를
달아, 실패한 검사를 기록하는 대신 채점을 `grade_error`로 멈추게 할 수 있다. 에이전트의 `TMPDIR`은 실행의 작업 폴더 안에
있으므로 에이전트가 실행한 검토의 비용은 집계되고, 채점기가 직접 실행한 검토의 비용은 집계되지 않는다.

사용자 정의 검사는 `ctx.origin`, 즉 채점 사본의 원본으로 실행의 원래 폴더를 읽으므로, T21 같은 작업은 설정 스크립트가
저장소 옆에 만든 Git worktree와 가짜 Orca 상태를 검사할 수 있다.

`tests/test_e2e_eval_graders.py`는 작업마다 채점기를 증명한다. 수정하지 않은 픽스처는 실패하고
`tasks/reference/`의 기준 해답은 통과한다.

## 골든 작업

프롬프트는 실제 사용자처럼 한국어로 쓴다. 픽스처는 실제 저장소의 관례를 갖춘 가상 저장소다. README, 한국어 미러
규칙이 있는 `AGENTS.md`, 테스트, 한국어 미러가 있다. T21은 `ORCA_TERMINAL_HANDLE`을 설정하고 `tasks/setup/fake_orca.py`가
만든 가짜 `orca`를 `PATH`의 맨 앞에 두고 실행하며, 상태는 저장소 옆의 `orca-state/`에 두고, 테스트는
`tests/test_e2e_eval_orca_cleanup.py`에 있다.

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
| T13 | inventory-service | 풀 리퀘스트 설명 | 티켓 키와 diff에 보이는 목록을 금지하는 규칙 아래, 컬럼 네 개를 더한 브랜치의 설명 |
| T14 | inventory-service | 리뷰 답글 | 검사를 왜 lock 안에서 하는지 답하기 |
| T15 | ops-notes | 이슈 본문 | 가이드와, 가이드가 이미 링크하는 설정 절을 함께 링크한 이슈 메모 |
| T16 | ops-notes | 티켓 코멘트 | 완료 기준 셋 중 둘만 적은 코멘트 초안 마무리 |
| T17 | notes-cli | 커밋 메시지 | 설정 한 줄 변경 후 커밋 |
| T18 | ops-notes | 채팅 메시지 | 표를 다시 풀어 쓴 문단이 있는 배포 안내 |
| T19 | ops-notes | 공유 문서 | 1,500자 한도에 1,600자쯤 되는 위키 초안 |
| T20 | notes-cli | 최종 보고 | 테스트를 더한 작은 변경 후 보고 |
| T21 | notes-cli | 작업 종료 시 Orca 정리 | 티켓의 설정 한 줄 변경, 가짜 `orca`와 저장소 세 곳의 Git worktree를 심어 둔 상태 |

## 두 호스트에서 변경 비교

플러그인 변경은 그 변경 하나만 다른 이전 변형과 이후 변형으로, 그 변경의 이슈가 정한 사례에서, 두 호스트 모두에서
측정한다. 규칙의 정확한 단계는 `harness/verdict.py`에 있고, 요약은 다음과 같다.

- 필수 검사를 모두 통과하면 실행이 통과다. 시간은 그 실행의 `wall_seconds`에 보관한 이전 시도의 `wall_seconds`를 더한
  값이고, 비용은 보관한 이전 시도를 포함한 실행 전체의 정가 지출이다. 요약이 계산하는 Claude 지출에 Codex 추정값을 더한
  값이다. 어떤 기록에도 기간이 없는 이전 시도가 있으면 시간은 `not measured`다.
- 품질: 모든 이후 실행이 두 호스트에서 통과하고, 이전에 통과한 사례가 어느 호스트에서도 실패하지 않는다. 품질이
  실패하면 시간과 비용 격차와 상관없이 그 사례는 실패다.
- 격차: 한 사례와 한 측정값에서 큰 호스트 값을 작은 호스트 값으로 나눈 값이다. 먼저 변형과 호스트마다 사례를 1회
  실행한다. 이후 격차가 이전 격차 이하이면 통과한다. 격차가 커지면 판정은 `repeat`이고, 변형과 호스트마다 번갈아 4회를
  더 실행해 반복 번호로 짝을 짓는다. 그러면 이후 격차 다섯 개의 중앙값이 이전 격차 다섯 개 가운데 가장 큰 값 이하일 때
  통과한다. 측정값마다 자신의 첫 쌍으로 갈래를 정하므로, 한 측정값을 위한 반복이 첫 쌍에서 통과한 다른 측정값을 바꾸지
  않는다. 한 호스트나 한 변형에 실행이 없는 반복은 짝이 덜 찬 것이라 `not measured`다.
- 첫 이전 격차가 2를 넘으면 그 측정값은 그 사례의 통과 조건이 아니다. 사례는 `investigate` 줄을 출력하고, 그 격차를
  이미 다루는 열린 이슈가 없으면 이슈 하나가 그 격차를 조사한다.
- 이전 실행이 없는 사례나 호스트는 품질만 판정하고, 그 이후 실행이 이후 변경의 기준선이 된다.
- 시간이나 비용 값이 없으면 `not measured`이고 통과가 아니다. 이전 실행이 없는 사례나 첫 이전 격차가 2를 넘는 사례도
  마찬가지다.
- 개선 주장(`--claim`): 시간이나 비용을 낮추려고 채택하는 변경은 주장하는 측정값을 밝힌다. 사례와 호스트마다 번갈아
  5회 실행해서, 모든 이후 실행이 통과하고, 주장한 측정값마다 이후 중앙값이 이전 최저값보다 낮고, 주장하지 않은 측정값마다
  이후 중앙값이 이전 최고값을 넘지 않아야 한다. 먼저 한 쌍을 실행하고, 실패하면 두 번째 쌍을 실행하며, 두 번째도 실패하면
  주장을 기각한다. 기각된 주장은 그 사례와 전체 판정을 `reject`로 만들고, 아직 결정에 이르지 않은 주장은 둘을
  `continue to five`나 `second pair`로 두며 `pass`로 두지 않는다.

`record`는 캠페인에서 두 변형의 실행을 두 호스트 모두 읽어, 요청한 작업마다(`--tasks`가 없으면 캠페인이 실행한 작업마다)
사례 하나를 만든다. 끝나지 않았거나 지표나 채점이 없거나 채점 오류가 있는 실행은 `not measured`로 그 사례에 남고, 실행이
하나도 없는 작업도 남는다. 역할마다 모델과 effort는 실행 자신의 호스트 기록에서 읽는다. Claude 스트림과 명령줄, 메인과
모든 자식 세션의 Codex rollout(역할은 `session_meta`에서 읽고, 같은 역할의 두 번째 세션은 별개 호출로 남긴다), role runner
상태 줄, 루브릭 결과가 그것이다.
기록 어디에도 없는 effort는 `not measured`로 적는다. 그다음 사례를 판정하고 기록을 검증해 `records/<이슈 번호>.json`에
쓴다. 사례마다 한 줄, `investigate` 줄, 반복이 필요한 사례, 주장 판정을 출력한다. 기록에는 측정값과 모델, effort, 이슈
번호 같은 실행 사실, 가상 픽스처 이름만 들어간다. 검증은 절대 로컬 경로, 상한 밖 모델, 빠진 필드를 거부한다.
`tests/test_e2e_eval_record_cli.py`가 커밋된 모든 기록을 검증한다.

### 기록

| 이슈 | 사례 | 판정 |
|---|---|---|

## 알려진 한계

- Bash 요청은 항상 허용하므로, 캠페인은 에이전트가 어떤 셸 명령이든 실행해도 되는 컴퓨터에서 돌려야 한다. 승인
  서버가 거부하는 것은 실행의 작업 폴더 밖으로 해석되는 파일 도구 요청뿐이다.
- `harness/process.py`의 프로세스 트리 조회는 마지막 조회 뒤 에이전트가 끝나기 전에 시작된 분리된 자식을 놓칠 수
  있고, 그런 자식은 종료되지 않는다.
- 사용자의 권한 모드에서 질문 없이 통과한 호출은 승인으로 세지 않는다. 그래서 승인 수는 가드가 다룬 모든 호출이
  아니라 사용자가 실제로 보게 될 질문 수를 잰다.
- Codex 비용은 API 정가로 계산한 추정값이고, 긴 문맥 요금 구간은 요청마다 입력 크기로 고른다. 실행 폴더에서
  시작하지 않은 rollout의 Codex 토큰은 모으지 않는다.
- 위임 프롬프트에 제약의 키워드가 하나도 없으면 그 제약이 빠진 것으로 센다. 키워드 없이 바꿔 말한 경우도 빠진
  것으로 센다.
- 모든 실행이 사용자의 Claude와 Codex 계정을 함께 쓰므로 사용량 한도와 서비스 부하가 모든 변형에 영향을 준다.
- 캠페인을 멈추는 것은 에이전트 자신의 Claude 세션이 낸 사용량 한도뿐이다. 실행 안에서 생긴 Codex 할당량 실패는
  에이전트 결과의 일부이고, role runner 종료 코드로 나타난다.
- Codex 실행에는 지출 한도가 없다. `codex exec`에 예산 플래그가 없으므로, 폭주한 Codex 실행은 작업의 경과 시간
  제한에서만 끝난다.
- Claude 서브에이전트의 effort는 하네스가 복사하는 기록에 없으므로 기록에는 `not measured`로 나온다.
