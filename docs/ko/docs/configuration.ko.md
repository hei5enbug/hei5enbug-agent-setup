# 설정

> 영어 원본: [configuration.md](../../configuration.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 플러그인 옵션, 호스트 설정 검사, 플러그인이 바꿀 수 있는 설정을 설명합니다.

## 호스트 설정

일부 호스트 설정은 승인 프롬프트를 늘리거나 가드가 실행되지 못하게 합니다. `scripts/host_settings.py`는 이를 점검하고,
Codex에서만 짧은 허용 목록을 고칩니다.

```bash
python3 <plugin root>/scripts/host_settings.py check [--host claude|codex] [--json]
python3 <plugin root>/scripts/host_settings.py apply [--host claude|codex] [--json]
```

두 명령 모두 `--claude-dir`, `--codex-home`, `--codex-bin`도 받습니다. 호스트는 기본적으로 명령을 실행하는 호스트입니다.
`check`는 읽기이며 아무것도 쓰지 않습니다. 문제마다 한 줄을 보고합니다.

- Claude Code: `defaultMode`가 `dontAsk`인 경우와 Bash나 MCP 도구에 적용되는 `permissions.ask` 규칙(최대 세 개 표시).
- `~/.codex/config.toml`에 `[features] plugin_hooks`가 `true`가 아닌 경우(양쪽 호스트).
- Codex만: 플러그인 훅이 확인되지 않은 경우(heartbeat 해시 불일치), `config.toml`이 올바른 TOML이 아닌 경우,
  `rules/hei5enbug.rules`가 없거나 읽을 수 없거나 구버전이거나 플러그인 소유가 아닌 경우, MCP 서버에 `prompt` 승인 모드가 없는 경우,
  `approval_guard`가 꺼져 있어 모드 단계를 건너뛴 경우, 가드가 다루는 MCP 도구에 읽기에도 묻는 도구별 `prompt`가 있는 경우.
- Codex만: 사용자 소유 `rules/*.rules` 파일에서 `kubectl get`, `helm list`, `az show`, `git status` 같은 읽기 접두에 대한
  `prompt`·`forbidden` 규칙.

`apply`는 이 허용 목록만, 그것도 Codex에서만 바꿉니다. Claude Code에서는 아무것도 바꾸지 않고 그 사실만 알립니다.

- `[features] plugin_hooks`: `codex features list`에 보이면 `codex features enable plugin_hooks`로 켭니다. 그 명령이 없으면
  직접 설정하라고 알립니다.
- 플러그인 소유 파일 `~/.codex/rules/hei5enbug.rules`: 플러그인 버전의 텍스트로 만들거나 갱신합니다. [승인 가드](approval-guard.ko.md#승인-가드)가
  쓰는 래퍼 스크립트에 대한 `prompt` 규칙을 담고 있습니다. 그 경로가 심볼릭 링크이거나 기존 파일에 플러그인 소유 헤더
  줄이 없으면 `apply`는 알리기만 하고 아무것도 쓰지 않습니다.
- `approval_guard`가 켜져 있는 동안 모든 `[mcp_servers.<name>]` 표의 `default_tools_approval_mode = "prompt"`와, 이미 다른
  모드를 지정한 도구별 표의 `approval_mode = "prompt"`. 그 줄만 고치며, 결과가 의도대로 파싱되지 않으면 아무것도 쓰지 않습니다.

`apply`는 파일을 바꾸기 전에 `<file>.bak-hei5enbug-<YYYYMMDD>`로 복사해 두며, 하루에 한 번만 만듭니다. 바꾼 항목마다 한 줄을
출력하고, 두 번째 실행은 아무것도 바꾸지 않습니다. 사용자 소유 규칙 파일, Claude Code 설정, 훅 신뢰는 절대 고치지 않습니다.

세션 시작 시 훅이 하는 일은 `host_settings` 옵션이 정합니다. `apply`(기본값)는 Codex에서 먼저 `apply`를 실행해 바꾼 내용을 알리는
안내 한 줄을 추가하고, 이어서 `check`가 찾은 나머지 문제를 보고합니다. `report`는 보고만 합니다. 다른 값은 `apply`로 취급합니다.
Claude Code는 이 옵션을 `/config`에서 읽고, Codex는 `HEI5ENBUG_HOST_SETTINGS`에서 읽습니다.

## 기능 옵션

끌 수 있는 boolean 기능은 일곱 가지이며 각각 기본값은 켜짐입니다. Claude Code의 구현 worker 경로, worker 모델과 사고 강도,
검토 모델, 호스트 설정 모드, 에이전트 세션을 시작하는 데 필요한 최소 여유 메모리(`session_memory_min_mb`),
훅 Python 인터프리터, 이 플러그인과 함께
새로고침할 플러그인(`refresh_plugins`)은 문자열 옵션입니다. 경로는 `auto`, `codex`, `haiku`, `sol`, `sonnet` 중 하나를 고르고, 값이 비어 있거나 알 수 없으면
`auto`를 씁니다.
`auto`에서는 메인 세션이 작업마다 worker를 고릅니다. 호스트 설정 모드는 `apply`와 `report` 중 하나를 고르고, 값이 비어 있거나
알 수 없으면 `apply`를 씁니다. 이 모드는 `SessionStart`가 허용 목록의 Codex 설정을 바꿔도 되는지 정합니다.
[호스트 설정](#호스트-설정)을 참고하세요.
검토 모델은 스킬 검토 역할을 `high`로 실행하며,
[모델 라우팅](../../../instructions/model-routing.md#keep-role-settings-fixed)의 사고 강도 규칙에 따라 `xhigh`로 실행합니다. 독립 검증은 이 설정을
쓰지 않습니다.
고정된 일곱 모델 ID 중 하나를 고릅니다. 값이 비어 있거나
알 수 없으면 `gpt-6-astra`를 씁니다. 플러그인 옵션은 `/config`나 `claude plugin configure`에서 설정합니다. Codex에서는 세션 시작 전에 환경변수를
설정합니다. boolean 기능은 값이 `false`, `0`, `off`, `no`(대소문자 무시)이면 꺼집니다.

Claude Code `worker` 에이전트는 `worker_model`과 `worker_effort`로 실행됩니다. mod가 이 값으로 worker를 생성하며, 잘못된 값이면 레지스트리 고정값을
씁니다. 세션 컨텍스트는 이 값을 `Worker agent model: <model> at <effort>.` 줄로 알립니다. Codex에는 플러그인 설정 화면이 없으므로 세션 훅이
Claude Code가 저장한 설정(`~/.claude/settings.json`의 `pluginConfigs`, 또는 `CLAUDE_CONFIG_DIR` 아래)에서 `codex_worker_model`과
`codex_worker_effort`를 읽기 전용으로 읽습니다. 환경변수가 이 값을 덮어쓰고, 잘못된 값이면 한 줄 안내와 함께 기본값을 씁니다. 세션 컨텍스트는
`Codex worker model: <model> at <effort>.` 줄로 알립니다. 값은 다음 Codex 세션부터 적용되며, 이 값을 읽을 때는
Codex 설정이나 Claude 설정을 쓰지 않습니다. Codex 설정을 쓰는 것은 [호스트 설정](#호스트-설정)의 허용 목록 변경뿐입니다.

| 기능 | Claude Code `/config` 키 | Codex 환경변수 |
|---|---|---|
| 내장 서브에이전트 차단 | `agent_guard` | `HEI5ENBUG_AGENT_GUARD` |
| 역할 모델 고정 | `role_pinning` | 해당 없음 |
| 도구 호출 위험 라벨 | `risk_highlight` | 해당 없음 |
| 서브에이전트 작업 현황판 | `work_board` | 해당 없음 |
| 도구 결과 비밀값 가리기 | `secret_redaction` | 해당 없음 |
| 구현 worker 경로 | `implementation_worker` (`auto`, `codex`, `haiku`, `sol`, 또는 `sonnet`) | 해당 없음 |
| Claude Code worker 모델과 사고 강도 | `worker_model` (기본 `claude-haiku-5-5`), `worker_effort` (기본 `high`) | 해당 없음 |
| Codex worker 모델과 사고 강도 | `codex_worker_model` (`gpt-5.6-luna` 또는 `gpt-6.1-sol`, 기본 `gpt-5.6-luna`), `codex_worker_effort` (`high` 또는 `xhigh`, 기본 `high`) | `HEI5ENBUG_CODEX_WORKER_MODEL`, `HEI5ENBUG_CODEX_WORKER_EFFORT` |
| 검토 모델 | `review_model` (고정 모델 ID, 기본 `gpt-6-astra`) | 해당 없음 |
| 응답 언어 가드 | `language_guard` | `HEI5ENBUG_LANGUAGE_GUARD` |
| DataGrip 쿼리 가드 | `datagrip_guard` | `HEI5ENBUG_DATAGRIP_GUARD` |
| 승인 가드 | `approval_guard` | `HEI5ENBUG_APPROVAL_GUARD` |
| 승인 범위 | `approval_scope`(`tiered` 또는 `session`, 기본값 `tiered`) | `HEI5ENBUG_APPROVAL_SCOPE` |
| 다른 저장소에 Orca 워크트리 사용 | `orca_worktree` | `HEI5ENBUG_ORCA_WORKTREE` |
| 모델 턴 없는 Orca 상태 기록 | `orca_status_writes` ([Orca 상태](guards.ko.md#orca-상태) 참고) | `HEI5ENBUG_ORCA_STATUS_WRITES` |
| 호스트 설정 모드 | `host_settings` (`apply` 또는 `report`, 기본 `apply`) | `HEI5ENBUG_HOST_SETTINGS` |
| 에이전트 세션을 시작하는 데 필요한 최소 여유 메모리 | `session_memory_min_mb` (MB, 기본값 `2048`; `0`, `off`, `false`, `no`이면 차단 규칙을 끔; [Orca 세션 시작](guards.ko.md#orca-세션-시작) 참고) | `HEI5ENBUG_SESSION_MEMORY_MIN_MB` |
| 훅 Python 인터프리터 | `python` (절대 경로, 기본값 빈 문자열) | `HEI5ENBUG_PYTHON` |
| 이 플러그인과 함께 새로고침할 플러그인 | `refresh_plugins` (쉼표로 구분한 `plugin@marketplace` ID, 기본값 빈 문자열) | `HEI5ENBUG_REFRESH_PLUGINS` |
| `~/.codex/AGENTS.md`의 서브에이전트 허용 블록 | 해당 없음 | `HEI5ENBUG_SUBAGENT_POLICY` |
| 질문 기능 플래그 | 해당 없음 | `HEI5ENBUG_CODEX_ASK_TOOL` |

훅 Python 인터프리터는 Python 3.12 이상 인터프리터의 절대 경로입니다. SQL 가드의 파서를 쓰려면 그 인터프리터에 `pglast`를 설치합니다.
모든 훅은 `scripts/hook_python.sh`를 거쳐 시작하며, 이 런처가 해당 인터프리터로 스크립트를 실행합니다. Claude Code의 `python` 옵션을 먼저 보고
그다음 `HEI5ENBUG_PYTHON`을 보며, `/`로 시작하고 실제로 존재하는 실행 파일을 가리키는 경로만 인정합니다. 값이 비어 있거나
상대 경로이거나 없는 경로이거나 유효하지 않으면 `PATH`의 `python3`로 돌아가므로, 옵션을 설정하지 않으면 이전과 똑같이 동작합니다. 경로를 지정하면 pyenv shim 같은 버전 관리자 shim을
거치지 않습니다. 논리 코어 10개에 1분 평균 부하가 60~69였던 한 기기에서 `python3 -c pass`는 shim을 거치면 2.05~3.18초, 실제 인터프리터로는
0.09~0.17초 걸렸습니다. Bash 입력 하나에 대한 `required_checks_hook.py`는 1.81~3.75초 대 0.24~0.73초,
`orca_placement_hook.py`는 2.02~2.26초 대 0.56~0.81초였습니다. shim은 프로젝트마다 다른 Python을 고를 수도 있습니다.
런처는 컴파일된 바이트코드를 `$XDG_STATE_HOME/hei5enbug-agent-setup/pycache/`(기본값 `~/.local/state`)에 캐시합니다.
이 폴더는 가드 상태 폴더이므로 승인 가드는 `approvals/`, `heartbeats/`, `interpreter/`처럼 에이전트의 쓰기를 거부합니다.
절대 경로의 상태 폴더를 알 수 없으면 훅은 캐시 없이 실행됩니다.

유효한 설정 경로가 없으면 런처는 해결한 인터프리터도 캐시합니다. 프로세스를 시작하지 않고 `PATH`의 첫 `python3`를 읽고, 상태 폴더의
`interpreter/cache`가 같은 `python3`와 실행 가능한 파일을 가리키면 그 절대 경로로 실행합니다. 해결기는 캐시를 쓴 다음 현재 사용자만
들어갈 수 있는 폴더 안에 두 번째 파일 `interpreter/verified`를 씁니다. 런처는 두 파일이 모두 현재 사용자의 소유이고, 어느 쪽도
심볼릭 링크가 아니며, 캐시가 `verified`보다 새롭지 않을 때만 캐시를 믿습니다. 다른 계정이 캐시를 다시 쓰면 캐시가 더 새로워지므로
훅은 `PATH`의 `python3`로 실행됩니다. 그룹이나 다른 사용자가 쓸 수 있는 캐시는 훅이 시작할 때 지웁니다. 남는 한계는 런처의 확인과
읽기 사이 짧은 순간의 쓰기이며, 이는 현재 사용자가 소유한 파일에 쓰기 권한이 있어야 합니다. 캐시가 없거나 낡았을 때, 예를 들어 다른
`python3`가 `PATH` 앞에 오거나 파일이 지워졌을 때는 훅이 전과 같이 `PATH`의 `python3`로 실행되고, 분리된 해결기 하나가 루트 폴더에서 그
`python3`를 한 번 실행해 `sys.executable`을 출력하게 한 뒤 Python 3.12 이상일 때만 결과를 캐시에 씁니다. 모든 세션이 해결기의
프로세스 ID를 담은 잠금 파일 `interpreter/lock`을 함께 쓰므로 해결기는 많아야 하나만 돌고, 훅은 그 프로세스가 사라졌을 때만 잠금을
넘겨받습니다. 해결이 실패하면 아무것도 캐시하지 않고 `interpreter/failed`가 모든 세션에서 1분 동안 다시 시도하지
못하게 합니다. 해결은 프로젝트의 버전 파일이 아니라 사용자의 기본 `python3`를 따릅니다.

런처 환경이 일치하지 않으면 mod는 고정 GPT 요청을 공급자에 보내기 전에 거부합니다. 이 거부에는 토글이 없습니다.
세션 지침과 운영 규칙도 저장소 간 작업 규칙을 불러오는 `orca_worktree` 줄을 제외하면 토글이 없으며,
끄려면 플러그인 자체를 비활성화합니다.

## Codex 자동 설정

Codex에서는 세션 훅이 두 설정을 관리하며, 두 설정 모두 다음 세션부터 적용됩니다. 훅은 아래 표시 블록을
`~/.codex/AGENTS.md` 끝에 유지하고, 파일이 없으면 만듭니다.

```text
<!-- hei5enbug:subagents -->
When hei5enbug-agent-setup is active, use subagents according to its situation-based delegation rules.
<!-- /hei5enbug:subagents -->
```

또한 `codex features list`에서 `default_mode_request_user_input` 기능이 꺼져 있으면 켜므로, Default 모드에서도
`request_user_input`을 쓸 수 있습니다. blocking을 강제하거나 클라이언트의 자동 응답 처리를 끄는 기능은 아닙니다.
필수 결정에는 [확인 질문 규칙](../instructions/session/common.ko.md#확인-질문)을 따르고, 연결이 중단되면
[연결 복구](../instructions/connection-recovery.ko.md)를 적용합니다.
`HEI5ENBUG_SUBAGENT_POLICY=off`로 설정하면 표시 블록만 지우고 블록 밖은 절대 고치지
않습니다. `HEI5ENBUG_CODEX_ASK_TOOL=off`로 설정하면 기능을 다시 끄지만, 플러그인이 켠 경우에만 끄며 직접 켠 기능은 그대로
둡니다. 실패한 단계는 다음 세션 시작 때 다시 시도하며, 세션 지침 로드를 막지 않습니다. 실제 실행에는 호스트 규칙, 훅 신뢰와
사용 가능한 도구가 계속 적용됩니다.
[공식 Codex 서브에이전트 계약](https://learn.chatgpt.com/docs/agent-configuration/subagents)을 참고하세요.
