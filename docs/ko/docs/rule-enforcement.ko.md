# 규칙 집행

> 영어 원본: [rule-enforcement.md](../../rule-enforcement.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 표는 이 저장소에서 글로 쓴 규칙마다 그 규칙을 집행하는 검사를 짝지어 둔다. 표에 없는 규칙은 에이전트가 읽는 것에만
기댄다. 테스트 파일이 표에서 빠지면 `tests/test_rule_enforcement.py`가 실패한다.

반복된 실수가 검사 없이 글로만 쓴 규칙을 어기면 같은 변경에서 그 규칙을 한 단계 올린다. 구조로 가능성을 없애거나,
타입이나 스키마로 표현할 수 없게 만들거나, 오류 메시지가 올바른 대안을 알려 주는 테스트를 추가한다. 새 검사가 그
실수의 실제 과거 사례에서 실패한다는 것을 증명한다. 검사가 실수를 불가능하게 만들면 그 검사가 대신하는 글로 쓴
규칙을 지우고 해당 행을 갱신한다.

## 저장소 규칙

| 집행자 | 집행하는 규칙 | 규칙 위치 |
|---|---|---|
| `tests/test_public_boundary.py` | 추적 파일과 커밋 메시지에 로컬 경로, 실명, 비밀 값, 비공개 내용이 없고, 보호 섹션은 바뀌지 않은 채 마지막에 있다. | `AGENTS.md` (Public boundary) |
| `tests/test_release_version.py` | 기준 태그 이후 계획 버전은 하나이고, 모든 매니페스트에서 같으며, 기준보다 낮지 않고, 버전만 바꾸는 커밋이 없다. | `AGENTS.md` (릴리스 기준) |
| `tests/test_model_pins.py` | 런타임 파일은 고정한 전체 모델 ID로만 모델을 부르고, 고정값은 14일 안에 다시 확인한다. | `AGENTS.md` (모델 고정) |
| `tests/test_korean_mirrors.py` | 사람이 읽는 영어 Markdown 파일마다 실행 폴더 밖에 원본을 링크한 비권위 한국어 미러가 있다. | `AGENTS.md` (한국어 미러) |
| `tests/test_instruction_duplication.py` | 공유 규칙은 정본 파일 하나에만 있고, 호스트 파일과 저장소 파일은 core나 common 규칙을 복사하지 않는다. | `AGENTS.md` (단일 정본) |
| `tests/test_rule_enforcement.py` | 이 표가 모든 테스트 파일을 적는다. | 이 문서 |
| `tests/test_file_size_limit.py` | `scripts/`와 `skills/*/scripts/` 아래 Python 파일은 800줄 이하로 유지한다. | 이 파일 (소유자 규칙: 파일당 800줄 이하) |

## 세션 지침과 위임

| 집행자 | 집행하는 규칙 | 규칙 위치 |
|---|---|---|
| `tests/test_session_context.py` | 세션 훅은 core, common, 호스트 지침을 크기 상한 안에서 설정·경로 알림과 함께 렌더링한다. | `instructions/session/`, `README.md` (Automatic instructions) |
| `tests/test_session_settings_notice.py` | 설정 알림은 알린 설정이 바뀔 때만 나온다. | `README.md` (Automatic instructions) |
| `tests/test_commit_routing.py` | 새 커밋은 모두 `suggest-commit` 커밋 모드를 거친다. | `instructions/session/common.md` |
| `tests/test_planning_contract.py` | 계획과 설계 절차는 분리되고, 모델 선택의 출처는 하나이며, 독립 검증은 마지막 단계에서 자동으로 1회 실행하고 더 이른 검토는 승인이 필요하며, 읽기 전용 1회다. | `instructions/implementation-planning.md`, `instructions/independent-model-validation.md` |
| `tests/test_delegation_contract.py` | 호스트는 위임 계약을 받고, 수정하지 않은 이전 역할 파일은 교체하되 사용자가 고친 파일은 둔다. | `instructions/session/common.md`, `instructions/implementation-delegation.md` |
| `tests/test_claude_worker_contract.py` | Claude Code worker와 에이전트 정의는 선언한 도구, 모델, 어댑터 규칙을 유지한다. | `agents/`, `instructions/claude-agents.md` |
| `tests/test_codex_worker_contract.py` | Codex worker와 designer 역할은 할당받은 worker 규칙과 어댑터를 따른다. | `standalone-agents/`, `instructions/codex-agents.md`, `README.md` (Structure) |
| `tests/test_reviewer_contract.py` | 검토자는 모델과 읽기 전용 도구를 고정하고, 독립 검증 표는 레지스트리의 계열별 검토자를 그대로 적으며, scout는 로컬 조사만 맡는다. | `agents/`, `standalone-agents/`, `instructions/model-routing.md` |
| `tests/test_worker_route_accept.py` | `auto` 구현 worker 경로가 Claude 세션 문맥과 매니페스트에 나타난다. | `README.md` (Feature options) |
| `tests/test_worker_setting.py` | worker 모델과 사고 강도는 환경 변수, 저장한 옵션, 매니페스트 기본값 순으로 정한다. | `README.md` (Feature options) |
| `tests/test_role_runner.py` | 역할 실행기는 역할마다 샌드박스, 모델, 사고 강도, 도구를 넘기고 실제 실행을 검증한다. | `instructions/claude-agents.md`, `instructions/model-routing.md` |
| `tests/test_verify_spawn.py` | 생성한 Codex 에이전트는 기록에 기대한 모델과 사고 강도가 있을 때만 인정한다. | `instructions/codex-agents.md` |
| `tests/test_agent_guard.py` | Codex 내장 에이전트는 거부하고, 설치한 역할은 고정한 모델과 사고 강도로만 실행한다. | `instructions/codex-agents.md` |
| `tests/test_runtime_regressions.py` | 역할 파일을 동시에 만들 때도 사용자 파일을 보존한다. | `README.md` (Structure) |
| `tests/test_codex_usage.py`, `tests/test_codex_usage_accept.py` | Codex 주간 사용률을 안전하게 파싱하고, 모르면 `null`로 보고한다. | `scripts/codex_usage.py`, `hooks/mod/board.js` |
| `tests/test_language_guard.py` | 사용자에게 보내는 답변과 진행 안내는 응답 언어를 쓴다. | `instructions/session/common.md`, `README.md` (Response language) |
| `tests/test_host_settings.py` | 세션 시작은 실제로 적용되는 호스트 권한 설정을 짧게 알린다. | `README.md` (Host settings) |
| `tests/test_hook_python.py` | 훅은 설정한 Python 인터프리터를 고르고, 없으면 `python3`으로 대체한다. | `README.md` (Feature options) |
| `tests/test_codex_hook_trust.py` | 플러그인은 신뢰가 풀린 자기 Codex 훅만, HEAD를 공식 원격이 지금 `main`이나 `v*` 태그로 광고하거나 `main`에 포함하는 깨끗한 공식 checkout에서만 다시 신뢰하고 `hooks/list`로 확인한다. | `README.md` (Automatic instructions, Situation-based delegation) |

## 승인과 데이터 가드

| 집행자 | 집행하는 규칙 | 규칙 위치 |
|---|---|---|
| `tests/test_approval_guard.py` | 읽기는 통과하고, 쓰기는 승인이 필요하며, 파괴적 호출은 매번 묻고, 비밀 값 출력은 거부한다. | `instructions/session/core.md`, `README.md` (Approval guard) |
| `tests/test_approval_guard_modules.py` | 승인 가드의 분리된 모듈은 순환 없이 층으로 가져오고, 바꿔 끼우는 이름마다 소유 모듈이 하나이며, 진입점과 똑같이 프로그램이나 import로 쓰면 거부된다. | `README.md` (Approval guard) |
| `tests/test_approval_policy_tiers.py` | 조회, 세션 승인, 매번 승인 층이 경계를 지킨다. | `README.md` (Approval guard) |
| `tests/test_approval_one_approval.py`, `tests/test_approval_session_write.py` | 세션당 한 번의 승인이 파괴적이지 않은 쓰기를 모두 다루고, 되돌릴 수 없는 호출은 계속 묻는다. | `instructions/session/core.md`, `README.md` (Approval guard) |
| `tests/test_approval_session_scope.py` | `session` 범위는 중대한 종류를 빼고 세션당 한 번 묻는다. | `README.md` (Approval guard) |
| `tests/test_approval_local_scope.py`, `tests/test_approval_removal_targets.py` | 버려도 되는 로컬 작업은 매번 묻지 않고, 재귀 삭제는 대상을 풀어서 판단한다. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_reads.py` | 기록된 실수 없는 조회는 묻지 않는다: 따옴표 구분자 heredoc으로 쓰고 같은 명령에서 실행하는 스크립트, 이름이나 개수만 출력하는 xargs 조회, 비밀이 아닌 값에 대한 `env \| grep`, 로컬 docker 메타데이터. 내용을 출력하거나 비밀이 드러나는 인접 형태는 계속 묻는다. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_removals.py` | 기록된 실수 없는 삭제는 묻지 않는다: `${VAR:?}`, 리터럴 `for` 목록, `bash -c` 인자, `unset`·`export`를 지나도 유지되는 `mktemp` 추적으로 정해지는 대상, `.git`이 없는 `.[!.]*` 글롭, `runs` 밖의 플러그인 평가 작업 폴더, 잃는 내용이 없는 stash drop, Claude의 위험한 삭제 확인에서 답하는 임시 폴더 안 삭제. 풀리지 않거나 보호되거나 내용을 잃는 인접 형태는 계속 묻는다. | `README.md` (Approval guard) |
| `tests/test_approval_recorded_replay.py` | 에이전트 실수 없이 기록된 승인 가드 ask를 모두 훅으로 다시 실행하면 묻지도 막지도 않고, 남겨 둔 `$PWD` 삭제는 계속 묻는다. | `README.md` (Approval guard) |
| `tests/test_approval_python_risks.py` | 자격 증명 파일을 읽거나 비밀 이름 환경변수 값을 출력하는 Python 코드는 `cat`과 같은 민감 읽기 판정을 받고, 설정 여부 검사·이름 나열·검색어·평범한 읽기와 쓰기는 묻지 않는다. | `README.md` (Approval guard) |
| `tests/test_approval_installed_code.py` | 리다이렉트·`tee`·`sed -i`·`cp`·`mv`·`install`·`rsync`·Python으로 플러그인 캐시나 실행 중인 플러그인 루트에 쓰는 호출은 경로를 푼 뒤 자기 수정으로 거부하고, 그 코드를 읽거나 다른 곳에 쓰는 호출은 허용한다. | `README.md` (Approval guard) |
| `tests/test_approval_python_sensitive_writes.py` | `~/.ssh`·`~/.aws`·`~/.gnupg`, 셸 시작 파일, git 훅, Claude·Codex 설정 파일에 쓰는 Python은 매번 묻고, 작업 트리와 임시 공간의 평범한 Python 쓰기는 묻지 않는다. | `README.md` (Approval guard) |
| `tests/test_approval_false_positives.py`, `tests/test_approval_classification_safety.py` | 무해한 호출과 비밀 메타데이터 조회를 쓰기나 비밀 값 출력으로 오인하지 않는다. | `README.md` (Approval guard) |
| `tests/test_approval_extensions.py`, `tests/test_approval_reuse.py` | 사전 승인 키와 민감 조회 승인은 지정한 대상만 다룬다. | `README.md` (Approval guard) |
| `tests/test_approval_retries.py` | 답을 받지 못한 승인 요청이 반복되면 새 프롬프트 전까지 거부한다. | `README.md` (Approval guard) |
| `tests/test_approval_heartbeat.py` | 가드는 현재 훅이 도구를 검사했는지 확인한다. | `README.md` (Approval guard) |
| `tests/test_approval_risk_record.py`, `tests/test_approval_wording.py` | 쓰기와 중대한 호출을 기록하고, 승인 문구는 언어 설정을 따른다. | `README.md` (Claude Code mod, Approval guard) |
| `tests/test_approval_review_fixes.py` | 래퍼 형태, `curl` 자격 증명, 가림 처리, 실행 가능한 MCP 입력을 안전하게 분류한다. | `README.md` (Approval guard) |
| `tests/test_approval_tabularis.py` | Tabularis 쿼리는 연결 메타데이터와 맞는 SQL 분류기를 따른다. | `README.md` (Approval guard) |
| `tests/test_codex_native_approval.py`, `tests/test_permission_request_claude.py` | 각 호스트의 자체 승인 창이 세션의 첫 쓰기 승인을 이어받는다. | `README.md` (Approval guard) |
| `tests/test_datagrip_guard.py`, `tests/test_db_read_policy.py` | 데이터베이스 쿼리는 읽기일 때만 묻지 않고 실행한다. | `instructions/infrastructure-access.md`, `README.md` (DataGrip query guard) |
| `tests/test_limits_file_protection.py` | 데이터베이스 읽기 한도 파일을 보호한다. | `README.md` (Approval guard) |
| `tests/test_secret_exec.py`, `tests/test_secret_patterns.py` | 비밀 값은 출력되지 않은 채 명령에 전달되고, 공유 패턴이 그 값을 가린다. | `instructions/protected-values.md` |

## 스킬

| 집행자 | 집행하는 규칙 | 규칙 위치 |
|---|---|---|
| `skills/skill-builder/tests/test_metadata.py` | 스킬 메타데이터를 파싱하고 검증한다. | `skills/skill-builder/SKILL.md` |
| `skills/skill-builder/tests/test_sibling_references.py` | 스킬은 선언한 대로만 형제 스킬의 참조 문서를 읽고, 형제 스킬을 호출하지 않는다. | `skills/skill-builder/SKILL.md` (Portability contract) |
| `skills/skill-builder/tests/test_schema_single_source.py` | JSON을 내보내는 에이전트 프롬프트는 단일 스키마 출처를 따른다. | `skills/skill-builder/references/schemas.md` |
| `skills/skill-builder/tests/test_benchmark.py`, `skills/skill-builder/tests/test_evaluation.py` | 벤치마크는 토큰 값을 지어내지 않고, 트리거 평가는 실제 모델 없이 동작한다. | `skills/skill-builder/SKILL.md` |
| `skills/skill-builder/tests/test_implementation_worker_scope.py`, `skills/skill-builder/tests/test_model_runner.py` | 평가 모델 어댑터와 실행기는 범위와 프로세스 계약을 지킨다. | `skills/skill-builder/references/execution-methods.md` |
| `skills/skill-builder/tests/test_package_skill.py`, `skills/skill-builder/tests/test_viewer.py` | 패키징은 파일 경계를 지키고, 평가 뷰어는 HTML을 이스케이프하며 피드백을 저장한다. | `skills/skill-builder/SKILL.md` |
| `skills/session-retro/tests/test_list_sessions.py` | 세션 목록은 하루 경계, 호스트 필터, 출력 형식, 오류 처리를 지킨다. | `skills/session-retro/SKILL.md` |
| `skills/decision-navigator/tests/test_local_lock.py`, `skills/decision-navigator/tests/test_decision_eval_fixtures.py` | 티켓 점유는 한 번에 하나만 성공하고, 평가 픽스처는 계속 쓸 수 있다. | `skills/decision-navigator/SKILL.md` |
| `skills/deep-interview/tests/test_interview_eval_fixtures.py` | 인터뷰 평가 사례는 상태 흐름과 입력 파일을 유지한다. | `skills/deep-interview/SKILL.md` |
| `skills/document-to-confluence/tests/test_column_widths.py`, `skills/document-to-confluence/tests/test_image_size.py`, `skills/document-to-confluence/tests/test_text_parity.py`, `skills/document-to-confluence/tests/test_validate_body.py` | 변환한 페이지는 열 너비, 이미지 크기, 텍스트 일치를 지키고 로컬 경로를 담지 않는다. | `skills/document-to-confluence/SKILL.md` |
| `skills/document-to-confluence/tests/test_render_diagrams.mjs` | 다이어그램 캡처는 유효하고 겹치지 않는 파일 이름을 쓰고, 요청이 없으면 브라우저 샌드박스를 켜 두며, 항상 브라우저를 닫는다. | `skills/document-to-confluence/references/diagrams.md` (Naming and browser flags) |
| `skills/orca-plugin-refresh/tests/test_orca_plugin_refresh.py` | 갱신은 입력창이 빈 유휴 세션에만 입력을 보낸다. | `skills/orca-plugin-refresh/SKILL.md` |
| `skills/tiki-taka/tests/test_runner.py`, `skills/tiki-taka/tests/test_stream_agent.py`, `skills/tiki-taka/tests/test_detached_job.py`, `skills/tiki-taka/tests/test_questions.py` | 토론 실행기는 상태, 완료 판정, 정리, 질문 파일 규칙을 지킨다. | `skills/tiki-taka/SKILL.md` |
| `skills/local-data-cleanup/tests/test_survey_kinds.py`, `skills/local-data-cleanup/tests/test_survey_checks.py`, `skills/local-data-cleanup/tests/test_merge_delete.py` | 조사는 읽기 전용으로 남고 안전하지 않은 후보를 보고 전용이나 보호 항목으로 바꾸며, 삭제는 두 판정이 모두 허용하고 사용자가 고른 항목만 지운다. | `skills/local-data-cleanup/SKILL.md` |
| `skills/report-skill-gap/tests/test_find_tracker.py` | 트래커 탐색은 플러그인 루트를 찾아 `issue-target.json`을 검증하고, 선언이 없거나 잘못되면 트래커를 추측하지 않고 그 상태를 보고한다. | `skills/report-skill-gap/SKILL.md` |
| `tests/test_issue_target.py` | 이 플러그인 루트의 `issue-target.json`은 공개 GitHub 트래커를 선언한다. | `README.md` (report-skill-gap) |
| `skills/skill-builder/scripts/quick_validate.py`를 모든 스킬에 실행 | 모든 스킬 폴더가 검증을 통과한다. | `README.md` (Development checks) |

## 평가 하네스

| 집행자 | 집행하는 규칙 | 규칙 위치 |
|---|---|---|
| `tests/test_e2e_eval_harness.py` | 엔드투엔드 실행은 시험할 플러그인 리비전을 불러오고, 권한이나 플러그인 훅을 절대 우회하지 않으며, 사용량 한도 뒤에 이어서 실행하고, 모든 변형의 토큰, 비용, 결과를 같은 방식으로 기록한다. | `evals/e2e/README.md` |
| `tests/test_e2e_eval_graders.py` | 골든 작업마다 채점기는 수정하지 않은 픽스처를 실패시키고 기준 해답을 통과시키며, 채점하는 저장소를 바꾸지 않는다. | `evals/e2e/README.md` (Graders) |
