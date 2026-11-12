# 승인 가드

> 영어 원본: [approval-guard.md](../../approval-guard.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 승인이 필요한 호출, 호스트별 승인 절차, 가드의 보호 대상을 설명합니다.

## 판정 종류

`PreToolUse` 훅은 Bash, MCP, Claude 파일 도구(`Read`, `Edit`, `Write`, `MultiEdit`, `NotebookEdit`),
Codex `apply_patch` 호출 전에 `scripts/approval_guard.py`를 실행합니다. 같은 스크립트가 `PermissionRequest`,
`PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`도 처리합니다. 양쪽 호스트에서 읽기는 승인 없이 실행됩니다. 호출은 세 층 중
하나에 들어가거나, 거부되거나, 통과합니다.

| 판정 | 동작 |
|---|---|
| 읽기 | 승인 없이 실행됩니다. |
| 세션 승인 | 세션당 한 번 묻고, 세션이 끝날 때까지 같은 종류의 이후 호출을 모두 허용합니다. 두 가지가 있습니다. `write:session`은 명령이나 대상과 관계없이 운영 환경 변경, git 푸시, MCP, DataGrip, tabularis 쓰기를 포함한 모든 쓰기를 허용하며, 분류할 수 없는 호출도 텍스트에 파괴적 작업이 없으면 쓰기입니다. `sensitive:session`은 보호 값이 노출될 수 있는 호출인 모든 민감 읽기를 허용합니다. 하나를 승인해도 다른 하나는 승인되지 않으며, 둘 다 필요한 호출은 한 번 물어 둘 다 승인합니다. |
| 매번 | 호출할 때마다 묻고 승인을 남기지 않으므로 다음 실행에도 다시 묻습니다. 아래 목록이 이 작업들입니다. Claude 프롬프트는 `Asks every time:`으로 시작합니다. 이런 호출이 세션 승인도 필요로 하면 승인이 그 승인까지 주고, 프롬프트가 이를 밝힙니다. |
| 요청 | 실제 호출 전에 세션 승인 묶음을 요청합니다. |
| 비밀 | 명령이 비밀 값을 출력하므로 두 호스트 모두에서 거부됩니다. |
| 금지 | 두 호스트 모두에서 거부됩니다. 가드 스크립트를 실행하거나, 승인 상태를 편집하거나, 설치된 플러그인 코드를 쓰는 경우입니다(아래 자기 승인 규칙 참고). |
| 통과 | 가드가 다루지 않는 호출이므로 호스트의 기존 권한 절차가 결정합니다. |

## 매번 승인이 필요한 호출

매번 묻는 목록에는 원격·운영 시스템에 영향을 주거나 복구할 수 없는 로컬 데이터를 지우는 작업을 둡니다.
그래서 한 번 승인해도 다음 실행에는 다시 묻습니다. 버려도 되거나 복구할 수 있는 로컬 작업은 이 목록에서 제외합니다.
아래 로컬 범위 규칙에서 이를 설명합니다.

1. 파괴적 `git push`: 강제·force-with-lease·삭제·mirror·prune push와 `+`·`:` refspec.
   단 로컬 범위 규칙에서 설명하는 lease로 보호된 기능 브랜치 푸시는 제외합니다.
2. 커밋하지 않은 작업 버리기: dry run 없는 강제 `git clean`, `git stash drop`·`git stash clear`.
   추적 파일에 커밋하지 않은 변경이 있거나 저장소 상태를 읽을 수 없을 때의 `git reset --hard`,
   강제 checkout이나 `.` checkout, 작업 트리의 `.`·`:/` restore도 포함합니다.
3. 보호 경로나 외부 경로, 풀 수 없는 대상의 재귀 삭제. 단 로컬 범위 규칙에서 설명하는 복구 가능한 작업 트리 삭제는 제외합니다.
4. `psql`, `sqlcmd`, DataGrip, tabularis, MCP SQL 필드로 보내는 파괴적 데이터베이스 문장
5. 원격 인프라 삭제: `kubectl`, `oc`, `helm`, `az`, `terraform`, `tofu`, `aws`, `gcloud`, `gsutil`의 파괴적 동사
   (`delete`, `drain`, `uninstall`, `destroy`, `purge`, `terminate` 등), `--` 앞의 `--force`와 `--prune`,
   `kubectl`·`oc` `exec` 안의 파괴적 명령, 파괴적 `gh` 호출
6. 패키지 게시: `npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`의 `publish`, `twine upload`, `gem push`
7. 원격 엔진을 대상으로 한 `docker`·`podman`의 삭제: `rm`, `rmi`, `prune`, `compose down -v`, `exec` 안의 파괴적 명령.
   DELETE 같은 파괴적 메서드를 쓴 `curl`. 이름에 삭제 단어가 든 MCP 도구와 action
8. 샌드박스 보호 없는 Codex 실행
9. 가드가 분류하지 못한 호출과 텍스트에 파괴적 작업이 있는 분류 불가 호출(스크립트와 실행형 도구의 코드 입력 포함)

## 로컬 범위 예외

로컬 범위 규칙은 버려도 되거나 복구할 수 있는 로컬 작업을 매번 묻는 목록에서 제외합니다.

- **임시 루트**는 `/tmp`, `/private/tmp`, `/var/folders`, `/private/var/folders`, `$TMPDIR`, `~/.cache`,
  Claude Code 작업 폴더 `~/.claude/jobs/<id>/tmp`입니다. 임시 루트 안의 재귀 삭제는 통과합니다.
  리다이렉션(`>`, `>>`, heredoc), `mkdir`, `touch`, `tee`, `cp`·`mv`의 목적지는 심볼릭 링크를 푼 뒤
  모든 목적지가 임시 루트 안에 있으면 통과합니다. 원본은 어디에 있어도 됩니다. 다만 기존 폴더로 `cp`·`mv`할 때는
  `<folder>/<source name>`으로 판단하므로 그 위치의 심볼릭 링크가 루트 밖으로 나가거나 원본 이름을 알 수 없으면
  (glob이나 변수) 이 규칙을 적용하지 않습니다. 명령 전체가 이런 쓰기와 `cat`, `echo`, `ls`, `cd` 같은
  무해한 명령 몇 개로만 이루어지면 세션 승인 없이 Claude Code 자체 권한 프롬프트에 허용으로 응답합니다.
  `./README.md`처럼 임시 루트 안임을 증명할 수 없는 목적지는 기존 절차를 따릅니다.
  그곳에 쓰는 스크립트는 여전히 쓰기입니다.
- **복구 가능한 작업 트리 삭제**: 모든 대상이 명령이 실행되는 폴더가 속한 Git 작업 트리 안에 있고, Git이 각 대상을
  변경 사항(staged, unstaged, untracked)이 없는 추적 대상이거나 추적되지 않고 무시된(`git check-ignore`) 대상으로
  보고하면 재귀 `rm`은 세션 쓰기이며 "Recursive removal of tracked files" 또는 "Recursive removal of ignored files"로
  표시합니다. Git은 추적되지 않은 파일 보고와 무시 설정을 명령줄에서 강제한 채 실행하므로 저장소 설정으로 파일을 숨길 수
  없습니다. 작업 트리 루트, `.git`, 심볼릭 링크, 존재하지 않는 경로, `assume-unchanged`나 `skip-worktree` 항목,
  Git이 무시하지 않는 추적되지 않은 파일,
  같은 텍스트 앞쪽에서 파일을 바꿀 수 있는 명령(반복문 머리는 포함하고 단순한 `[ ... ]` 검사는 제외), 저장소를 바꿀 수 있는
  Git 변수, Git 실패나 시간 초과는 계속 매번 묻습니다.
- **로컬 컨테이너 엔진**: 엔진이 로컬이면 `docker`·`podman`의 삭제·정리(`rm`, `rmi`,
  `container`, `image`, `volume`, `network`의 `rm`·`prune`, `system prune`, `-v` 유무와 관계없는
  `compose down`)와 파일을 지우는 `exec` 명령은 세션 쓰기입니다. 하위 명령 앞에 `--host`, `-H`,
  `--remote`, `-r`, `--url`, `--connection`, `--identity` 옵션이 있으면 엔진은 원격입니다.
  `-Htcp://h`, `--remote=true` 같은 모든 표기를 포함합니다. `CONTAINER_HOST`나 `CONTAINER_CONNECTION`이
  설정되어 있거나, `DOCKER_HOST`가 `unix://` 소켓, 경로, 단독 호스트 `localhost`, `127.0.0.1`, `::1`
  이외의 값일 때도 원격입니다. 이름이 있는 Docker 컨텍스트는 `--context`·`-c`, 그다음 `DOCKER_CONTEXT`,
  그다음 Docker 설정의 `currentContext`에서 가져옵니다. 설정은 `--config`, `DOCKER_CONFIG`,
  `~/.docker/config.json` 순서로 찾습니다. 이 컨텍스트는
  `<config dir>/contexts/meta/<sha256 of the name>/meta.json`의 `Endpoints.docker.Host`가
  `unix://`나 `npipe://`로 시작할 때만 로컬이므로 Docker Desktop의 `desktop-linux`는 로컬입니다.
  메타 파일이 없거나 읽을 수 없거나 형식이 잘못된 경우, 호스트가 없는 경우, `tcp://`·`ssh://` 같은 다른 스킴이면
  원격입니다. `default` 컨텍스트는 로컬입니다. podman은 `containers.conf`(`CONTAINERS_CONF`,
  사용자·시스템 파일과 각각의 `.d` 폴더)에 `active_service`나 `remote = true`가 설정되어 있거나,
  저장된 시스템 연결 기본값이 있으면 원격이며, 해당 설정을 읽을 수 없을 때도 원격입니다.
  원격 엔진에는 계속 매번 묻습니다. 함수, 변수, `eval`, `sh -c` 텍스트의 파괴적 단어가 로컬
  `docker`·`podman` 삭제만 가리키는 경우도 세션 쓰기입니다.
- **lease로 보호된 푸시**: 다음 조건을 모두 충족하는 `git push`는 매번 묻지 않고 세션 쓰기로 처리합니다.
  강제 관련 플래그는 `--force-with-lease`(단독, `=<ref>`, `=<ref>:<expect>`)와 `--force-if-includes`만 있어야 합니다.
  원격 이름을 명시해야 하며 `upstream`은 제외합니다. URL, 경로, git이 읽을 수 없는 원격에는 계속 매번 묻습니다.
  모든 대상 브랜치를 명시해야 하며 `main`, `master`, `develop`, `trunk`는 제외합니다.
  `git symbolic-ref refs/remotes/<remote>/HEAD`를 읽을 수 있으면 해당 원격의 HEAD 브랜치도 제외합니다.
  대상은 `src:dst`, `dst` 또는 lease ref에서 가져옵니다. `HEAD`, `@`, 비어 있거나 암묵적인 대상, glob,
  `refs/heads/` 이외의 `refs/` 이름에는 계속 매번 묻습니다. `--force`, `-f`, `--delete`, `-d`, `--mirror`,
  `--prune`, `--all`, `--tags`, `+`·`:dst` refspec, 알 수 없는 옵션, `-C` 이외의 전역 옵션,
  대상을 바꾸는 `GIT_*` 변수, 컨테이너 안의 `exec`도 계속 매번 묻습니다.
  예를 들어 `git push --force-with-lease origin feature/ABC-1`은 세션 쓰기이고,
  `git push --force-with-lease origin main`은 매번 묻습니다.
- **변경 없는 추적 트리**: 저장소에서 `git status --porcelain --untracked-files=no`가 3초 안에
  아무것도 출력하지 않으면 `git reset --hard`, `git checkout -f`, `git checkout .`, `git restore .`은
  세션 쓰기입니다. `-C`가 지정한 경로도 따릅니다. 다음 경우에는 계속 매번 묻습니다. 오류나 시간 초과가 발생한 경우,
  `-C`와 무해한 `--no-pager`, `-P`, `--no-optional-locks`, `--paginate`, `-p` 이외의 전역 옵션이 있는 경우
  (`-c`, `--config-env`, `--git-dir`, `--work-tree`, `--namespace`, `--bare` 모두 해당),
  또는 다음 예외 이외의 `GIT_*` 변수가 있는 경우입니다. 예외는 `GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`,
  `GIT_PAGER`, `GIT_TERMINAL_PROMPT`, `GIT_ASKPASS`, `GIT_SSH`, `GIT_SSH_COMMAND`, `GIT_TRACE*`,
  `GIT_PROGRESS_DELAY`, `GIT_FLUSH`, `GIT_MERGE_AUTOEDIT`입니다. 세션이 그대로 물려받은 `GIT_CONFIG_COUNT` 항목이
  일부 터미널이 내보내는 것처럼 `credential.interactive`나 `credential.guiPrompt`만 설정하면 이것도 예외입니다.
  명령이 `GIT_CONFIG_*` 변수를 직접 설정하면 여전히 해당합니다.
  `kubectl`·`oc`·`docker`·`podman`의 `exec` 안의 명령에도 매번 묻습니다.
  같은 명령의 앞선 세그먼트 중 파일 출력 없는 단순 읽기가 아닌 것이 있어도 매번 묻습니다.
  예를 들어 `printf x >> a; git reset --hard`는 매번 묻습니다.

## 승인 문구와 CLI 분류

승인이 필요한 호출은 응답 언어로 한 줄, 100자 이내로 보입니다. Claude Code는 `language` 설정에서 언어를 가져오며, 설정이
없으면 영어입니다. Codex는 `HEI5ENBUG_LANGUAGE`를 쓰고, 없으면 응답 언어 가드의 `HEI5ENBUG_RESPONSE_LANGUAGE`를 쓰며 그
기본값은 한국어입니다. 줄에 맞지 않는 설명은 줄이되 최소 20자는 남깁니다.
복합 호출은 설명을 모두 남기되 각각 40자로 줄이며 줄 길이는 제한하지 않습니다. Claude는 다음 줄을 보여 줍니다.

| 종류 | 한국어 | 영어 |
|---|---|---|
| 쓰기 | `쓰기 승인: kubectl apply on (default) dev/web. 한 번 승인하면 이 세션의 쓰기는 더 묻지 않습니다.` | `Write: kubectl apply on (default) dev/web. Approve once; later writes in this session will not ask.` |
| 매번 | `매번 승인: git push --force (origin main).` | `Asks every time: git push --force (origin main).` |
| 민감 읽기 | `민감 조회 승인: cat .env (값이 노출될 수 있음). 한 번 승인하면 이 세션의 민감 조회는 더 묻지 않습니다.` | `Sensitive read: cat .env (may show a value). Later ones in this session won't ask.` |

다른 세션 승인도 함께 주는 호출의 줄 끝에는 "Also approves writes for this session."처럼 그 승인을 밝히는 짧은 문장이 붙습니다.
요청은 `--why` 문구를 설명으로 보여 줍니다.

| CLI | 읽기 | 비밀 (거부) | 민감 (세션) | 매번 | 프롬프트의 대상 |
|---|---|---|---|---|---|
| `kubectl`, `oc` | `get`, `describe`, `logs`, `diff`, `config view`, `config get-contexts`, `config current-context`, `--dry-run=client` 또는 `--dry-run=server`가 붙은 모든 호출 | 값을 출력하는 출력 형식이 붙은 `get secret`(이름, 네임스페이스, UID, 레이블, 소유자 참조, finalizer, 타임스탬프, 리소스 버전, `type`, `kind`, `apiVersion`, `immutable`만 읽는 `jsonpath` 또는 `custom-columns` 템플릿은 읽기입니다. `annotations`에는 마지막으로 적용한 매니페스트가 들어갈 수 있으므로 계속 비밀로 분류합니다), `secrets` 경로의 `get --raw`, `config view --raw`, `create token` | `exec ... env` 또는 `printenv` | `delete`, `drain`, `--` 앞의 `--force`·`--prune`, `exec` 안의 파괴적 명령 | kubeconfig, 그다음 컨텍스트 / 네임스페이스 |
| `helm` | `list`, `status`, `get notes`, `repo list` | 없음 | `get all`, `get manifest`, `get values` | `uninstall` | kubeconfig, 그다음 컨텍스트 / 네임스페이스 |
| `az` | `list`, `show`, `exists`, `query`, `query-*`, `version`; `--resource` 없이 `https://management.azure.com`이나 풀 수 없는 변수 URL에 보내는 `rest` GET | `keyvault secret show`와 `download`, `list-keys`, `account get-access-token`, Key Vault `/secrets`·`/keys` URL에 대한 `rest` GET | 없음 | `delete`, `purge`, `rest` DELETE | 구독 / 리소스 그룹 |
| `terraform`, `tofu` | `plan`, `show`, `validate`, `state list`, `fmt -check`, `-json`·`-raw` 없는 `output` | 없음 | `state show`, `state pull`, `output -json`, `output -raw` | `destroy`, `apply -destroy`, `state rm` | 디렉터리 : 워크스페이스 |
| `aws` | `describe-*`, `list-*`, 비밀 조회가 아닌 `get-*`, `s3 ls` | `secretsmanager get-secret-value`와 `batch-get-secret-value`, `--with-decryption`이 붙은 `ssm get-parameter*`, `kms decrypt` | 없음 | `delete-*`, `terminate-*`, `s3 rm`, `s3 sync --delete` | 프로파일 / 리전 |
| `gcloud`, `gsutil` | 명령 경로에서 처음 나오는 동사가 `list`, `describe`, `get-*`, `ls`, `cat` | `secrets versions access`, `auth print-access-token` | 없음 | `delete`, `gsutil rm`, `gsutil rb` | 프로젝트 |
| `docker`, `podman` | `ps`, `images`, `logs`, `<object> ls` | 없음 | `inspect`, `exec ... env` 또는 `printenv` | 원격 엔진 대상: `rm`, `rmi`, `prune`, `compose down -v`, `exec` 안의 파괴적 명령(로컬 엔진: 세션 쓰기) | 컨텍스트 |
| `psql`, `sqlcmd` | 읽기인 쿼리. 가드가 다루는 `psql` 읽기는 `default_transaction_read_only=on`과 `statement_timeout=60000`으로 실행됩니다. | 없음 | 없음 | `delete`·`drop`·`truncate`가 이름으로 든 텍스트와 `DO`·`EXEC`·`EXECUTE`·`CALL`로 시작하는 문장 등을 포함한 파괴적 SQL | 호스트 / 데이터베이스 |
| `curl` | 데이터·폼·업로드·JSON 플래그가 없는 GET/HEAD | 없음 | argv의 자격 증명(`-u`, `--user`, `Authorization` 헤더) | DELETE 같은 파괴적 메서드 | 메서드 / 스킴과 호스트 |
| `kustomize` | 모든 호출 | 없음 | 없음 | 없음 | 없음 |
| `mysql`, `mongosh`, `redis-cli` | 없음. 명시적인 로컬 호스트는 통과 | 없음 | 없음 | 파괴적 작업이 든 분류 불가 텍스트 | 없음 |
| `git` | `status`, `show`, `log`, `diff`, `ls-remote`, `ls-tree`, `ls-files`, `cat-file`, `rev-list`, `show-ref`, `for-each-ref`, `merge-base`, `blame`, `shortlog`, `diff-tree`, `describe`, `rev-parse`, 태그 목록과 검증 | 없음 | 없음 | 강제·삭제·미러·prune 푸시(lease로 보호된 기능 브랜치 푸시는 세션 쓰기), dry run 없는 강제 `clean`, `stash drop`·`stash clear`. 추적 트리에 변경이 없을 때(이때는 세션 쓰기)를 제외한 `reset --hard`, 강제 checkout이나 `.` checkout, 인덱스만 복원하는 경우를 제외한 `.`·`:/` restore | 명령 |
| `gh` | `view`, `list`, `ls`, `status`, `checks`, `diff`, `search`, `watch`, `browse` 같은 읽기 동사, `auth status`, `config get`/`list`, 버전·도움말, `api` GET과 인라인 GraphQL query | `auth token` | 없음 | 모든 영역의 `delete`, `api` DELETE | 명령 |

그 밖에 가드가 다루는 비파괴적 CLI 작업은 세션 쓰기 승인을 사용합니다. 로컬 `kubectl`·`oc` `config` 변경(`use-context`,
`delete-context` 등), `helm repo remove`, 로컬 git 태그 삭제·강제 변경도 여기에 해당합니다. 원격 SQL 클라이언트의
파일·표준 입력·대화형 사용은 분류 불가 쓰기이며, 파괴적 텍스트가 있으면 매번 묻는 목록에 들어갑니다. `psql`, `mysql`,
`redis-cli`, `mongosh`에서 명시적인 로컬 호스트(`localhost`, `127.0.0.1`, `::1`, 소켓 경로)는 통과합니다.
`gh api`의 데이터 플래그와 `--input`은 명시적인 GET으로 덮어쓰지 않는 한 쓰기를 뜻합니다.
인라인 GraphQL 필드는 `#` 주석과 앞쪽 공백을 제거한 뒤 `query`나 `{`로 시작하고 `mutation` 단어가 없어야 읽기입니다.
mutation과 쿼리 파일은 쓰기입니다. 알려지지 않은 `gh` 동작도 쓰기이며, `gh pr checkout`과 `gh repo clone`은
호스트 판단에 맡깁니다. git 태그 생성과 푸시, 릴리스 생성·편집·업로드 같은 `gh` 쓰기는 양쪽 호스트에서 같은 승인을 사용합니다.

패키지 게시(`npm`, `pnpm`, `yarn`, `uv`, `poetry`, `cargo`, `twine upload`, `gem push`)는
게시 하위 명령 앞에 옵션이 있어도 매번 묻습니다.
재귀 `rm`은 세션 폴더와 그 상위 폴더, 홈 폴더, `/`, `.git`과 그 내용, 풀 수 없는 대상 등
보호 경로나 외부 경로에 대해 매번 묻습니다. 그 밖에 세션 폴더나 임시 루트(로컬 범위 규칙 참고) 안에서의 삭제는 통과합니다.
대상이 정확히 `$(mktemp -d ...)` 또는 백틱 치환이거나 `${TMPDIR:-<default>}`로 시작하면, 먼저 임시 루트(`TMPDIR`가
있으면 그 값, 없으면 기본값)로 풀고 다른 경로와 똑같이 검사합니다. 그래서 홈 폴더, 세션 폴더, `.git` 차단은 그대로 적용됩니다.
같은 명령 텍스트에서 앞서 대입한 변수는 값이 정적 단어 하나(리터럴, `~`, `$HOME`, `$TMPDIR`, `${TMPDIR:-<default>}`,
또는 이미 푼 다른 변수)이면 풉니다. 텍스트의 모든 경로가 거치는 `if`, `case`, `{ }`, `( )` 본문 안의 대입과
`for` 반복문의 단어도 포함합니다. 삭제는 가능한 모든 값에 대해 검사하고 가장 엄격한 결과를 따릅니다.
`&&`나 `||` 목록에서 앞선 명령이 성공하거나 실패할 때만 실행되는 대입은 조건부입니다. 그 목록에서 뒤따르는 명령은 앞의 연결이
모두 `&&`일 때만 새 값만 보고, `||` 뒤와 목록 뒤(`;`, 줄바꿈, `&` 다음)에서는 새 값과 이전 값을 함께 봅니다. 환경이 제공하지
않는 변수의 이전 값은 빈 문자열입니다. 따옴표 없는 참조는 공백에서 나뉘므로 값의 각 단어를 따로 대상으로 검사합니다.
따옴표 없이 빈 값으로 풀리는 대상은 뺍니다. 따옴표를 친 빈 대상은 아무것도 지우지 않습니다. 다만 빈 값 때문에 `$D/y`가
`/y`가 되는 것처럼 대상이 세션 폴더와 임시 루트 밖의 경로로 바뀌면 계속 묻습니다. 뒤따르는 `cd`는 상대 대상의 기준만 바꿉니다.
명령 치환, 백틱, `read`, 산술, 알 수 없는 변수, `set --`, `shift`, 일부 경로에서만 대입한 값은 풀지 못한 채 매번 묻습니다.
가드가 명령이 실행하는 셸 스크립트를 읽을 때는 스크립트를 하나의 텍스트로 판단하므로 한 줄에서 대입한 변수를 다음 줄에서 풉니다.
그 스크립트의 `$0`, 폴더 관용구 `$(dirname "$0")`, `$(cd "$(dirname "$0")" && pwd)`, `${BASH_SOURCE[0]%/*}`,
`$1`부터 `$9`는 각각 스크립트 경로, 스크립트 폴더, 호출의 리터럴 인자로 풀며, 인자가 반복문 변수이면 가능한 모든 값으로 풉니다.
스크립트 경로는 명령이 쓴 경로를 셸처럼 심볼릭 링크를 풀지 않고 절대 경로로만 만든 것입니다.
`kubectl`·`oc`·`docker`·`podman`의 `exec` 안의 명령에도 일반 분류기를 적용합니다.
파괴적 명령은 매번 묻되, 로컬 `docker`·`podman` 컨테이너 안의 파일 삭제는 세션 쓰기입니다.
비밀 출력은 차단하며, 나머지 `exec` 호출은 쓰기입니다.
샌드박스 우회 플래그나 설정 재정의를 포함해 `danger-full-access`를 쓰는 모든 `codex` 호출은 매번 묻습니다.
`codex exec` 또는 `e`에서 하위 명령 앞뒤의 `--add-dir`·`-C`·`--cd`, 또는 `role_runner.py --add-dir`로
worker가 세션 폴더 밖에 접근하면 쓰기입니다.

## 셸과 스크립트 분류

쓰기는 `<cli>:<subcommand>@<target>`로 나타내며 subcommand는 첫 번째 플래그 앞의 단어들입니다. 프롬프트에는
`<cli> <subcommand> on <target>`으로 보이고, `write:session` 승인 하나가 이런 쓰기를 모두 허용합니다.
`kubectl`, `oc`, `helm`의 대상은 kubeconfig(`--kubeconfig`, 그다음 `KUBECONFIG`, 없으면 `(default)`)와
컨텍스트 및 네임스페이스입니다. 컨텍스트를 주지 않으면 같은 kubeconfig로 현재 컨텍스트를 읽습니다.
그 밖에 분석할 수 있는 하위 명령은 모두 쓰기이므로 `kubectl apply`와 `helm upgrade`는 세션에서 첫 쓰기가 승인될 때까지만 묻습니다.
`$(...)`나 백틱 치환의 본문은 별도 명령처럼 분류해 호출에 합칩니다. 명령 동사가 확장되지 않은 변수인 치환은 분류 불가 쓰기이며,
파괴적 작업이 있으면 매번 묻습니다. `eval`, `xargs`, `c`가 든 플래그 묶음을 쓴 `sh -c` 안의 명령도 분류합니다.
영역 자체가 비밀을 출력하면 명령 전체를 거부합니다. 가드가 다루는 명령의 heredoc은 분류 불가 쓰기이며,
파괴적 작업이 있으면 매번 묻습니다. heredoc 본문은 받는 명령이 `cat`, `tee`, `echo`, `printf`, `head`, `tail`, `wc`,
`sort`, `uniq`, `cut`, `tr`, `base64`, `xxd`, `od`, `grep`, `egrep`, `fgrep`, `rg`, `jq`, `column`, `fold`,
`fmt`, `nl`, `tac`, `rev`, `cmp`, `diff`, `git`, `gh`이고 출력이 뒤로 파이프되지 않으며,
쓰는 파일을 같은 명령 텍스트 뒤에서 `bash`, `sh`, `zsh`, `source`로 실행하지 않으면 데이터로 보고 검사하지 않습니다.
파일 확장자는 이 규칙에 영향을 주지 않습니다. 그 밖의 수신 명령이면 본문을 계속 검사합니다.
따옴표 없는 구분자 때문에 셸이 실행하는 치환만 계속 분류합니다. 프로그램 단어가 치환이나 확장되지 않은 변수에서 오면서
가드가 다루는 CLI를 언급하는 세그먼트는 분류 불가입니다. `command -v` 조회는 아무것도 실행하지 않으므로 분류하지 않습니다.

복합 명령은 전체로 판단합니다. 비밀 세그먼트가 있으면 거부합니다. 매번 묻는 목록에 드는 세그먼트가 하나라도 있으면
매번 묻고, 그 승인은 나머지 세그먼트가 필요로 하는 세션 승인도 함께 줍니다. 그 밖에 쓰기가 하나라도 있으면 검증되지 않은
세그먼트나 파일 출력이 있어도 명령 전체를 쓰기로 봅니다. 가드가 다루는 읽기는 나머지 세그먼트가 `grep`, `head`, `jq` 같은 필터이고,
출력 리다이렉션이 `/dev/null` 또는 `2>&1`로만 가는 경우에만 읽기로 남습니다.
`sudo`, `env`, `nice`, `time` 같은 래퍼는 옵션과 함께 건너뛰고 나서 실행 파일을 읽습니다.
쓰기와 매번 묻는 호출의 대상은 플래그나 환경 변수에서 가져옵니다. 둘 다 없으면 그 호출에 대해서만
`kubectl config current-context`와 `az account show`를 3초 제한으로 실행합니다.

`psql` 읽기는 `PGOPTIONS`에 `-c default_transaction_read_only=on -c statement_timeout=60000`을 더한
서브셸에서 실행하도록 다시 써서, 가드의 읽기 검사가 함수 호출을 놓치더라도 서버가 쓰기를 거부하게 하고 이 옵션이 뒤따르는 명령에 남지 않게 합니다.

가드는 `bash`, `sh`, `zsh`, `./`, `source`, `.`로 실행하는 셸 파일과 Python 파일,
선택한 또는 기본 타깃과 한 단계 선행 타깃의 Makefile 레시피, `npm`·`pnpm`·`yarn run <name>`이 가리키는
`package.json` 스크립트 텍스트를 읽습니다. 파일 경로는 이벤트의 `cwd` 기준이며 크기 제한은 256 KiB입니다.
같은 명령 텍스트 앞부분에서 `;`, `&&`, 줄바꿈으로 구분한 일반 `NAME=value` 문은 뒤의 단순 명령에 치환됩니다.
`for ... do ... done` 루프 본문도 포함하며, 따옴표 없는 확장에는 sh 단어 분할을 적용합니다.
값이 명령 치환 없는 정적 단어 하나이고(`$(mktemp -d ...)`는 삭제 대상처럼 풉니다), 조건 없는 대입일 때만 적용합니다.
즉 `export`가 아니고 괄호, 블록, 함수, 중괄호 그룹, 파이프, 백그라운드 안에 없어야 하며,
왼쪽이 대입만으로 이루어진 경우를 제외하면 `||`·`&&` 뒤에도 없어야 합니다.
이런 문맥 안의 대입은 그 뒤에서 해당 이름을 알 수 없는 상태로 만듭니다.
`read`, `export`, `for NAME in` 같은 명령은 치환을 해제합니다.
단순 명령이 뒤따르는 `xargs`는 입력을 알 수 없는 피연산자 하나로 보고 해당 세그먼트의 대입을 적용해 그 명령으로 분류합니다.
`DOCKER_HOST=ssh://h xargs docker rm`은 매번 묻습니다. 읽기나 `cat`·`grep` 같은 파일 읽기 명령은
알 수 없는 피연산자가 보호 파일을 가리킬 수 있으므로 민감 읽기가 되며, `xargs rm -rf`는 매번 묻습니다.
셸, `eval`, 중첩된 `xargs`, 알 수 없는 옵션, 명령 이름의 자리표시자는 기존의 불투명 처리를 유지합니다.
`cd <dir>`는 현재 셸에서 조건 없이 실행될 때만, 즉 괄호 밖에서 앞에 아무것도 없거나 `;`가 있고
뒤에 아무것도 없거나 `;` 또는 `&&`가 있을 때만 뒤따르는 세그먼트의 기준 경로를 옮깁니다.
앞선 독립 대입이 정한 `$NAME`, `${NAME}`은 경로에서 확장하지만, 접두 대입(`NAME=value cmd`)은 자기 명령의 인자를
확장하지 않습니다. 대입하지 않은 변수는 스크립트를 읽을 수 없게 하므로 분류 불가입니다.
셸의 각 줄과 Makefile 레시피에는 CLI 분류기를 적용합니다. Python 스크립트 파일이나 `python3 -` heredoc의 구문 트리가
읽기 전용임을 증명할 수 있으면 읽기입니다. 목록에 있는 표준 모듈만 가져오고, 프로세스·네트워크·환경·동적 실행이나
파일 변경 함수(`replace`, `remove`, `touch`, `mkdir` 이름 포함)를 호출하지 않아야 합니다.
파일은 리터럴 읽기 모드로만 열고, 자격 증명으로 보이는 경로나 단어를 언급하지 않아야 합니다.
`open` 함수에 연결된 모든 이름을 검사하므로 `from io import open as f`도 예외가 아닙니다.
검사가 판단하지 못하는 경우는 기존 결과를 유지합니다. 보호 파일을 인자나 옵션 값(`--file=.env`)으로 전달할 때도 그렇습니다.
`-c` 표기가 `-c code`, `-ccode`, `-Ic code` 중 무엇이든 heredoc이 아닌 인라인 코드를 분류합니다.
Python 인라인 코드, heredoc, 표준 입력 파일, 스크립트 파일은
프로세스를 실행하거나 클라우드·데이터베이스 SDK를 가져오면 쓰기입니다. 키워드 인자를 포함한 리터럴 프로세스 명령은 분류합니다.
파괴적 프로세스 명령, 파괴적 SDK 호출 이름, 프로세스를 실행하거나 SDK를 가져온 Python 안의 파괴적 텍스트는 매번 묻습니다.
나머지 Python은 문자열에 CLI 명령이 있어도 통과하지만(`python3 -c` 코드는 읽기가 되지 않습니다),
명시적인 `--execute`가 있으면 쓰기입니다. 문자열 리터럴을 받는 `exec`·`eval`은 그 코드를 제자리에 직접 쓴 것처럼 실행하는
코드로 판정하므로, 해롭지 않은 리터럴은 통과하고 자격 증명을 읽거나 보호된 위치에 쓰는 리터럴은 그 판정을 받습니다. 네임스페이스 인자가 상수로 된 딕셔너리 리터럴이면 그 값을 코드가 읽는
이름에 넘겨 주고, `globals()`나 변수처럼 다른 네임스페이스는 풀지 않고 세션 쓰기를 유지합니다.
변수, `input()`, 표준 입력을 받는 `exec`·`eval`은 이전 결과인 세션 쓰기를 유지하며, 스크립트의 나머지 부분에 대한 자격 증명·
설치된 코드·보호된 위치 판정도 그대로 받습니다. Node와 그 밖의 셸·Python이 아닌 실행 파일은 통과합니다.
읽기는 승인 없이 실행하고 쓰기는 세션 쓰기 승인이 필요합니다. 파괴·강제·비밀 호출은 기존 규칙을 따릅니다.
읽을 수 없거나 더 큰 스크립트 파일은 분류 불가입니다. 검사한 셸 스크립트가 대상 CLI를 언급하거나
`boto3`, `azure`, `kubernetes`, `psycopg`, `psycopg2`, `pymysql`, `sqlalchemy`, `pymongo`, `redis`,
`google.cloud`를 가져오지만 호출을 분류하지 못한 경우도 분류 불가입니다. 이런 호출은 텍스트에 파괴적 작업이 없으면 쓰기이고,
있으면 매번 묻습니다. 이들 중 아무것도 언급하지 않는 스크립트는 통과합니다. 플러그인 자체의
`python3 <plugin root>/scripts/host_settings.py check`는 읽기, `apply`는 세션 쓰기입니다. 단 스크립트가 이 가드의
플러그인 루트에 속하고 앞에 인터프리터 옵션이 없을 때만 그렇습니다.

## MCP와 데이터베이스 호출

MCP 도구 이름은 `_`, `-`, camelCase 경계에서 나뉩니다. 이름의 파괴적 단어는 매번 묻습니다.
문자열 필드 `sql`, `statement`, `queryText`와, SQL 문장처럼 시작하는 `query` 필드(검색어는 제외)에는 DataGrip SQL
분류기를 적용합니다. 읽기는 승인 없이, 파괴적 문장은 매번 승인 후 실행하고, 나머지 SQL은 세션 쓰기입니다.
실행 이름 단어(`repl`, `exec`, `execute`, `eval`, `run`, `code`, `script`, `command`)는 코드 입력을 `language` 필드나
생김새에 따라 명령 또는 Python 스크립트처럼 분류합니다. 비밀·금지 결과는 평소처럼 거부하고, 매번 묻는 결과는 매번 묻고,
그 밖의 경우는 코드가 없는 도구를 포함해 세션 쓰기입니다. 명시적인 `action` 입력은 일반 이름 동사보다 우선합니다.
파괴적 동작은 매번 묻고, 파괴적 SQL 필드는 그 밖의 동작보다 우선합니다.
SQL이 없으면 읽기 동작은 읽기, 쓰기 동작은 쓰기입니다.
이 입력이 없으면 읽기 동사로 시작하는 이름은 뒤에 쓰기 단어가 있어도 읽기이고, `getjiraissue`처럼 소문자 한 덩어리로 쓴 이름은
읽기 동사로 시작하고 뒤에 쓰기·삭제 단어가 없으면 읽기입니다.
그 밖에는 쓰기 단어가 읽기 단어보다 우선하고, 아는 동사가 없으면 쓰기입니다.
세션 쓰기 승인 하나로 DataGrip과 tabularis 쓰기를 포함한 해당 세션의 모든 비파괴적 MCP 쓰기가 허용됩니다.

`mcp__tabularis__run_query`의 `connection_id`는 tabularis의 `connections.json`에서 ID나 이름으로 찾습니다.
설정 폴더는 macOS의 `~/Library/Application Support/tabularis`, Linux의 `$XDG_CONFIG_HOME/tabularis` 또는
`~/.config/tabularis`, Windows의 `%APPDATA%\tabularis`입니다. 테스트에서는 `HEI5ENBUG_TABULARIS_DIR`로 바꿉니다.
가드는 `id`, `name`, `params.driver`만 추출하며 다른 연결 필드나 비밀번호는 출력하지 않습니다.
`postgresql`에는 PostgreSQL 분류기를, `sqlserver`·`sqlserver-entra`에는 SQL Server 분류기를 적용합니다.
운영이 아닌 연결의 읽기는 승인 없이 실행하고, 비파괴적인 쓰기는 세션 쓰기입니다. 다른 드라이버,
알 수 없는 연결, 읽을 수 없는 파일, 해석할 수 없는 쿼리 텍스트는 세션 쓰기 승인을 사용합니다.
코드의 `delete`·`drop`·`truncate`(리터럴, 주석, 따옴표 식별자 안은 제외)와 SQL 분류기가 파괴적으로 판단한 문장은 매번 묻습니다.
`DO`·`EXEC`·`EXECUTE`·`CALL`로 시작하는 문장도 여기에 포함됩니다. 다만 [DataGrip 쿼리 가드](guards.ko.md#datagrip-쿼리-가드)에서 설명한
운영이 아닌 PostgreSQL 연결의 대상 지정
`DELETE`와 안전한 `DO`는 세션 쓰기입니다.
이런 쿼리는 `sql:always:tabularis:<id>:<digest>` 키를 씁니다.
다른 tabularis 도구는 기존 이름 규칙을 따릅니다.

### 운영 데이터베이스 읽기

`run_query`와 DataGrip `execute_sql_query`에서 연결 이름을 대소문자 경계, 공백, `_`, `-`, `.`, 괄호로 나눈 단어에
`dev`, `develop`, `development`, `test`, `testing`, `qa`, `stg`, `stage`, `staging`, `sandbox`, `local`,
`demo` 중 하나가 있거나
이름에 `개발`, `테스트`, `스테이징`, `검증`, `로컬`이 들어 있고, `prod`, `production`, `prd`, `live` 단어와 `운영`이 없으면
운영이 아닙니다. 그 밖의 모든 연결은 운영이며, 알 수 없는 연결과 `승인`이 든 이름도 포함합니다.
- `ANALYZE`가 없는 PostgreSQL `EXPLAIN [(옵션)] <읽기>`는 어떤 연결에서도 읽기입니다. 운영 연결에서 성공하면 `PostToolUse` 훅이
  추정 비용과 행 수(JSON `Plan`의 `Total Cost`와 `Plan Rows`, 또는 텍스트 계획 첫 줄)를 호스트·세션·도구·연결·정확한 읽기 텍스트(앞뒤
  공백과 끝의 세미콜론만 뺀 것)별로 30분 동안 상태 파일에 기록합니다. 오류나 해석할 수 없는 결과는 기록하지 않습니다.
- 두 한도 이하인 기록이 있는 PostgreSQL 운영 읽기는 실행합니다. 기록이 없으면 먼저 실행할 `EXPLAIN (FORMAT JSON) <읽기>` 형식을 알려 주며
  거부하고, 한도를 넘거나 기록을 해석할 수 없으면 매번 묻습니다.
- SQL Server 운영 읽기는 계획 없이(두 도구 모두 SQL Server 예상 계획을 돌려줄 수 없습니다) 실행하며, `SET LOCK_TIMEOUT 5000;`과
  `SET DEADLOCK_PRIORITY LOW;` 접두가 항상 맨 앞에 붙습니다. 읽기가 `LOCK_TIMEOUT`을 0부터 한도 밖의 값으로 정하거나
  `DEADLOCK_PRIORITY`를 `LOW`나 -5 이하 정수가 아닌 값으로 정하면 매번 묻습니다. tabularis `limit`은 요청값(기본 100)과 최대 결과 행 수 중
  작은 값이 됩니다.
- 한도 기본값은 `postgres_max_cost` 10000, `max_estimated_rows` 100000, `max_result_rows` 1000, `sqlserver_lock_timeout_ms`
  5000입니다.
  `$XDG_CONFIG_HOME/hei5enbug-agent-setup/db-read-limits.json`(기본 `~/.config`)에
  `{"default": {...}, "connections": {"<연결 이름 또는 id>": {...}}}`를 둘 수 있고, 연결 항목은 키별로 default를 덮어씁니다.
  알 수 없는 키, 0 이하이거나 숫자가 아닌 값, 잘못된 파일은 무시합니다. 편집 도구나 셸로 이 파일이나 그 폴더를 바꾸면, 따옴표나
  이스케이프로 이름을 나눠도 매번 묻습니다. 그 폴더 안에서 대상을 풀 수 없는 쓰기도 묻습니다. 다른 곳에서 풀 수 없는 값으로 조립한
  경로는 잡지 못합니다.
- `approval_guard`를 끄면 아무것도 기록하지 않으므로 읽기를 막지 않습니다.

## 민감 조회

`curl`은 GET/HEAD 이외의 요청 메서드와 `-d`, `--data*`, `-F`, `--form`, `-T`, `--upload-file`, `--json`이 없으면
읽기입니다. 나머지는 `curl <METHOD> on <scheme://host>`로 보이는 쓰기이며, DELETE 같은 파괴적 메서드는 매번 묻습니다.
argv의 `-u`·`--user` 또는 `Authorization` 헤더는 메서드 자체의 결과에 민감 읽기 승인을 더합니다. 읽기는
`sensitive:session`이 필요하고, 쓰기는 `write:session`과 `sensitive:session`이 모두 필요하며, 파괴적 메서드는 여전히
매번 묻습니다. 프롬프트가 보여 주거나 대기 상태에 저장하는 설명은 `-u`·`--user` 값, `Authorization`·`Cookie`·`X-Api-Key`
헤더 값, URL의 사용자 정보, 키 이름이 비밀을 가리키는 `key=value`·`--key value` 쌍을 가립니다.

Claude `Read`와 Bash 읽기(`cat`, `less`, `head`, `tail`, `grep`, `rg`)가 `~/.kube/config`, 모든 `KUBECONFIG` 경로,
`~/.aws/credentials`, `~/.aws/config`, `~/.azure/**`, `~/.config/gcloud/**`, `~/.pgpass`, `~/.docker/config.json`,
`~/.netrc`, `~/.config/gh/hosts.yml`, `~/.ssh` 아래의 개인 키(`*.pub`, `known_hosts`, `config` 제외), `.env*` 파일을 읽으면
민감 호출입니다. 단 이름이 `.example`, `.sample`, `.template`, `.dist`로 끝나는 템플릿은 제외합니다. Python 코드도 같은 판정을
받습니다. heredoc, `-c` 코드, 스크립트가 이 파일을 열거나 읽거나 불러오면(경로는 `Path.home()`, `os.path.expanduser`,
`os.path.join`, f-string, 한 번만 대입한 이름으로 적을 수 있음), 또는 비밀로 보이는 이름의 환경변수 값
(`os.environ[...]`, `os.environ.get`, `os.getenv`)을 출력하거나 보내면 민감 읽기입니다. 그런 변수가 설정됐는지 검사하거나,
변수 이름만 나열하거나, 파일이 있는지만 확인하거나, 비밀 단어를 검색어로만 쓰면 묻지 않습니다. 필터 없는 `printenv`, 명령 없는 `env`,
`kubectl exec ... env|printenv`, `docker inspect`, `docker exec ... env`, `terraform`의 state와 JSON·raw 출력,
`helm get all`·`get manifest`·`get values`도 같습니다. 한 세션의 첫 민감 읽기는 한 번 묻고, 그 뒤로는 모든 민감 읽기를
세션이 끝날 때까지 실행합니다. 비밀 거부는 그대로여서, 비밀 값을 출력하는 명령은 승인한 뒤에도 거부합니다.
비밀이 아닌 변수 이름만 지정한 `printenv`는 읽기입니다. `env`나 `printenv`에 지원되는 `grep`·`rg` 필터를 적용하고,
일치한 이름 중 비밀 이름이 없으면 읽기입니다. 개수만 출력하는 경우도 읽기입니다. 변수 이름만 남기거나 값을 가리는
파이프도 읽기입니다. `cut -d= -f1`, `awk -F= '{print $1}'`, 이름에 고정한 패턴의 `grep -o`, `grep -c`, 첫 `=` 뒤를 전부
바꾸는 `sed` 치환이 그렇습니다. 확인할 수 없는 필터는 계속 민감 호출입니다.
지원되는 필터는 명령 목록 안에서도 같은 분류를 유지하며, 가드는 다른 요소의 결과와 기존 규칙대로 합칩니다.
다만 `export`, 변수 대입, `source`, `eval`처럼 목록이 먼저 환경을 바꿀 수 있으면 이 규칙을 적용하지 않습니다.
`python3 <plugin root>/skills/orca-plugin-refresh/scripts/orca_plugin_refresh.py status ...`는 해석된 스크립트가
이 가드의 플러그인 루트에 속하고 앞에 인터프리터 옵션이 없으면 읽기입니다.

## Claude Code 승인 절차

Claude Code에서는 승인이 필요한 호출에 위의 한 줄 이유를 담은 `PreToolUse` `ask`를 내고, 세션이 이미 승인한 호출에는
`allow`를 냅니다. 가드는 호스트 자체의 `PermissionRequest` 프롬프트에도 응답하므로 세션 쓰기 승인 하나가 그 프롬프트를 흡수합니다.

- 프로젝트 폴더(`CLAUDE_PROJECT_DIR`, 없으면 작업 폴더) 안이나 로컬 프로젝트·프로젝트·사용자 설정의
  `permissions.additionalDirectories` 안 경로에 대한 편집 도구(`Edit`, `Write`, `MultiEdit`, `NotebookEdit`)는 허용합니다.
  `$`가 든 경로, 가드의 상태 폴더, `.env*`와 자격 증명 파일 같은 보호 경로, 호스트의 보호 폴더와 파일(`.git`, `.claude`,
  `.vscode`, `.idea`, `.husky`, 셸 시작 파일, `.gitconfig`, `.gitmodules`, `.mcp.json`, `.claude.json`, `.ripgreprc`)이
  절대 경로 어디에든 있는 경로(허용된 폴더 자체가 그중 하나여도 마찬가지), 그 폴더 밖의 경로는 호스트에 맡깁니다.
- 가드가 다루지 않는 Bash 명령도 허용합니다. 단 `ssh`, `scp`, `rsync`, `sudo`, `su`, `doas`를 실행하거나, 재귀 삭제,
  강제 푸시, `dd of=` 쓰기, `mkfs` 실행을 하거나, 파괴적 작업이 이름으로 든 명령은 제외합니다. 가드가 분류했고 세션이 이미
  승인한 호출도 허용합니다. 읽기, 매번 묻는 호출, 그 밖의 경우에는 결정을 내지 않으므로 호스트가 결정합니다.
- 세션 쓰기 승인이 생기기 전에는 이런 첫 편집이 호스트의 네이티브 프롬프트를 보여 줍니다. 가드는 그 요청을 기록해 두고,
  편집이 끝나면 `write:session`을 기록합니다. 그래서 네이티브 프롬프트에서 승인한 첫 편집이 쓰기 승인을 주고, 이어지는
  `kubectl apply`는 다시 묻지 않습니다. 아래에서 설명하는 요청 한도를 다 쓰면 편집 프롬프트를 다시 보여 주는 대신 중단
  메시지와 함께 거부합니다.

한계: auto 모드에서는 가드가 허용한 호출을 호스트의 분류기가 여전히 거부할 수 있으며, 플러그인은 그 거부를 덮어쓰지
않습니다. `PermissionDenied` 훅의 `retry`는 모델에게 다시 시도해도 된다고 알릴 뿐이므로 훅으로도 되돌릴 수 없습니다.

## Codex 승인 절차

Codex에서는 `PreToolUse`가 물을 수 없으므로, 준비된 상태에서는 네이티브 승인 창이 승인을 맡습니다.

- 승인이 필요한 Bash 호출은 `PreToolUse`가 명령을 `<plugin root>/scripts/approve_wrapper.sh '<원래 명령>'`으로 바꿔
  허용합니다. 래퍼는 인자 하나에 `bash -c`를 실행하는 두 줄짜리 스크립트입니다. 플러그인 소유 규칙 파일
  `~/.codex/rules/hei5enbug.rules`에는 래퍼 경로에 대한 `decision="prompt"` `prefix_rule` 하나가 있어서, Codex가 원래
  명령이 보이는 승인 창을 띄웁니다. 가드는 분류하기 전에 래퍼를 풀므로 판정은 원래 명령의 판정이고, 파괴적인 안쪽 명령이
  든 래퍼 호출도 계속 매번 묻습니다. `sh`, `bash`, `zsh`가 평범한 단어 하나로 래퍼를 실행하는 호출은, 단독이든
  `env`, `command`, `exec`, `nohup` 같은 래퍼 뒤에 있든 그 단어의 텍스트로 분류합니다. 인자 개수가 다르거나
  `source`, 치환, `xargs`를 쓰는 것처럼 래퍼 경로를 이름으로 든 그 밖의 명령은 "Unrecognized approval wrapper call"로
  매번 묻고, 래퍼 파일 자체는 분류하지 않습니다.
- MCP 호출은 서버의 `default_tools_approval_mode = "prompt"`가 Codex 창을 띄우게 합니다. 읽기는 감싸지 않으며,
  `PermissionRequest`가 `allow`로 응답해 창을 건너뜁니다. DataGrip 쿼리도 `datagrip_guard.py`를 통해 같은 경로를 따릅니다.
  세션에 한 번 묻는 호출만 창을 쓰고, 파괴적인 도구와 쿼리처럼 매번 묻는 MCP·DataGrip 호출은 창이 준비돼 있어도 코드 방식을
  유지합니다. 창의 모드는 `config.toml`에서 오므로, 명령줄 옵션으로 MCP 서버를 `prompt`에서 다른 모드로 옮겨 시작한 세션은
  그 서버의 비파괴적 쓰기를 승인 없이 실행할 수 있습니다. `apply_patch` 편집은 Codex에 맡깁니다.
- `PermissionRequest`는 호출이 필요로 하는 승인을 세션이 이미 가졌으면 창을 건너뜁니다. 그렇지 않으면 창이 줄 승인을
  기록해 둡니다. Codex는 사용자가 진행을 고른 뒤에만 호출을 실행하므로, 호출이 끝나면 `PostToolUse`나
  `PostToolUseFailure`가 `write:session`이나 `sensitive:session`을 기록합니다. 매번 묻는 Bash 호출은 창에서 매번 묻고 승인을
  남기지 않습니다. 사용자가 거절해도 승인이 남지 않습니다.

네이티브 창에는 다음이 모두 필요합니다. 훅 이벤트가 권한 모드 `default`를 알리고, 세션이 역할 실행기의 자식이 아니고,
세션 ID를 쓸 수 있고, `rules/hei5enbug.rules`가 이 플러그인 버전이 쓰는 텍스트와 정확히 같고, MCP 도구의 승인 모드가
`~/.codex/config.toml`에서 `prompt`여야 합니다. 그렇지 않으면 아래 코드 방식이 적용됩니다. `codex exec`이나
권한 우회 실행처럼 창을 보여 줄 수 없는 세션, 자식 worker, [호스트 설정](configuration.ko.md#호스트-설정)이 규칙 파일이나 MCP 모드를 쓰기
전이 여기에 해당합니다. 신뢰하지 않은 Codex 훅은 가드를 전혀 실행하지 않으므로 어떤 방식도 적용되지 않습니다. 아래의
신뢰 경고를 참고하세요.

## 승인 코드와 요청 한도

쓰기 전에 묶음 승인을 요청할 수 있습니다.

```bash
python3 <plugin root>/scripts/approval_guard.py request --key write:session --why 'Deploy the requested change and update the issue'
```

`--key`는 `write:session`이나 `sensitive:session`을 받으며 여러 번 쓸 수 있습니다. Claude는 이유를 보여 주며 묻고,
질문한 호출이 `PostToolUse`나 `PostToolUseFailure`에 도달할 때만 세션 키를 기록합니다. 승인한 쓰기가 실패해도 세션 승인을
남깁니다. 기존 승인으로 허용한 호출은 그 승인을 다시 기록하지 않습니다. Codex는 묶음 코드 하나와 함께 거부하고,
사용자가 `승인 <CODE>`를 입력하거나 대기 요청이 하나일 때 `승인`만 입력하면 기록합니다.
명령은 키를 출력하고 0으로 종료하며 승인 상태를 직접 쓰지 않습니다.
예전 `<cli>:<kind>@<target>`과 `mcp:session` 형식도 받아 같은 세션 쓰기 승인으로 처리합니다. 파괴·강제 종류,
`sql:always:*`, 파괴적인 `mcp:<tool>` 키는 사전 승인할 수 없으므로 매번 묻는 작업은 요청할 수 없습니다.
명시적인 `unclassified` 요청 키 형식도 거부하지만, 세션 쓰기 승인은 비파괴적인 분류 불가 호출에도 적용됩니다.

Codex에서 코드 방식이 적용되면 승인이 필요한 호출을 두 줄짜리 코드와 함께 거부합니다. 영어로는 다음과 같습니다.

```text
Approval required: kubectl apply on (default) dev/web. Approving also covers later writes in this session. Ask the user to reply `approve K7M2QX` (or just `approve` when only one is pending).
After the user replies with the code, retry this exact call immediately and continue the task without asking again.
```

한국어로는 첫 줄이 다음과 같고 둘째 줄은 그대로입니다.

```text
승인 필요: kubectl apply on (default) dev/web. 승인하면 이 세션의 쓰기도 더 묻지 않습니다. 사용자에게 `승인 K7M2QX` 입력을 요청하세요(대기 요청이 하나면 `승인`만).
```

사용자는 채팅에 `승인 <CODE>` 또는 `approve <CODE>`를 입력합니다. 대기 중인 요청이 정확히 하나이면 `승인`이나
`approve`만 입력해도 됩니다. `UserPromptSubmit` 훅이 승인을 기록하면 에이전트는 같은 호출을 즉시 재시도하고
다시 묻지 않은 채 작업을 계속합니다. 양쪽 호스트 모두 `UserPromptSubmit` 컨텍스트에 승인한 설명과 이 재시도 지침을 제공합니다.
코드는 거부된 호출의 모든 키를 덮습니다. 매번 묻는 키는 한 번짜리 승인으로, 세션 키는 세션 승인으로 덮습니다.
세션 승인은 세션이 끝날 때까지 유지되며, 7일 동안 활동이 없는 세션의 상태는 지웁니다.
Codex의 일회 승인이 진행 중이고 `PostToolUse`나 `PostToolUseFailure`가 없으면 같은 키의 다음 시도는 코드 없이 한 번 재사용할 수 있습니다.
승인은 그 재시도로 옮겨 가며, 그 호출도 중단되면 새 승인을 요청해야 합니다.
`PermissionRequest`는 승인을 가진 호출만 허용하고 `PostToolUse`나 `PostToolUseFailure`가 정리합니다.

각 세션은 호출이 완료되거나 사용자가 새 프롬프트를 보낼 때까지 발급한 승인 요청을 키별로 셉니다. Claude의 확인 요청,
Codex의 네이티브 창, Codex의 코드 응답이 대상이며, 같은 대기 코드를 다시 보여 주는 것도 포함합니다. 사용자의 마지막
프롬프트 이후 `PostToolUse`나 `PostToolUseFailure` 없이 요청 세 번에 도달하면 네 번째 요청을 거부합니다. 영어 안내 문구는
“This approval was requested three times since the user's last message without the call
completing (declines included); stop retrying and tell the user.”입니다. 이미 받은 승인은 세 번째 코드로 승인한 재시도까지
실행합니다. `PostToolUse`나 `PostToolUseFailure`는 끝난 호출의 키별 횟수를 초기화하고, `UserPromptSubmit`은 모든 횟수를
초기화하므로, 중단된 뒤 사용자가 요청한 쓰기는 다시 승인을 묻습니다. 이미 세션 승인된 키는 다른 키의 요청 한도를 쓰지 않습니다.

## 스킬이 선언하는 쓰기

사용자가 스킬의 시작을 승인한 뒤 오래 도는 실행은 사용자가 자리를 비운 동안 새 쓰기 키에 닿을 수 있습니다. 플러그인은 스킬의 시작이 덮는 쓰기를 선언할 수 있고, 가드는 그 쓰기를 질문 없이 실행합니다. 선언이
없는 플러그인은 위에서 설명한 대로 동작합니다.

### 선언 파일

플러그인은 루트에 `approval-grants.json` 파일 하나를 둡니다. 가드는 이 파일을 지금 실행 중인 Claude Code 설치가
`installed_plugins.json`(`$CLAUDE_CONFIG_DIR/plugins` 또는 `~/.claude/plugins` 아래)에 설치된 것으로 적은 버전에서만 읽습니다.
설치된 플러그인 코드가 가드가 에이전트로부터 보호하는 대상이기 때문입니다. 그래서 이전 버전으로 되돌린 플러그인은 그 이전
선언을 적용하고, 그 파일에 없는 플러그인이나 다른 호스트의 캐시에만 있는 사본에는 선언이 없습니다. 작업 트리로
향하는 링크처럼 플러그인 캐시 밖으로 풀리는 파일은 무시합니다. 레이아웃이 틀린 파일은 통째로 거부합니다.

```json
{
  "skills": {
    "demo-run": {
      "entries": [
        {"command": "az repos pr update --status completed"},
        {"command": "az repos pr update --id <id> --status completed --delete-source-branch false",
         "extra_options": false},
        {"command": "git push -u origin <branch:feature/*>"},
        {"command": "kubectl rollout restart <workload> -n <ns:@grant> --context <ctx:@grant>",
         "never": {"ctx": ["prod-ctx"]}},
        {"command": "curl -X DELETE https://<host:api.dev.example.com|api.stg.example.com>/<path>", "destructive": true},
        {"tool": "mcp__demo__demo_post_message", "arguments": {"channel": "C123"}}
      ]
    }
  }
}
```

항목에는 `command`(명령 예시) 또는 `tool`(전체 `mcp__<server>__<tool>` 이름과, 호출이 지녀야 할 값을 적은 `arguments`) 중 정확히 하나가 있습니다. `never`는
자리표시자 이름을 절대 받아들이지 않는 값에 대응시키고, `destructive: true`는 가드가 파괴적으로 분류하는 호출까지 그 항목이 덮게 하며, 명령 항목의 `extra_options: false`는 그 항목이 자기 옵션 밖의 옵션을 더하지 않는 쓰기에만 일치하게 합니다([쓰기나 호출 매칭](#쓰기나-호출-매칭) 참고). `extra_options`는 `true`나 `false`를 받고 기본값은 `true`입니다. 다른 키가 있거나 다른 값이면 그 항목은 잘못된 항목이 되어,
grant가 무시하고 이유를 알립니다.

| 자리표시자 | 받아들이는 값 |
|---|---|
| `<name>` | 모든 값 |
| `<name:a\|b>` | 나열한 값 중 하나 |
| `<name:glob>` | glob에 맞는 값(예: `<branch:feature/*>`) |
| `<name:@grant>` | grant 명령이 `name`에 넘긴 값 |

자리표시자는 인자 전체나 URL 경로 같은 인자의 일부를 대신할 수 있습니다. 예시 값이 JSON 객체인 옵션은 모든 깊이에서 예시와 키가 정확히 같은 인라인 JSON 객체를 받아들이며, 각 값은 예시와 같거나
JSON 문자열로 적은 자리표시자가 받아들이는 값이어야 합니다. 키가 더 있거나 모자란 경우, 타입이 다른 경우, 반복된 키, `@body.json`처럼 파일에서 읽는 값은 절대 일치하지 않습니다.

### grant, 거부, link

스킬은 시작한 뒤 grant 명령을 실행합니다.

```bash
python3 <plugin root>/scripts/approval_guard.py grant --skill demo-run --value ctx=dev-ctx --value ns=demo
```

`--skill`은 `<skill>` 또는 `<plugin>:<skill>`을 받고, `--value name=value`는 `@grant` 자리표시자에 값을 넘기며 반복할 수 있습니다. `PreToolUse` 훅이
`request`와 같은 방식으로 이 호출을 판정하고, 스킬 이름과 시각을 붙여 grant를 세션 상태 파일에 저장합니다. 명령은 저장된 보고서를 출력합니다. 유지한 항목, 이유와 함께 무시한 항목, grant한
값, 거절한 값입니다. 같은 세션에서 다시 실행하면 유지 항목을 새로 정하고 값을 더합니다. 항목의 `never` 목록에 있는 값은 거절하고 알리며, 나머지 grant는 기록합니다.

훅은 아래 조건이 모두 맞을 때만 grant하고, 아니면 호출을 거부하며 아무것도 grant하지 않습니다.

- 호스트가 Claude Code입니다. 이 검사에는 transcript가 필요해서 Codex는 거부합니다.
- 호출이 메인 세션에서 옵니다. 이벤트에 `agent_id`가 없어 서브에이전트가 아니고, `HEI5ENBUG_PARENT_SESSION`이 없어 워커나 자식이 아닙니다.
- 세션 transcript의 메인 스레드가 사용자가 입력한 명령이나 `Skill` 도구 호출로 그 스킬이 시작되었음을 보여 줍니다. 서브에이전트, 도구 결과, 스킬이 주입한 텍스트에 기록된 시작은 인정하지
  않습니다.
- 설치된 플러그인의 `approval-grants.json`이 그 스킬을 선언합니다. 두 플러그인이 같은 이름을 선언하면 `<plugin>:<skill>` 형태가 필요합니다.

grant는 아래 조건이 맞는 항목만 유지하고 나머지는 무시합니다.

- 모든 자리표시자를 받아들이는 값으로 채웠을 때 가드가 명령 예시를 쓰기로 분류하거나, 항목에 `destructive: true`가 있으면 파괴적으로 분류하며, 치명적으로는 분류하지 않습니다. 민감 조회, 비밀
  접근, 분류되지 않은 명령은 무시합니다. 도구 항목도 같은 방식으로 쓰기로 분류되어야 합니다.
- 키의 대상 부분에 닿는 자리표시자(호스트, 데이터베이스, 컨텍스트, 네임스페이스, 푸시 원격 등)는 값을 나열하거나 grant에서 받아야 합니다. 거기에 열린 자리표시자나 glob이 있으면 항목을 무시합니다.
- 푸시 예시는 원격과 모든 refspec을 밝히고, 일반 플래그만 쓰며, 강제나 삭제 형태(`--force`, `--force-with-lease`, `-f`, `--delete`, `-d`, `--mirror`,
  `+`나 `:`로 시작하는 refspec)가 없습니다. refspec 없는 `git push`는 가드가 읽지 않는 설정에서 refspec을 가져오므로 무시합니다.

`HEI5ENBUG_PARENT_SESSION`으로 연결된 자식 프로세스는 그 세션의 승인 키를 쓰듯 그 세션의 grant를 씁니다. 자식을 시작하는 스킬은 자기 Bash 호출에서 `python3 <plugin
root>/scripts/approval_guard.py link`를 실행합니다. 이 명령은 현재 세션의 값 (예: `claude:<session id>`)을 출력합니다. 그런 다음 그 텍스트를 환경 변수로 붙여
자식을 시작합니다. 예: `HEI5ENBUG_PARENT_SESSION=claude:<session id> claude -p ...`. 링크 없이 시작한 자식에게는 grant가 없고, 비대화형 자식은 전처럼
묻습니다.

### 쓰기나 호출 매칭

가드는 먼저 다른 곳과 똑같이 쓰기를 분류합니다. 치명적인 쓰기는 절대 일치하지 않습니다. 파괴적으로 분류된 쓰기는 `destructive: true`인 항목에만 일치합니다. 쓰기가 파이프, 리다이렉션, 셸 확장,
환경 변수 접두어가 없는 단순 명령 하나이고 아래가 모두 맞으면 유지된 항목과 일치합니다.

- 예시의 모든 리터럴 부분이 쓰기와 같습니다. 위치 인자, 옵션 값, 한 인자 안에서 자리표시자 둘레의 텍스트를 포함합니다. 위치 인자 개수도 같습니다.
- 쓰기가 예시의 모든 옵션을 예시와 같은 횟수만큼 지닙니다. `--option value`와 `--option=value`는 같고, `--namespace`의 `-n` 같은 별칭은 다른 옵션입니다. 쓰기에 옵션이
  더 있어도 됩니다. 다만 명령줄 밖에서 동작이나 대상을 바꿀 수 있는 옵션은 안 됩니다. 이름이 설정, 파일, 입력, kubeconfig,
  URL, 다음 요청, 요청, 출력을 가리키는 옵션, `-K`, `-f`, `-o`, `-:`, 그리고 값이 `@`나 `file:`로 시작하는 추가 옵션이 여기에 해당합니다. `"extra_options": false`인 항목은 추가 옵션을 모두 거부합니다. 쓰기는 항목의 옵션만 정확히 지녀야 하며, `<id>` 같은 자리표시자는 여전히 그 값과 일치합니다. 위 예시의 두 번째 항목은 `az repos pr update --id 7 --status completed --delete-source-branch false`와 일치하지만, 같은 쓰기에 `--bypass-policy true --bypass-policy-reason x`나 `--auto-complete true`가 붙으면 거부합니다.
- 채운 값 모두를 해당 자리표시자가 받아들이고 `never` 목록에 없습니다. 반복되는 자리표시자는 값 하나만 가집니다.
- 쓰기의 값으로 채운 예시가 쓰기와 같은 키로 분류됩니다. `git`이나 `gh` 키처럼 키가 명령 텍스트의 다이제스트이면 채운 예시의 단어가 쓰기의 단어와 하나하나 같아야 합니다.
- 푸시는 refspec을 명시하고, 강제나 삭제 형태가 없으며, 채운 값에 `:`가 들어 있거나 `+`로 시작하는 값이 없습니다. 그래서 `+feature/demo`와
  `staging-1:refs/tags/release-1`은 절대 일치하지 않습니다.

MCP 호출은 도구 이름이 같고, 항목이 나열한 인자를 모두 지니며, 각 값이 받아들여지면 도구 항목과 일치합니다. 가드가 파괴적으로 분류한 호출은 `destructive: true`인 항목에만 일치하고, 치명적인
호출은 절대 일치하지 않습니다. DataGrip `execute_sql_query` 호출과 `mcp__tabularis__run_query` 호출도 같은 방식으로 일치합니다. `datagrip_guard.py`와 승인 가드가 [MCP와 데이터베이스 호출](#mcp와-데이터베이스-호출)처럼 쿼리를 분류한 뒤, 비운영 데이터 소스나 연결의 파괴적이지 않은 쓰기는 일치하는 항목이 필요하고 파괴적 문장은 `destructive: true`인 항목이 필요합니다. 운영이거나 확인되지 않은 데이터 소스나 연결은 절대 일치하지 않으므로 그 쓰기나 문장은 전처럼 묻습니다. grant는 `projectPath`와 `connectionId`가 grant 실행 시점에 확인되는 비운영 데이터 소스를 가리킬 때만 그런 항목을 유지합니다.

일치한 호출은 묻지 않고 실행되며 세션 승인을 남기지 않습니다. Claude Code 모드용 호출 기록은 `source` 필드에 `<plugin>:<skill>`로 그 스킬을 승인의 출처로 적습니다. 유지된 어떤
항목에도 일치하지 않는 쓰기는 전과 같이 동작합니다.

### 이 기능이 신뢰하는 것

가드는 스킬이 메인 세션에서 시작되었는지와 쓰기가 유지된 항목에 일치하는지를 확인합니다. 두 가지는 선언한 플러그인에 맡깁니다. 스킬은 사용자의 요청이나 승인이 있을 때만 시작한다는 점, 그리고 어떤 항목도 운영
대상을 받아들이거나 grant하지 않는다는 점입니다. grant는 사용자가 스킬을 승인한 위에 얹는 가드레일이지 보안 경계가 아닙니다. 유지된 항목과 grant한 값은 세션이 끝날 때까지 유지되며, 사용자가 시작하지
않은 스킬은 이를 얻지 못합니다.

## 보호되는 상태와 코드

에이전트는 스스로 승인할 수 없습니다. `approval_guard.py`, `datagrip_guard.py`, `approval_state.py`, 그리고 이들이 가져오는
`approval_state_*.py`, `datagrip_sql.py`, `guard_*.py` 모듈을 프로그램으로, `-m`으로, 또는 이를 가져오는 Python 코드로 실행하는 Bash 명령은 두 호스트
모두에서 거부됩니다.
승인 또는 heartbeat 상태 디렉터리를 가리키는 명령은 모든 단순 명령이 허용된 읽기 명령일 때만 예외입니다.
허용 목록은 `ls`, `cat`, `head`, `tail`, `grep`, `wc`, `stat`, `file`, `find`, `echo`입니다. `find`는 `-type`, `-name`,
`-maxdepth`, `-print` 같은 읽기 옵션만 쓸 수 있고 글롭 문자를 쓸 수 없습니다. 명령에는 중괄호, 치환, 변수 대입 접두사,
`/dev/null` 이외의 출력 리다이렉션이 없어야 합니다. 허용하는 변수는 `$HOME`, `${HOME}`, `$XDG_STATE_HOME`,
`${XDG_STATE_HOME}`, `${XDG_STATE_HOME:-<절대 경로>}`뿐이며, 각각 단어의 맨 앞에서 `/`로 이어지는 경로 접두로만 쓸 수 있습니다.
예: `ls "$HOME/.local/state/hei5enbug-agent-setup/approvals"`. 가드는 경로를 검사하기 전에 이 변수를 풉니다. 그 밖의
`$`, `$(`, 백틱, `<(`, `>(`, 중괄호는 거부하며, 거부 사유가 원인을 밝힙니다(예: `It was denied because of "$(".`).
`cat`이나 `rg`로 가드 파일을 읽기만 하는 명령은 거부되지 않습니다. 위에서 검증한 `request`, `grant`, `link` 명령만 실행 예외입니다.
두 상태 디렉터리 안의 파일 편집은 `apply_patch` 패치가 가리키는 경로를 포함해 양쪽 호스트 모두 거부합니다.

설치된 플러그인 코드도 같은 방식으로 보호합니다. Claude나 Codex 플러그인 캐시(`~/.claude/plugins/cache`,
`$CLAUDE_CONFIG_DIR/plugins/cache`, `~/.codex/plugins/cache`)나 실행 중인 플러그인 루트에 쓰는 호출은 양쪽 호스트에서
거부합니다. 리다이렉션, `tee`, `sed -i`, `cp`·`mv`·`install`·`rsync`·`ln`의 대상, heredoc·`-c` 옵션·스크립트 파일의 Python
코드가 그 경로를 쓰거나 옮기거나 지우는 경우, 대상이 그곳에 있는 `Write`·`Edit`·`MultiEdit`·`NotebookEdit`·`apply_patch`
호출이 모두 해당합니다. 가드는 비교 전에 `..`, 반복된 슬래시, `~`, 알려진 변수, 심볼릭 링크를 풀어서 보고, 캐시를 설정된
위치와 링크가 가리키는 위치 양쪽으로 알아보므로 git 작업 트리로 연결된 캐시도 계속 보호됩니다. 그 코드를 읽는 것은 계속
허용합니다.

heredoc·`-c` 옵션·스크립트 파일의 Python 코드가 보안에 민감한 위치의 경로를 쓰거나 옮기거나 지우면 매번 묻습니다.
대상은 `~/.ssh`, `~/.aws`, `~/.gnupg`, 셸 시작 파일 `~/.zshrc`, `~/.bashrc`, `~/.profile`, `~/.bash_profile`,
`~/.zprofile`, `.git/hooks` 폴더, Claude와 Codex 설정 파일(`.claude` 폴더나 `$CLAUDE_CONFIG_DIR`의 `settings.json`·
`settings.local.json`, `~/.claude.json`, `.codex` 폴더나 `$CODEX_HOME`의 `config.toml` ·`hooks.json`)입니다. 심볼릭 링크인 파일이나
폴더는 자기 이름과 링크 대상
양쪽으로 따집니다. 가드는 `dst=`·`path=`·`target=` 같은 키워드 인자와 경로를 바꾸는 `with_suffix`·`with_name`·`with_stem`을 거쳐도 경로를 따라갑니다.
작업 트리나 그 밖의 평범한 Python 쓰기는 묻지 않습니다.

비밀 값이 필요한 명령은 비밀 도우미를 사용합니다: `python3 <plugin root>/scripts/secret_exec.py --secret
DB_PASSWORD=k8s:<context>/<namespace>/<secret>/<key> -- <command>`. 소스는 `k8s:`, `keyvault:<vault>/<name>`,
`aws:<secret id>[#<json key>]`, `gcp:<project>/<name>[/<version>]`입니다. `--file VAR=<source>`는 값 대신 임시 파일의 경로를
넘깁니다. 값은 환경 변수나 임시 파일을 통해서만 명령에 전달되며, 도우미가 명령 출력에서 값을 가립니다. 조회가 실패하면 도우미는 소스와 조회 명령의 종료 코드만 알리고, 조회 명령의
stderr는 출력하지 않습니다. 각 조회의 제한 시간은 30초입니다. 시간이 지나면 소스와 `timed out`을 알리고 2로 종료합니다.

역할 실행기의 자식에 `HEI5ENBUG_PARENT_SESSION=<host>:<session_id>`가 있으면 부모의 승인 키도 읽으며 상태는 바꾸지
않습니다. 잘못된 값은 무시합니다. 자식은 `UserPromptSubmit`에서 코드를 기록하거나 `request`, `grant`를 실행할 수 없습니다.
부모에게 없는 세션 승인이 필요한 호출은 메인 세션에서 요청(`request --key write:session` 또는 `--key sensitive:session`)한
다음 다시 시도하라는 안내와 함께 거부합니다. 자식은 부모 세션이 가진 `write:session`과 `sensitive:session` 승인을 그대로
사용하며, Codex 자식은 네이티브 창을 쓰지 않습니다. 자식에서 매번 묻는 작업은 모두 거부하며 메인 세션이 직접 실행합니다.
편집 가능한 Claude 자식은 `--tools`와 `--allowedTools`에 `Bash`도 받지만, 자식의 가드는 승인되지 않은 쓰기와
매번 묻는 작업을 계속 거부합니다.

가드가 다루는 쓰기에 Claude `permissions.ask` 규칙을 추가하지 마세요. 이 규칙은 세션 승인 뒤에도 매번 확인을 요청합니다.
Claude의 `defaultMode: dontAsk`는 가드가 요청하는 승인을 거부합니다. 가드가 허용하는 `kubectl get` 같은 읽기를 `prompt`하거나
금지하는 사용자 소유 Codex `rules/*.rules` 파일도 그대로 적용됩니다. [호스트 설정](configuration.ko.md#호스트-설정)은 이런 설정을 보고만 하고
고치지 않습니다.

## 훅 검증과 승인 범위

유효한 세션 ID가 있는 모든 이벤트는 토글 검사 전에 가능한 경우
`$XDG_STATE_HOME/hei5enbug-agent-setup/heartbeats/<host>-<session_id>`와 `.<EventName>` 파일을 만들거나 갱신합니다.
`PreToolUse`는 그 호스트가 읽는 훅 파일, 즉 `hooks/hooks.json`과 플러그인 manifest가 나열한 다른 훅 파일의 SHA-256도
`heartbeats/confirmed-<host>`에 한 줄로 기록합니다. 그래서 한 호스트 전용 훅 파일이 바뀌어도 다른 호스트에는 경고하지 않습니다.
해시가 없거나 다르면 `UserPromptSubmit`이 세션당 한 번 경고를 추가하고 세션 상태에 표시 여부를 저장합니다.
경고는 훅 변경 뒤 가드의 도구 검사가 아직 관찰되지 않았다고 설명합니다. Codex 사용자에게 `/hooks`에서 플러그인 훅을
신뢰하도록 안내하고, 그전에는 쓰기가 승인 없이 실행될 수 있다고 알립니다.
분류기 예외는 “hei5enbug-agent-setup approval guard failed; approve only if the call looks right” 이유로 매번 승인을 요청하고,
플러그인과 승인 가드의 이름, 예외 이름, 다음 단계를 담은 한 줄을 stderr에 남깁니다. 가드를 끄면 여전히 아무것도 출력하지 않습니다.

승인 가드는 보안 경계가 아니라 안전장치입니다. 셸 전체 권한을 가진 에이전트는 우회할 수 있습니다. 가드가 다루지 않는 호출은 호스트의 기존 권한 절차를 따릅니다. 승인 상태는
`$XDG_STATE_HOME/hei5enbug-agent-setup/approvals/`(기본값 `~/.local/state`) 아래에 호스트와 세션마다 한 파일씩 저장됩니다.
승인은 세션이 끝날 때까지 유지되고, 7일 동안 활동이 없는 세션 파일은 다른 승인을 쓸 때 지워집니다. 가드를 끄려면
`approval_guard`를 `false`로 두거나, Codex에서는 `HEI5ENBUG_APPROVAL_GUARD=false`를 설정하세요.
Codex에서는 `/hooks`에서 훅을 신뢰해야 합니다.

`approval_scope` 옵션은 가드가 얼마나 자주 묻는지 정합니다. 기본값 `tiered`는 위 설명대로 동작합니다.
`session`은 세션당 한 번 묻습니다. 어떤 종류든 첫 승인이 그 세션의 이후 호출을 모두 덮습니다. 다만 네 가지는 계속
매번 묻고, 그 승인은 해당 호출에만 적용됩니다. 커밋하지 않은 작업 버리기(`git reset --hard`, `git clean`, 작업 트리
변경을 버리는 `git checkout` 이나 `git restore`, `git worktree remove --force`, 커밋하지 않은 변경이나 무시되지 않은 새 파일이 있는 파일 삭제), 운영 DB
연결의 삭제 문장, 운영
context의 `kubectl delete` 같은 운영 인프라 삭제, 보안에 민감한 위치에 쓰는 Python(위 자기 승인 규칙 참고)입니다. 연결이나 context 이름에 운영 단어가 있거나 개발 단어가 없으면
운영으로 보므로, 알 수 없는 이름은 운영으로 남습니다. 거부되는 호출은 두 범위 모두에서 계속 거부됩니다.
