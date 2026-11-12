# hei5enbug-agent-setup

> 영어 원본: [README.md](../../README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

Claude Code와 Codex 사용자에게 공통 스킬, 세션 지침, 가드 훅을 제공하는 개인용 에이전트 하네스입니다.

- [주요 기능](#주요-기능)
- [지원 호스트와 사전 조건](#지원-호스트와-사전-조건)
- [설치](#설치)
- [스킬](#스킬)
- [문서 안내](#문서-안내)
- [개발 검사](#개발-검사)
- [관련 링크](#관련-링크)
- [라이선스](#라이선스)

## 주요 기능

| 기능 | 제공하는 것 |
|---|---|
| 세션 지침 | 공통 작업 규칙을 자동으로 불러오고, 상세 참조 문서는 필요할 때만 읽습니다. |
| 스킬 | 개발, 문서, 브라우저 작업, 유지보수에 재사용할 수 있는 작업 흐름입니다. |
| 위임과 모델 라우팅 | 작업 범위를 정해 배정하고 모델, 사고 강도, 실행 결과를 확인합니다. |
| 승인 가드 | 읽기는 승인 없이, 쓰기와 민감 조회는 세션 승인으로 실행하며 파괴적인 호출은 매번 승인받습니다. |
| Claude Code mod | 역할 고정, 내장 에이전트 제한, 위험 표시, 작업 현황판, 비밀 값 가림을 제공합니다. |
| 응답 언어와 DataGrip 가드 | 응답 언어를 검사하고 데이터베이스 쿼리를 보호합니다. |

각 스킬은 지침, 참조 문서, 스크립트를 한곳에 둡니다. 같은 `SKILL.md`가 두 호스트에서 수정 없이 작동합니다.

## 지원 호스트와 사전 조건

| 조건 | 설명 |
|---|---|
| 호스트 | Claude Code 또는 Codex입니다. 검증된 Claude Code 최소 버전은 [mod 호환성](docs/claude-code-mod.ko.md)을 참고하세요. |
| 플랫폼 | macOS와 Linux를 지원합니다. Windows 실행은 테스트 대상이 아닙니다. |
| Python | `PATH`의 `python3` 또는 [설정한 훅 인터프리터](docs/configuration.ko.md#기능-옵션)로 Python 3.12 이상을 사용합니다. |
| 훅 | 플러그인 훅을 켜고, Codex에서는 `/hooks`에서 검토하고 신뢰해야 합니다. 관리 정책이 실행을 막을 수 있습니다. |
| 선택 SQL 파서 | [DataGrip PostgreSQL 파서](docs/guards.ko.md#datagrip-쿼리-가드)를 쓰려면 `pglast`를 설치합니다. |

OpenCode 설정은 참고용 원본으로만 남아 있습니다. 이 플러그인은 이를 설치하거나 유지보수하거나 실행하지 않습니다.

## 설치

호스트에 맞는 명령으로 GitHub 저장소에서 번들을 한 번 설치합니다.

### Codex

```bash
plugin_release_tag=$(git ls-remote --tags --refs --sort=-version:refname \
  https://github.com/hei5enbug/hei5enbug-agent-setup.git |
  awk '$2 ~ /^refs\/tags\/v[0-9]+\.[0-9]+\.[0-9]+$/ {sub("refs/tags/", "", $2); print $2; exit}')
test -n "$plugin_release_tag" &&
  codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref "$plugin_release_tag" &&
  codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

### 첫 사용

새 Codex 스레드를 시작하거나 Claude Code를 다시 시작합니다. 플러그인 훅이 켜져 있고, Codex에서는 신뢰되어 있는지 확인합니다.
세션 지침은 자동으로 불러옵니다. 새 Codex 역할은 다음 세션부터 사용할 수 있습니다.
프로젝트에서 스킬을 시험하려면 다음과 같이 요청하세요.

```text
suggest-commit으로 현재 변경 사항의 커밋 메시지를 추천해 줘.
```

Claude Code의 `/config`에서 옵션을 고르거나 Codex를 시작하기 전에 대응하는 환경 변수를 설정합니다.
기본값은 [설정](docs/configuration.ko.md)을, 설치한 플러그인을 업데이트할 때는 [업데이트](docs/updates.ko.md)를 참고하세요.

## 스킬

| 스킬 | 용도 |
|---|---|
| [`aside-browser-tasks`](../../skills/aside-browser-tasks/SKILL.md) | 다른 도구로 끝내지 못하는 브라우저 작업을 로그인된 Aside Browser로 수행합니다. [한국어](skills/aside-browser-tasks/SKILL.ko.md) |
| [`decision-navigator`](../../skills/decision-navigator/SKILL.md) | 구현 경로가 분명해질 때까지 의사 결정 티켓을 해결합니다. [한국어](skills/decision-navigator/SKILL.ko.md) |
| [`deep-interview`](../../skills/deep-interview/SKILL.md) | 모호함을 점수로 평가하는 소크라테스식 인터뷰로 요구사항을 명확히 합니다. [한국어](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](../../skills/flowchart-design/SKILL.md) | 공통 디자인 기준으로 플로우차트를 만들고 고칩니다. [한국어](skills/flowchart-design/SKILL.ko.md) |
| [`docs-rewrite`](../../skills/docs-rewrite/SKILL.md) | 의미를 보존하면서 어색한 한국어를 포함한 기존 글을 자연스럽게 고칩니다. [한국어](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](../../skills/document-to-confluence/SKILL.md) | 문서를 Confluence에 게시하고 웹 편집과 댓글을 보존하면서 원본 변경을 반영합니다. [한국어](skills/document-to-confluence/SKILL.ko.md) |
| [`local-data-cleanup`](../../skills/local-data-cleanup/SKILL.md) | 에이전트 데이터를 검사하고 크기별로 보고한 뒤 선택한 항목만 삭제합니다. [한국어](skills/local-data-cleanup/SKILL.ko.md) |
| [`mistake-enforcer`](../../skills/mistake-enforcer/SKILL.md) | 요청하면 반복되는 저장소 실수를 과거 사례로 검증한 검사로 바꿉니다. [한국어](skills/mistake-enforcer/SKILL.ko.md) |
| [`skill-issue-creator`](../../skills/skill-issue-creator/SKILL.md) | 공개 초안에 비공개 이름이 있는지 먼저 확인한 뒤 스킬이나 지침의 빈틈을 선언된 트래커에 등록합니다. [한국어](skills/skill-issue-creator/SKILL.ko.md) |
| [`session-retro`](../../skills/session-retro/SKILL.md) | 세션 기록을 검토해 근거 있는 스킬 개선안과 요청한 계획을 만듭니다. [한국어](skills/session-retro/SKILL.ko.md) |
| [`session-triage`](../../skills/session-triage/SKILL.md) | 실행 중인 Orca 에이전트 세션을 누가 누구를 기다리는지에 따라 분류하고 한 번의 승인으로 조치해 유휴 세션이 차지한 메모리를 확보합니다. [한국어](skills/session-triage/SKILL.ko.md) |
| [`skill-builder`](../../skills/skill-builder/SKILL.md) | 에이전트 스킬을 만들고 평가하고 개선하고 패키징합니다. [한국어](skills/skill-builder/SKILL.ko.md) |
| [`orca-plugin-refresh`](../../skills/orca-plugin-refresh/SKILL.md) | 플러그인을 업데이트해 실행 중인 Orca 세션에 적용하고, 오래된 Claude Code 릴리스의 세션은 재개합니다. [한국어](skills/orca-plugin-refresh/SKILL.ko.md) |
| [`suggest-commit`](../../skills/suggest-commit/SKILL.md) | 저장소 스타일에 맞는 커밋 메시지 5개를 추천하거나 요청 시 커밋합니다. [한국어](skills/suggest-commit/SKILL.ko.md) |
| [`technical-design-writer`](../../skills/technical-design-writer/SKILL.md) | 구현 계획과 구분해 기술 설계 문서와 RFC를 작성하고 검토합니다. [한국어](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](../../skills/tiki-taka/SKILL.md) | 횟수가 제한된 Claude/Codex 토론으로 쟁점을 해결합니다. [한국어](skills/tiki-taka/SKILL.ko.md) |

각 스킬의 전체 절차, 실행 조건, 제한은 링크한 스킬 문서에 있습니다.

## 문서 안내

| 문서 | 답하는 질문 |
|---|---|
| [Claude Code mod](docs/claude-code-mod.ko.md) | Claude 전용 가드와 화면 표시는 무엇이며 어떤 호스트 버전에서 실행되나요? |
| [응답 언어와 DataGrip 가드](docs/guards.ko.md) | 답변을 어떻게 검사하고 데이터베이스 쿼리를 어떻게 보호하나요? |
| [승인 가드](docs/approval-guard.ko.md) | 어떤 호출이 통과·승인 요청·거부되며 승인은 어떻게 작동하나요? |
| [설정](docs/configuration.ko.md) | 어떤 옵션이 있고 어떤 호스트 설정을 바꿀 수 있나요? |
| [지침과 위임](docs/instructions-and-delegation.ko.md) | 지침을 어떻게 불러오고 작업자를 실행하며 모델을 검사하나요? |
| [업데이트](docs/updates.ko.md) | 릴리스, 호스트 업데이트, 실행 중인 Orca 세션은 어떻게 다루나요? |
| [개발](docs/development.ko.md) | 코드는 어디에 있고 이슈 트래커는 어떻게 선언하나요? |
| [규칙 집행](docs/rule-enforcement.ko.md) | 각 문서 규칙을 어떤 검사로 집행하나요? |

## 개발 검사

번들 스크립트에는 Python 3.12 이상과 PyYAML이 필요하고, Node 테스트에는 Node.js가 필요합니다. mod 테스트와 플러그인 검증에는
Claude Code CLI가 필요하며 2.1.307 이상이 필요하고 CI는 2.1.307 버전을 씁니다. `.github/workflows/validate.yml`이 macOS와 Linux에서 실행하는 검사와
플러그인 검증을 실행합니다.

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
claude plugin validate .
claude plugin test .
```

Orca CLI가 필요한 테스트는 Orca가 설치되어 있지 않으면 건너뛰므로 CI는 Orca 없이도 통과합니다. Orca를 설치한 뒤
`python3 -m pytest`를 다시 실행하면 이 테스트까지 확인합니다.

코어가 여러 개인 컴퓨터에서 더 빠르게 실행하려면 테스트를 작업 프로세스에 나누어 돌리는 `python3 -m pytest -n auto`를 실행합니다.

공개 경계를 어기는 커밋, 푸시, 태그, GitHub 쓰기를 실행하기 전에 막으려면 클론마다 한 번
`git config core.hooksPath .githooks`를 실행합니다. 이 공개 저장소에 적을 수 없는 이름까지 막으려면
`HEI5ENBUG_PUBLIC_BOUNDARY_WORDS`에 한 줄에 단어나 구절 하나를 적은 저장소 밖의 단어 목록 파일을 지정하거나,
[`public-boundary.json`](docs/development.ko.md#비공개-단어-목록-선언)에 그 파일을 선언한 플러그인을 설치합니다.
Claude Code는 `.claude/settings.json`의 프로젝트 훅을 읽고, Codex는 프로젝트를 신뢰하고 `/hooks`에서 훅을 검토한
뒤에만 `.codex/hooks.json`의 훅을 실행합니다. 설치된 플러그인도 어느 프로젝트의 세션에서든 같은 검사를 실행하며,
설치된 플러그인이 공개 저장소로 선언한 모든 저장소를 검사합니다.

`evals/e2e/`의 엔드투엔드 평가는 실제 에이전트 세션을 실행하므로 이 검사에 들어가지 않습니다. `python3 -m pytest`는
그 단위 테스트만 실행합니다. [평가 README](evals/e2e/README.ko.md)를 참고하세요.

## 관련 링크

- 도움이 필요하거나 기여하려면 [이슈 트래커](https://github.com/hei5enbug/hei5enbug-agent-setup/issues)와
  [개발 안내](docs/development.ko.md)를 참고하세요.
- 제거된 `omo-model-config` 스킬은 [보관된 버전](docs/development.ko.md#보관된-스킬)에서 찾을 수 있습니다.

## 라이선스

이 저장소는 Apache License 2.0을 따릅니다. 전문은 [`LICENSE`](../../LICENSE)에 있습니다.
