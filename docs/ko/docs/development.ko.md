# 저장소 개발

> 영어 원본: [development.md](../../development.md)
> 이 문서는 사람을 위한 비권위 한국어 번역본이다. 에이전트 실행 시 읽거나 사용하지 않는다.

이 문서는 기여자를 위한 저장소 구조와 이슈 트래커 선언을 설명합니다.

## 구조

```text
hei5enbug-agent-setup/
├── .agents/plugins/marketplace.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── .codex-plugin/plugin.json
├── .github/workflows/validate.yml
├── AGENTS.md
├── issue-target.json
├── docs/
│   ├── approval-guard.md
│   ├── claude-code-mod.md
│   ├── configuration.md
│   ├── development.md
│   ├── guards.md
│   ├── instructions-and-delegation.md
│   ├── rule-enforcement.md
│   ├── updates.md
│   └── ko/
│       ├── AGENTS.ko.md
│       ├── README.ko.md
│       ├── agents/
│       ├── evals/
│       ├── instructions/
│       └── skills/
├── evals/e2e/
├── hooks/hooks.json
├── hooks/claude-hooks.json
├── hooks/codex-hooks.json
├── hooks/mod/
├── config/claude-mod.json
├── config/model-registry.json
├── instructions/
│   ├── claude-agents.md
│   ├── codex-agents.md
│   ├── confluence.md
│   ├── cross-repository.md
│   ├── documentation.md
│   ├── failure-and-maintenance.md
│   ├── implementation-delegation.md
│   ├── implementation-execution.md
│   ├── implementation-planning.md
│   ├── independent-model-validation.md
│   ├── model-evaluation.md
│   ├── model-routing.md
│   ├── protected-values.md
│   ├── readme-writing.md
│   ├── services.md
│   └── session/
│       ├── claude-code.md
│       ├── codex.md
│       ├── common.md
│       └── core.md
├── scripts/
│   ├── agent_guard.py
│   ├── approval_guard.py
│   ├── approval_state*.py
│   ├── approve_wrapper.sh
│   ├── datagrip*.py
│   ├── guard_*.py
│   ├── hook_python.sh
│   ├── host_settings.py
│   ├── language_guard.py
│   ├── plugin_toggles.py
│   ├── role_runner.py
│   ├── session_context.py
│   └── verify_spawn.py
├── tests/
├── LICENSE
├── pyproject.toml
├── agents/
│   ├── designer.md
│   ├── reviewer.md
│   ├── scout.md
│   ├── sonnet-worker.md
│   └── worker.md
├── standalone-agents/
│   ├── codex-designer.toml
│   ├── codex-reviewer.toml
│   ├── codex-scout.toml
│   └── codex-worker.toml
└── skills/
    ├── aside-browser-tasks/
    ├── decision-navigator/
    ├── deep-interview/
    ├── flowchart-design/
    ├── docs-rewrite/
    ├── document-to-confluence/
    ├── local-data-cleanup/
    ├── mistake-enforcer/
    ├── orca-plugin-refresh/
    ├── report-skill-gap/
    ├── session-retro/
    ├── skill-builder/
    ├── suggest-commit/
    ├── technical-design-writer/
    └── tiki-taka/
```

각 플러그인 스킬 폴더는 자신의 `SKILL.md`와 필요한 참조 문서·스크립트를 담고 있습니다.
플러그인 매니페스트는 호스트별 디렉터리에 스킬을 복사하지 않고 같은 `skills/` 디렉터리를
Codex와 Claude Code에 패키징합니다.

## 이슈 트래커 선언

`report-skill-gap`은 담당 플러그인이 루트의 `issue-target.json`에 선언한 트래커에만 이슈를 등록합니다.
이 파일은 `.claude-plugin/`, `.codex-plugin/` 옆에 둡니다.
스킬은 모든 트래커를 이 파일에서 찾으므로, 이 플러그인은 자신을 기반으로 만든 플러그인을 알 필요가 없습니다.
이 플러그인은 자신의 저장소를 선언합니다.

```json
{
  "version": 1,
  "tracker": {"kind": "github", "location": "hei5enbug/hei5enbug-agent-setup"},
  "language": "en",
  "body_format": "markdown",
  "labels": ["bug", "enhancement"],
  "public": true,
  "write_approval": "preview"
}
```

| 필드 | 의미 |
|---|---|
| `version` | 항상 `1`입니다. |
| `tracker` | `kind`는 `github`, `gitlab`, `jira`, `other` 중 하나입니다. `location`은 GitHub에서는 `owner/repo`이고, 그 외에는 프로젝트 URL이나 키입니다. |
| `language` | 이슈에 쓰는 글의 언어 태그입니다. 예를 들어 `en`이나 `ko`입니다. |
| `body_format` | `markdown`, `jira-wiki`, `plain`, `html` 중 하나입니다. |
| `labels` | 스킬이 고를 수 있는 라벨 목록이며 하나를 고르고, 목록이 비어 있으면 고르지 않습니다. 또는 `;`로 구분한 태그 템플릿 문자열이며, `{skill}`은 담당 스킬의 이름이 되고 모든 태그를 적용합니다. 새 스킬 제안에서는 `{skill}`이 제안하는 스킬의 이름 다음에 `new-skill`이 오는 형태로 바뀝니다. 다른 플레이스홀더는 쓸 수 없습니다. |
| `public` | 누구나 트래커를 읽을 수 있으면 `true`입니다. 공개 트래커에서는 항상 미리 보여 줍니다. |
| `write_approval` | `preview`는 최종 내용을 보여 주고 승인을 기다립니다. `direct`는 스킬 이름을 부르면 등록합니다. |
| `content_rules` | 모든 이슈에서 내용을 제외하는 추가 규칙 파일의 경로입니다. 선택 사항이며 플러그인 루트를 기준으로 합니다. |
| `recommend` | 선택 사항인 불리언이며 생략하면 `false`입니다. `true`이면 남은 작업이 없고, 이 플러그인의 빈틈 때문에 생긴 이미 끝난 결과를 사용자가 정정했거나 끝난 작업 흐름을 스킬이나 이슈로 만들어 달라고 요청했을 때, 요청받지 않아도 에이전트가 한 줄로 등록을 제안할 수 있습니다. 등록은 사용자가 이후 메시지에서 승인한 뒤에만 시작합니다. |

알 수 없는 키가 있으면 선언은 유효하지 않습니다.
파일이 없거나 유효하지 않은 플러그인은 대화에서 초안만 받고 이슈는 등록되지 않습니다.
`github`이 아닌 종류의 트래커에서는 선언된 위치에 닿는 연결된 도구를 쓰고, 없으면 이미 인증된 해당 트래커의 공식 CLI를 씁니다.
둘 다 없으면 초안만 보여 주고 등록하지 않습니다.

## 보관된 스킬

- `omo-model-config`는 제거했습니다. 마지막 버전은
  [`v1.3.0` 태그](https://github.com/hei5enbug/hei5enbug-agent-setup/tree/v1.3.0/standalone-skills/omo-model-config) 에
  있습니다.
