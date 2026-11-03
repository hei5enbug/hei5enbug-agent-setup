# 위임

> 영어 원본: [delegation.md](../../../../../skills/skill-issue-creator/references/delegation.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이슈를 담당 플러그인의 저장소에 있는 세션으로 넘기는 규칙이다.
`orca status --json`이 접근 가능한 런타임을 보고하고 이 세션이 그 저장소에서 작업 중이 아니면 초안을 쓰기 전에 읽는다.
인계하면 초안 작성, 중복 검색, 등록, 검증을 다른 세션이 맡으므로 원래 세션은 자기 작업으로 돌아간다.

## 결정

`find_tracker.py` 결과에서 `plugin_name`을 가져온다.
담당 저장소는 `orca repo list --json`에 등록된 저장소 중, 복제본에 그 플러그인 이름을 명시한
`.claude-plugin/plugin.json`이나 `.codex-plugin/plugin.json`이 있는 저장소이다.
이 세션의 작업 디렉터리가 속한 Git 루트에 그 이름을 명시한 매니페스트가 있으면 이미 담당 저장소에서 작업 중인 것이다.
이때는 이 파일의 나머지를 건너뛰고 이 세션에서 계속한다.

다음 중 하나라도 성립하면 이 세션에서 이슈를 등록하고 이유를 한 줄로 밝힌다.

- Orca에 담당 저장소의 작업 공간이 없다. 작업 공간은 복제본이나
  `orca worktree list --repo id:<repoId> --json`에 나오는 워크트리 중 하나이다.
- `ORCA_TERMINAL_HANDLE`이 설정되지 않았거나, "원래 세션"의 기록에 `transcript_path`가 없다.
- "인계"의 전송이 수락되지 않거나, 위임받을 세션이 하나도 유휴 상태가 되지 않는다.

## 위임받을 세션 찾기

`<host>`는 Claude Code에서는 `claude`, Codex에서는 `codex`이다. 이 세션과 같은 호스트의 세션만 사용한다.

1. `orca terminal list --worktree id:<workspace id> --json`으로 작업 공간과 그에 속한 각 워크트리의 터미널을 나열한다.
2. 다음을 모두 만족하는 첫 번째 `<host>` 터미널을 고른다.
   - `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 5000 --json`이 `wait.satisfied`를 보고한다.
   - `orca terminal read --terminal <handle> --screen`에 열린 질문이나 승인 프롬프트가 없다.
   - 입력 줄이 비어 있다. `--text x`를 보내고 줄에 `x`만 보이면 `--text $'\x7f'`로 지운다.
     그렇지 않으면 `x`를 지우고 그 터미널에는 아무것도 보내지 않은 채 다음 터미널로 넘어간다.
3. 통과한 터미널이 없으면 `orca terminal create --worktree id:<workspace id> --command <host> --json`을 실행하고,
   이어서 `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 60000 --json`을 실행한다.
   한 번 더 길게 기다린 뒤에도 `wait.satisfied`가 false이면 이 세션에서 등록한다.

다른 세션의 프롬프트에 답하지 않는다.
전송 및 읽기 플래그에는 [메시지 규칙](../../../instructions/cross-repository.ko.md)을 적용한다.

## 원래 세션

세션 시작 훅은 대화형 Orca 터미널마다
`$ORCA_USER_DATA_PATH/hei5enbug-agent-setup/terminals/$ORCA_TERMINAL_HANDLE.json`에 기록을 남긴다.
그 기록의 `transcript_path`를 읽는다. 이 값이 원래 세션의 대화 기록 파일이다.
원래 터미널 핸들은 `$ORCA_TERMINAL_HANDLE`이다.

## 인계

`orca terminal send --terminal <handle> --text "<handoff>" --enter --json`으로 메시지 하나를 보낸다.
다음 내용을 담는다.

- 이슈 하나에 대해 `skill-issue-creator`를 실행하라는 지시
- 몇 줄로 정리한 빈틈, 플러그인 내부의 담당 파일 경로, 1단계에서 모은 사례의 식별자
- 원래 세션의 대화 기록 파일과, 그 안의 사용자 메시지를 모두 읽고 위임받은 세션에서 요구 사항 및 질문 규칙을 적용하라는 지시
- 원래 터미널 핸들과, "결과 회신"에 따라 이슈 링크를 돌려보내라는 지시

비밀 정보는 넣지 않고, 대화 기록 파일 외의 로컬 경로도 넣지 않는다.
전송이 `accepted: true`를 보고하면 인계가 끝난 것이다. 작업이 끝날 때까지 기다리지 않는다.
어느 작업 공간의 세션이 이슈를 맡았고 그 세션에서 질문이 표시된다는 점을 사용자에게 한 줄로 알린 뒤 원래 작업을 계속한다.

링크는 이 터미널의 Orca 메일함으로 도착하며, 메일함은 이 터미널이 열려 있는 동안만 링크를 보관한다.
호스트가 백그라운드 명령 종료를 알리는 기능을 제공하면 다음 명령을 백그라운드에서 실행하고, 반환되면 링크를 보고한다.
`orca orchestration check --terminal $ORCA_TERMINAL_HANDLE --wait --types status --timeout-ms 1800000 --json`.
그렇지 않거나 명령이 시간 초과되면, 최종 답변 전에 같은 검사를 `--wait` 없이 한 번 실행한다.

## 위임받은 세션

대화 기록 파일을 사용자 메시지의 원본으로 삼아 `skill-issue-creator`를 2단계부터 실행한다.
사용자에게 질문할 때는 이 세션에서 묻는다. 9단계 후에는 결과를 회신한다.

## 결과 회신

`orca orchestration send --to <original terminal handle> --from $ORCA_TERMINAL_HANDLE --subject "Issue filed"
--body "<issue link>" --type status --json`을 실행한다. 핸들은 인계 내용에 명시된 것을 쓴다.
링크나 등록하지 않은 이유를 보내고 초안 문구는 보내지 않는다.
