# 세션 재개

> 영어 원본: [resume.md](../../../../../skills/orca-plugin-refresh/references/resume.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

`resume_approval_needed`를 보고한 Claude Code 세션에만, 그리고 현재 요청에서 사용자가 승인한 터미널에만 실행한다.
`python3 <script> resume --run-id <run_id> --terminal <handle> --json`을 실행하며, 승인된 세션마다
`--terminal`을 반복한다. 핸들은 보고서의 `…` 접미사가 아니라 Orca 터미널 핸들 전체다.

## 스크립트가 하는 일

이름을 붙인 터미널마다 다음 순서로 처리한다.

1. 세션 표식의 기록 파일 이름에서 대화 ID를 읽는다. 없으면 그 세션을 건너뛴다.
2. 세션이 자체 턴 기록으로 유휴 상태이고, 백그라운드 알림이 남아 있지 않고, 화면에 열린 질문이나 승인 프롬프트가
   없고, 입력 줄이 비어 있는지 확인한다. 하나라도 아니면 세션을 건너뛰고 아무것도 보내지 않는다.
3. 세션 자신의 환경에 있는 `ORCA_TERMINAL_HANDLE`로 세션 프로세스를 찾고, 터미널의 셸이 아니라 그 프로세스에서
   정확한 인자와 `CLAUDE_CONFIG_DIR`를 읽는다.
4. `/exit`를 보내 그 프로세스가 끝나기를 기다린 뒤, 같은 터미널에 한 줄을 보낸다. 그 줄은 프로세스의
   `CLAUDE_CONFIG_DIR`, 현재 `claude` 실행 파일, 원래 옵션 인자, 그리고 `--resume <대화 ID>`로 이루어진다.
   어느 토큰이 옵션 값인지는 `claude --help`에서 읽고, 위치 인자 프롬프트와 `--continue`, `--resume`, `--session-id`,
   `--fork-session`, `--print`는 뺀다. 도움말을 읽을 수 없거나 옵션이 도움말에 없으면 `/exit` 전에
   `launch_arguments_unknown`으로 그 세션을 건너뛴다.
5. 세션 표식이 같은 대화에 대해 `source: resume`으로 다시 쓰였는지, 새 프로세스의 `CLAUDE_CONFIG_DIR`가 같은지,
   이어서 보낸 `/reload-plugins`가 오류 없이 불러오는지 확인한다.

## 세션별 보고

- `done`과 `resumed`: 모든 확인을 통과했다. `note: no_config_dir_in_process`는 끝난 프로세스에
  `CLAUDE_CONFIG_DIR`가 없어 줄에 포함하지 않았다는 뜻이다. `release_before`와 `release_after`는 두 릴리스를 알려 준다.
- `skipped`: 아무것도 보내지 않았고 세션을 끝내지 않았다. `busy`, `unsent_input`, `input_unknown` 등 준비되지 않은
  이유는 세션이 유휴 상태가 아니거나 입력 줄이 비어 있지 않다는 뜻이다. `background_task`는 백그라운드 작업, 서브에이전트,
  예약된 깨우기가 아직 알림을 남기고 있어 세션을 끝내면 멈춘다는 뜻이므로 사용자에게 알리고 나중에 다시 고르게 한다.
  `session_id_unknown`, `process_not_found`, `session_process_ambiguous`, `claude_missing`, `launch_arguments_unknown`은
  재개할 대상을 식별하지 못했다는 뜻이다. `not_a_claude_session`은 그 터미널이 Claude Code 세션이 아니라는 뜻이다.
- `failed`: 세션이 이미 끝났다. `exit_timeout`은 프로세스가 끝나지 않았고 재개 줄을 보내지 않았다는 뜻이다.
  `resume_marker_missing`과 `resume_session_mismatch`는 재개된 세션이 같은 대화인지 확인하지 못했다는 뜻이다.
  `resumed_process_missing`과 `config_dir_mismatch`는 새 프로세스가 없거나 다른 설정 폴더로 실행 중이라는 뜻이다.
  `plugin_load_error`는 재개된 세션이 여전히 로드 오류를 보고한다는 뜻이며 `plugin_load`에 개수가 있다. 해당
  터미널을 확인하라고 사용자에게 알린다. 스크립트는 다시 시도하지 않는다.
