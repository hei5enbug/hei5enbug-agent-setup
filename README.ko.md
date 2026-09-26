# hei5enbug-agent-setup

[English](./README.md) | **한국어** | [日本語](./README.ja.md) | [简体中文](./README.zh-CN.md) | [Español](./README.es.md) | [Deutsch](./README.de.md) | [Français](./README.fr.md)

> 영어 원본: [README.md](README.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

AI 코딩 에이전트를 위한 커스텀 스킬 모음입니다. 호스트별로 다시 작성하지 않고 여러 에이전트 호스트에서 그대로 공유할 수 있도록 만들었습니다.

## 개요

플러그인 스킬은 `skills/` 아래 자신의 폴더에 지침·참조 문서·스크립트를 함께 둡니다.
플러그인에 포함하지 않는 스킬은 `standalone-skills/`에 둡니다. 같은 `SKILL.md`가 지원하는
모든 호스트에서 수정 없이 작동합니다.

## 지원 호스트

- Claude Code
- Codex
- OpenCode ([Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) 플러그인 사용)

## 구조

```
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── AGENTS.ko.md
├── CLAUDE.md
├── CLAUDE.ko.md
├── hooks/hooks.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── documentation.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── protected-values.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       └── common.md
├── scripts/session_context.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── ko/scout.ko.md
│   └── scout.md
├── standalone-agents/
│   └── codex-explorer.toml
├── standalone-skills/
│   └── omo-model-config/
└── skills/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 플러그인 스킬 폴더는 자신의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다.
플러그인 매니페스트는 호스트별 디렉터리에 스킬을 복사하지 않고 같은 `skills/` 디렉터리를
Codex와 Claude Code에 패키징합니다. `standalone-skills/` 디렉터리는 두 플러그인의 스킬
검색 경로에 포함되지 않습니다.

`agents/` 디렉터리는 Claude Code 플러그인에 함께 배포되므로, 번들을 설치하면
`hei5enbug-agent-setup:scout` 서브에이전트가 추가됩니다. 직접 복사할 필요가 없습니다.

Codex는 `~/.codex/agents/`와 `.codex/agents/`에서만 서브에이전트를 찾으므로 플러그인이 등록할 수 없습니다.
대신 세션 훅이 `~/.codex/agents/explorer.toml`이 없을 때만 `standalone-agents/codex-explorer.toml`을
그 위치에 씁니다. 이 파일은 Codex 내장 `explorer`를 덮어써 사고 강도와 읽기 전용 샌드박스를 고정합니다.
이미 있는 `explorer.toml`은 절대 덮어쓰지 않으며, 다음 Codex 세션부터 적용됩니다. 모델은 지정하지 않으므로
호스트의 기본 모델을 물려받고, Claude Code의 `scout`는 모델을 하나로 고정한다는 점이 다릅니다.

## 플러그인 설치

GitHub 저장소에서 스킬 묶음을 한 번 설치합니다.

### Codex

```bash
codex plugin marketplace add hei5enbug/hei5enbug-agent-setup --ref main
codex plugin add hei5enbug-agent-setup@hei5enbug
```

### Claude Code

```bash
claude plugin marketplace add hei5enbug/hei5enbug-agent-setup
claude plugin install hei5enbug-agent-setup@hei5enbug
```

## 지침 자동 적용

macOS와 Linux에서 플러그인 훅은 `instructions/session/common.md`와 현재 호스트의 지침을 합친다.
Codex에는 `codex.md`, Claude Code에는 `claude-code.md`를 사용한다.
호스트의 `PATH`에서 `python3`로 Python 3.12 이상을 실행할 수 있어야 한다.
훅은 Python 표준 라이브러리만 사용한다.
루트 `AGENTS.md`와 `CLAUDE.md`는 이 저장소 개발에만 적용하며 훅은 두 파일을 읽지 않는다.

두 호스트 모두 `hooks/hooks.json`을 자동으로 찾는다.
Codex가 제공하는 `PLUGIN_ROOT`가 설치 디렉터리를 가리키면 로더는 Codex 지침을 선택한다.
스크립트 위치는 두 호스트가 제공하는 `CLAUDE_PLUGIN_ROOT`로 찾는다.
사용자 전역 지침 파일이나 작업 저장소의 지침 파일은 복사하거나 덮어쓰지 않는다.

| 시점 | 동작 |
|---|---|
| 세션 시작·재개 | `SessionStart`가 설치된 지침 파일을 전달한다. |
| 세션 초기화·컨텍스트 압축 | `SessionStart`가 지침을 다시 전달한다. |
| 서브에이전트 시작 | `SubagentStart`가 같은 호스트의 지침을 전달한다. |
| 사용자 입력·턴 종료·세션 종료 | Orca 업데이트용 registry가 prompt 본문 없이 세션 메타데이터를 기록한다. |
| 조건에 맞는 작업 시작 | 에이전트가 `instructions/`의 필수 참조를 읽는다. |
| 플러그인 업데이트 설치 | 새 세션이 설치된 버전을 읽는다. 저장소에 푸시하는 것만으로는 반영되지 않는다. |

핵심 규칙은 요청이 바뀌어도 세션 컨텍스트에 남는다.
서비스 접근, 보호된 보안 값 접근, 에이전트 사용, 문서 작성의 세부 규칙은 관련 작업 전에만 읽는다.
요청을 처리하던 중 관련 작업이 생겨도 먼저 참조를 읽는다.
세션 컨텍스트는 구현 계획과 설계 문서를 구분하고 두 작업의 실행 조건을 유지한다.
`instructions/implementation-planning.md`는 구현 계획의 6단계 절차와 템플릿을 관리한다.
`technical-design-writer`는 설계 문서와 RFC를 담당한다.
`instructions/independent-model-validation.md`는 두 결과물에 공통으로 적용되는 독립 검증 규칙을 관리한다.
로더는 각 세션 지침의 조건부 링크를 설치된 플러그인 내부의 절대 경로로 바꾼다.
세션을 시작할 때 조건부 참조 본문까지 읽지는 않는다.

Codex는 현재 플러그인 훅 정의를 사용자가 검토하고 신뢰한 뒤에 실행한다.
훅이 꺼져 있거나 조직 정책이 플러그인 훅을 금지하면 자동 적용되지 않는다.
설치·업데이트 후 호스트의 훅 설정에서 활성화 여부를 확인하고, Codex에서는 신뢰 여부도 확인한다.
업데이트 후에는 Claude Code를 재시작하거나 Codex에서 새 세션을 시작한다.
훅은 호스트의 신뢰 설정을 우회하지 않으며, 실행 중인 세션의 플러그인 버전을 바꾸지 않는다.
`orca-plugin-refresh-resume` 스킬은 한 번 초기 등록한 뒤 registry를 사용해 플러그인을 갱신하고,
등록된 idle 세션을 재개한다.

세션 지침 누락·빈 파일·잘못된 로컬 참조나 9,000 UTF-8 바이트를 넘는 컨텍스트는 표준 오류로 알린다.
이때 지침 일부만 전달하지 않는다.
세션 시작 훅의 오류가 호스트 실행을 반드시 중단시키지는 않으므로, 오류를 해결한 뒤 자동 적용을 사용한다.
세션 지침 파일은 짧게 유지하고 세부 사항은 조건부 참조로 옮긴다.
Windows 실행과 실제 모델의 지침 준수 여부는 테스트 범위에 포함하지 않는다.

실행 시점과 신뢰 설정은 공식 [Codex 훅 문서](https://learn.chatgpt.com/docs/hooks)와
[Claude Code 훅 문서](https://code.claude.com/docs/en/hooks)를 따른다.

## 플러그인 업데이트

두 플러그인 매니페스트, `pyproject.toml`, `uv.lock`은 같은 의미적 버전을 사용해야 합니다.
아래 개발 검사를 모두 통과시킨 뒤 릴리스를 배포하기 전에 함께 갱신합니다.

릴리스 배포 후 Codex를 업데이트합니다.

```bash
codex plugin marketplace upgrade hei5enbug
codex plugin add hei5enbug-agent-setup@hei5enbug
```

릴리스 배포 후 Claude Code를 업데이트합니다.

```bash
claude plugin marketplace update hei5enbug
claude plugin update hei5enbug-agent-setup@hei5enbug
```

업데이트한 스킬과 지침을 불러오려면 새 Codex 스레드를 시작하거나
Claude Code를 다시 시작합니다.

### Orca 에이전트 세션 업데이트

`orca-plugin-refresh-resume`은 Orca 관리 idle 세션에서 이 플러그인을 업데이트하고 기존 native session ID로
재개합니다. 먼저 계획을 보여주고 승인받은 뒤 marketplace와 플러그인을 업데이트합니다.
세션이 작업 중이거나 registry에 없거나 구분되지 않으면, 또는 보내지 않은 입력이 있으면 설치 전에 중단합니다.
Claude Code의 백그라운드 작업과 예약된 재실행도 업데이트를 막습니다. worker는 종료 직전에 terminal 신원과
idle 상태를 다시 확인하지만, 호스트의 훅 시간 초과 때문에 새 prompt가 절대 들어오지 않는다고 보장할 수는
없습니다. 완료 알림이 실패하거나 확인되지 않으면 receipt를 확인하세요. 새 terminal에서 agent가 실행 중일
가능성이 있으면 알림을 무작정 다시 보내거나 같은 세션을 다시 재개하지 마세요.

Codex는 세 가지가 다릅니다. Codex는 prompt가 시작될 때만 세션을 등록하므로, prompt를 한 번도 받지 않은
Codex 세션은 prompt를 받거나 닫힐 때까지 계획을 막습니다. `/exit` 뒤에는 Codex가 대화를 놓을 때까지
기다리며, 1분 정도 걸릴 수 있습니다. 그다음 마지막으로 기록된 모델과 추론 강도로 재개합니다.
재개된 Codex 세션은 다음 prompt에서 플러그인 버전을 등록하며, 그전까지 receipt에는
`plugin_registration: pending_next_turn`이 표시됩니다.

최초 한 번은 수동 초기 설정이 필요합니다. 새 플러그인을 설치하고 Codex 훅을 검토·신뢰한 뒤 기존 세션을
한 번씩 재시작하거나 재개합니다. 이전 세션은 lifecycle registry가 없어 native session ID를 식별할 수 없습니다.
초기 설정 후에는 훅이 registry를 갱신하므로 이후 등록 세션을 자동으로 재개합니다.
macOS와 Linux의 `hei5enbug` marketplace 사용자 범위 설치를 지원합니다.

## 개발 검사

번들 스크립트는 PyYAML이 설치된 Python 3.12 이상이 필요하고, Node 테스트는 Node.js가 필요합니다.
`.github/workflows/validate.yml`이 macOS와 Linux에서 실행하는 세 가지 검사를 같은 명령으로 실행합니다.

```bash
python3 -m pip install -e ".[dev]"
for skill in skills/*/ standalone-skills/*/; do python3 skills/skill-builder/scripts/quick_validate.py "$skill"; done
python3 -m pytest
node --test skills/document-to-confluence/tests/test_render_diagrams.mjs
```

## 지침 언어

플러그인 스킬, 참조, 에이전트와 세션 지침은 영어 파일을 실행 가능한 기준 원본으로 사용합니다.
사람이 읽는 모든 영어 Markdown 파일에는 의미가 같은 `.ko.md` 번역본을 같은 위치에 둡니다.
번역본은 영어 원본을 연결하고 비권위 자료임을 밝히며 에이전트 실행 중 읽거나 사용하지 않습니다.
원본과 번역본은 함께 수정, 이동 또는 삭제합니다.

코드, 스키마, 테스트 자료, 생성 아티팩트와 영어가 아닌 문서는 한국어 복사본을 만들지 않습니다.
호출 문구, 예시, 필수 출력 이름 또는 평가 자료처럼 한국어 자체가 대상 데이터일 때만 영어 실행 파일에
한국어를 유지할 수 있습니다. 자동 검사는 번역본 존재와 실행 경로 분리를 확인하고 의미 일치는 사람이나
모델이 별도로 검토합니다.

## 스킬 목록

| 스킬 | 하는 일 |
|---|---|
| [`decision-navigator`](skills/decision-navigator/SKILL.md) | 여러 세션에 걸친 작업을 의사 결정 티켓으로 나누고, 구현 경로가 분명해질 때까지 티켓을 하나씩 해결합니다. [한국어 안내](skills/decision-navigator/SKILL.ko.md) |
| [`deep-interview`](skills/deep-interview/SKILL.md) | 답변마다 요구사항의 모호함 정도를 점수로 측정하는 소크라테스식 인터뷰를 진행하며, 그 점수가 기준값 이하로 내려가기 전에는 실행 단계로 넘어가지 않습니다. [한국어 안내](skills/deep-interview/SKILL.ko.md) |
| [`flowchart-design`](skills/flowchart-design/SKILL.md) | SVG, HTML/CSS, Figma, draw.io 등 어떤 도구로 만들어도 하나의 디자인 시스템처럼 보이게 하는 플로우차트 공통 디자인 기준입니다. [한국어 안내](skills/flowchart-design/SKILL.ko.md) |
| [`docs-rewrite`](skills/docs-rewrite/SKILL.md) | 주장, 수치, 확신도를 그대로 둔 채 글이 자연스럽게 읽히도록 고쳐 쓰고, AI가 쓴 듯한 한국어 문체를 함께 고칩니다. [한국어 안내](skills/docs-rewrite/SKILL.ko.md) |
| [`document-to-confluence`](skills/document-to-confluence/SKILL.md) | Markdown, HTML, PDF, DOCX, Google Docs 문서를 Confluence 페이지로 변환하고, 문서 구조와 첨부 파일을 보존하며, 이후 원본 변경도 페이지에 반영합니다. [한국어 안내](skills/document-to-confluence/SKILL.ko.md) |
| [`skill-builder`](skills/skill-builder/SKILL.md) | 초안 작성 → 테스트 → 검토 → 개선 순환을 통해 에이전트 스킬을 만들고, 검증하고, 패키징합니다. [한국어 안내](skills/skill-builder/SKILL.ko.md) |
| [`orca-plugin-refresh-resume`](skills/orca-plugin-refresh-resume/SKILL.md) | idle 상태의 Orca 관리 Claude Code와 Codex 세션에서 이 플러그인을 미리 확인하고 업데이트한 뒤 저장된 native ID로 각 세션을 재개합니다. [한국어 안내](skills/orca-plugin-refresh-resume/SKILL.ko.md) |
| [`suggest-commit`](skills/suggest-commit/SKILL.md) | 스테이징된 변경과 스테이징되지 않은 변경을 함께, 또는 사용자가 지정한 범위를 최근 커밋 이력과 함께 읽어, 이 저장소의 스타일에 맞는 커밋 메시지 5개를 제안합니다. [한국어 안내](skills/suggest-commit/SKILL.ko.md) |
| [`technical-design-writer`](skills/technical-design-writer/SKILL.md) | 구현 계획을 담당하지 않고 기술 설계 문서와 RFC를 작성하거나 검토합니다. [한국어 안내](skills/technical-design-writer/SKILL.ko.md) |
| [`tiki-taka`](skills/tiki-taka/SKILL.md) | 현재 에이전트와 반대쪽 Claude/Codex 세션이 교환 횟수를 제한한 토론을 벌여 쟁점을 드러내고 수렴시킵니다. [한국어 안내](skills/tiki-taka/SKILL.ko.md) |

## 관련 링크

- [요구사항 명확화 통합 후보](.plan/clarify-requirements-2026-09-26/README.ko.md)는 인터뷰와 결정 지도 절차를
  평가용으로 통합한다. 필요한 실제 호스트의 품질·실행 비용 비교를 통과하기 전까지 플러그인 탐색에서 제외한다.

- [`omo-model-config`](standalone-skills/omo-model-config/SKILL.md)은 독립 실행용 소스로 유지하며
  플러그인 스킬 목록에는 포함하지 않습니다. [한국어 안내](standalone-skills/omo-model-config/SKILL.ko.md)
- [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) — 독립 실행용 스킬이 모델 라우팅을
  갱신하는 플러그인 시스템

## 라이선스

이 저장소는 Apache License 2.0을 따릅니다. 전문은 [`LICENSE`](./LICENSE)에 있습니다.
