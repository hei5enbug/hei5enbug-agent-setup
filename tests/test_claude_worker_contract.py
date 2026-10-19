"""Structural checks for the Claude Code worker definition and adapter.

These checks confirm the shipped metadata and the stated host policy. They do not prove that a live
Claude Code session selects the model or follows the policy; native trials cover that.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import session_context  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "agents/worker.md"
WORKER_MIRROR = REPO_ROOT / "docs/ko/agents/worker.ko.md"
SONNET_WORKER = REPO_ROOT / "agents/sonnet-worker.md"
SONNET_WORKER_MIRROR = REPO_ROOT / "docs/ko/agents/sonnet-worker.ko.md"
CLAUDE_AGENTS = REPO_ROOT / "instructions/claude-agents.md"
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin/plugin.json"
UNSUPPORTED_FIELDS = {
    "tools",
    "permissionMode",
    "isolation",
    "skills",
    "hooks",
    "mcpServers",
    "background",
    "memory",
    "initialPrompt",
}


def split_definition(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"missing frontmatter: {path}")
    return yaml.safe_load(match[1]), match[2]


def implementation_section() -> str:
    text = CLAUDE_AGENTS.read_text(encoding="utf-8")
    return " ".join(text.split("## Implementation", 1)[1].split())


class ClaudeWorkerDefinitionTest(unittest.TestCase):
    def test_worker_메타데이터는_고정_Haiku_ID_high와_Agent_금지를_정한다(self):
        """worker 정의는 이름, 고정된 Haiku 전체 ID, high, Agent 금지를 선언하고 우회나 자동 격리 필드를 두지 않는다."""
        # Given
        path = WORKER

        # When
        metadata, _ = split_definition(path)

        # Then
        self.assertEqual(metadata["name"], "worker")
        self.assertEqual(metadata["model"], "claude-haiku-5-5")
        self.assertEqual(metadata["effort"], "high")
        self.assertIn("Agent", [tool.strip() for tool in str(metadata["disallowedTools"]).split(",")])
        self.assertEqual(UNSUPPORTED_FIELDS & set(metadata), set())

    def test_worker_설명은_조정자가_할당한_구현에만_쓰게_한다(self):
        """worker 설명은 조정자가 할당한 구현 작업으로 사용 범위를 제한한다."""
        # Given
        path = WORKER

        # When
        metadata, _ = split_definition(path)

        # Then
        description = " ".join(metadata["description"].split())
        self.assertTrue(description.startswith("Coordinator-assigned implementation task only."))
        self.assertIn("Never use it for investigation, planning, review", description)

    def test_worker_본문은_공유_worker_계약을_가리킨다(self):
        """worker 본문은 규칙을 복사하지 않고 공유 실행 규칙의 worker 섹션을 가리킨다."""
        # Given
        path = WORKER

        # When
        _, body = split_definition(path)

        # Then
        normalized = " ".join(body.split())
        self.assertIn('Follow the "Assigned workers" rules in your session instructions or assignment', normalized)
        self.assertIn("report it to the coordinator and make no edit", normalized)
        self.assertNotIn("min(6", normalized)
        self.assertIsNone(re.search(r"claude-sonnet-\d", body))

    def test_sonnet_worker는_worker와_같은_본문에_Sonnet_모델을_고정한다(self):
        """sonnet-worker는 worker와 같은 본문을 쓰고 고정된 Sonnet 전체 ID와 high를 선언한다."""
        # Given
        worker_metadata, worker_body = split_definition(WORKER)

        # When
        metadata, body = split_definition(SONNET_WORKER)

        # Then
        self.assertEqual(metadata["name"], "sonnet-worker")
        self.assertEqual(metadata["model"], "claude-sonnet-5-5")
        self.assertEqual(metadata["effort"], worker_metadata["effort"])
        self.assertEqual(body, worker_body)
        self.assertEqual(UNSUPPORTED_FIELDS & set(metadata), set())

    def test_플러그인은_영어_정의만_에이전트로_등록하고_한국어_미러는_제외한다(self):
        """기본 agents 스캔은 하위 폴더까지 등록하므로 매니페스트가 영어 정의 파일만 나열해 agents/ko 미러를 뺀다."""
        # Given
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

        # When
        listed = manifest.get("agents")
        definitions = sorted(f"./agents/{path.name}" for path in (REPO_ROOT / "agents").glob("*.md"))

        # Then
        self.assertEqual(
            listed,
            [
                "./agents/scout.md",
                "./agents/worker.md",
                "./agents/sonnet-worker.md",
                "./agents/designer.md",
                "./agents/reviewer.md",
            ],
        )
        self.assertEqual(sorted(listed), definitions)
        self.assertFalse(any("/ko/" in path for path in listed))
        mirror = WORKER_MIRROR.read_text(encoding="utf-8")
        self.assertIn("영어 원본: [worker.md](../../../agents/worker.md)", mirror)
        self.assertIn("비권위", mirror)
        sonnet_mirror = SONNET_WORKER_MIRROR.read_text(encoding="utf-8")
        self.assertIn("영어 원본: [sonnet-worker.md](../../../agents/sonnet-worker.md)", sonnet_mirror)
        self.assertIn("비권위", sonnet_mirror)
        reviewer_mirror = (REPO_ROOT / "docs/ko/agents/reviewer.ko.md").read_text(encoding="utf-8")
        self.assertIn("영어 원본: [reviewer.md](../../../agents/reviewer.md)", reviewer_mirror)
        self.assertIn("비권위", reviewer_mirror)

    def test_designer_메타데이터는_고정_Opus_ID_xhigh와_Agent_금지를_정한다(self):
        """designer 정의는 이름, 고정된 Opus 전체 ID, xhigh, Agent 금지를 선언하고 worker와 같은 할당 규칙을 따른다."""
        # Given
        path = REPO_ROOT / "agents/designer.md"

        # When
        metadata, body = split_definition(path)
        normalized = " ".join(body.split())

        # Then
        self.assertEqual(metadata["name"], "designer")
        self.assertEqual(metadata["model"], "claude-opus-5-5")
        self.assertEqual(metadata["effort"], "xhigh")
        self.assertEqual(metadata["disallowedTools"], "Agent")
        self.assertEqual(set(metadata) & UNSUPPORTED_FIELDS, set())
        self.assertIn("UI code (HTML, CSS, JS, components)", normalized)
        self.assertIn("flowcharts, diagrams, or images", normalized)
        self.assertIn("the `design` capability:", normalized)
        self.assertIn("technical design document drafting assigned to you", normalized)
        self.assertIn("including writing the document file in the allowed path", normalized)
        self.assertIn("technical design document", metadata["description"])
        self.assertIn('Follow the "Assigned workers" rules in your session instructions or assignment', normalized)
        self.assertIn("report it to the coordinator and make no edit", normalized)
        mirror = (REPO_ROOT / "docs/ko/agents/designer.ko.md").read_text(encoding="utf-8")
        self.assertIn("영어 원본: [designer.md](../../../agents/designer.md)", mirror)
        self.assertIn("비권위", mirror)

    def test_매니페스트는_Mod_설정과_기본_구현_worker_옵션을_선언한다(self):
        """hooks 모듈과 boolean 토글, 세 경로를 선택하는 구현 worker 문자열 옵션을 선언한다."""
        # Given
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

        # When
        config_path = REPO_ROOT / manifest["hooks"]
        modules = json.loads(config_path.read_text(encoding="utf-8"))["modules"]
        options = manifest["userConfig"]

        # Then
        self.assertEqual(manifest["hooks"], "./config/claude-mod.json")
        self.assertEqual(modules, ["../hooks/mod/register.js"])
        self.assertTrue(all((config_path.parent / module).is_file() for module in modules))
        self.assertEqual(
            list(options),
            [
                "agent_guard",
                "role_pinning",
                "implementation_worker",
                "worker_model",
                "worker_effort",
                "codex_worker_model",
                "codex_worker_effort",
                "review_model",
                "language_guard",
                "datagrip_guard",
                "approval_guard",
                "python",
            ],
        )
        self.assertEqual(
            options["implementation_worker"],
            {
                "type": "string",
                "title": "Implementation worker",
                "description": "Route implementation work: auto (the main session picks per task: haiku for easy work, sol for normal or hard work, sonnet when Codex usage is high), codex (Codex on gpt-5.6-luna at xhigh), haiku (the plugin worker on its Worker model and Worker effort, claude-haiku-5-5 at high by default), sol (gpt-6.1-sol at high through the role runner), or sonnet (the plugin sonnet-worker on claude-sonnet-5-5 at high).",
                "options": ["auto", "codex", "haiku", "sol", "sonnet"],
                "default": "auto",
            },
        )
        self.assertEqual(options["review_model"]["type"], "string")
        self.assertEqual(options["review_model"]["default"], "gpt-6-astra")
        self.assertEqual(set(options["review_model"]["options"]), set(session_context.REVIEW_MODELS))
        self.assertIn("sonnet-worker", options["role_pinning"]["description"])
        self.assertEqual(
            options["approval_guard"]["description"],
            "Run covered CLI, script, database, and MCP reads without approval; ask once per session for writes, including production changes and git pushes, and reuse that approval for the rest of the session; reuse any other approved action for the session too, except force pushes, discarding uncommitted work, recursive deletion outside the session or temporary folders, destructive database statements, and remote infrastructure deletion, which ask every time; deny secret-printing commands and approval-state edits.",
        )
        self.assertEqual(
            options["datagrip_guard"]["description"],
            "Run DataGrip reads without approval with a 60-second PostgreSQL limit; use the session write approval for writes and for every query on a data source marked as needing approval; ask every time for destructive queries.",
        )
        for key, option in options.items():
            with self.subTest(key=key):
                if key in {"implementation_worker", "worker_model", "worker_effort", "codex_worker_model", "codex_worker_effort", "review_model", "python"}:
                    self.assertTrue(option["title"].isascii() and option["description"].isascii())
                    continue
                self.assertEqual(option["type"], "boolean")
                self.assertIs(option["default"], True)
                self.assertTrue(option["title"].isascii() and option["description"].isascii())


class ClaudeWorkerAdapterTest(unittest.TestCase):
    def test_구현은_세션_경로_줄을_따르고_플러그인_agent에_고정_모델을_쓴다(self):
        """Claude에서 구현 위임은 세션의 worker 경로 줄을 따르고, 플러그인 agent에는 호출 단위 모델을 넘기지 않는다."""
        # Given
        expected = (
            "[implementation delegation rules](implementation-delegation.md)",
            'Delegated implementation follows the route in the session line "Implementation worker route". Use '
            '`hei5enbug-agent-setup:sonnet-worker` for the Sonnet worker when the line says `sonnet`, the Codex '
            'worker (see "Codex worker" below) when it says `codex`, `hei5enbug-agent-setup:worker` when it says '
            '`haiku`, and the Sol worker (see "Sol worker" below) when it says `sol`.',
            'The `worker` agent runs on the model and effort in the session line "Worker agent model" (Haiku at '
            '`high` by default).',
            "When it says `auto`, choose per assignment: the `worker` agent for easy work",
            "Sol for normal or hard work",
            "Sonnet instead of Sol when the Codex weekly usage is above 70 percent or Sol is unavailable.",
            "When a Claude route stops on a usage limit, use Sol.",
            "A user request for one route applies to that request only.",
            "`hei5enbug-agent-setup:designer` still takes UI code, visual design, and diagram work, except the kinds "
            "the Claude Code session file assigns to the main session.",
            "Never use any other agent.",
            "Never pass a per-invocation model to a plugin agent on an invocation or resume, because that overrides "
            "its definition",
            "The bullets below apply whenever a plugin agent runs: a runner fallback, the `worker` or Sonnet worker, "
            "and the designer.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        self.assertNotIn("alias", section)
        self.assertNotIn("model-config", section)
        self.assertIsNone(re.search(r"claude-[a-z]+-\d|gpt-\d", CLAUDE_AGENTS.read_text(encoding="utf-8")))

    def test_Codex_worker는_역할_실행기로_실행하고_작업_폴더_밖_쓰기만_추가_허용한다(self):
        """Codex worker는 role_runner worker로 실행하고, 세션 폴더 밖 디렉터리는 --add-dir로만 추가한다."""
        # Given
        expected = (
            "Write the assignment, with the usual assignment fields, to a file and run the `worker` role.",
            "Add `--add-dir <dir>` only for a directory outside the session folder that the task must write.",
            "The plugin mod asks once per session.",
        )

        # When
        section = implementation_section().split("## Codex worker", 1)[1]

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        for forbidden in ("codex exec", "danger-full-access", "--ephemeral"):
            self.assertNotIn(forbidden, section)

    def test_모드_줄이_없으면_실제_모델과_사고_강도를_낮출_수_있는_설정을_확인한다(self):
        """강제 모델, 사고 강도 재정의, 상한, 대체 경고를 확인하고 부족한 근거를 거부한다."""
        # Given
        inputs = (
            "`CLAUDE_CODE_SUBAGENT_MODEL`",
            "`CLAUDE_CODE_SUBAGENT_MODEL_FORCE`",
            "`CLAUDE_CODE_EFFORT_LEVEL`",
            "`maxEffortLevel`",
            "substitution or fallback warning",
        )

        # When
        section = implementation_section()

        # Then
        for name in inputs:
            self.assertIn(name, section)
        self.assertIn("Never change user settings.", section)
        self.assertIn("in the environment and every settings file", section)
        self.assertIn(
            "only when it names the invoked definition's pinned model and effort.",
            section,
        )
        self.assertIn(
            "A different recorded model, a cap below the pinned effort, a contradictory override, or unknown effective "
            "precedence is insufficient.",
            section,
        )

    def test_고정_표시_줄이_없으면_준비_확인_경로를_따르고_설정을_다시_확인한다(self):
        """고정 표시 줄이 없으면 구현 위임 규칙의 준비 확인 경로를 따르며 구현 후속 메시지마다 설정을 다시 확인한다."""
        # Given
        expected = (
            "Without that line, the launch result does not name the model.",
            "follow the readiness-only path in implementation delegation",
            "Claude Code can reload settings during a session, so recheck them before every follow-up that carries "
            "implementation work.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)
        self.assertNotIn("Use this path only when that follow-up keeps", section)

    def test_mod가_주입한_역할_고정_표시가_있으면_세션당_한_번_상한만_확인한다(self):
        """등록된 mod의 실제 역할 고정 표시가 있으면 위임마다 설정이나 기록을 읽지 않고 고정과 차단을 수락 증거로 쓴다."""
        # Given
        expected = (
            "When the session context has the line `hei5enbug-agent-setup mod: role pinning active`",
            "blocks tool calls from a subagent that answered on another model",
            "Once per session, check only forced-model and effort limits",
            "A forced model or a cap below the pinned effort stops plugin-agent delegation.",
            "The mod's pinning and blocking are the acceptance evidence, so read no settings or subagent record per "
            "delegation.",
        )

        # When
        section = implementation_section()

        # Then
        for phrase in expected:
            self.assertIn(phrase, section)

    def test_worker나_기록이_없으면_위임을_멈추고_메인_대체_처리를_쓴다(self):
        """플러그인 worker나 실제 모델 기록이 없으면 위임을 멈추고 공통 대체 처리를 적용한다."""
        # Given
        blocker = "A missing plugin worker or a missing subagent record stops the affected delegation."

        # When
        section = implementation_section()

        # Then
        self.assertIn(blocker, section)
        self.assertIn("Apply the session fallback.", section)

    def test_호스트_한도는_메인_세션을_빼고_세며_바꾸지_않는다(self):
        """Claude 동시 실행 한도는 실행 중인 서브에이전트만 세고 조정자는 그 값을 바꾸지 않는다."""
        # Given
        limit = "`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, which counts running subagents but not the main session"

        # When
        section = implementation_section()

        # Then
        self.assertIn(limit, section)
        self.assertIn("never change it", section)

    def test_역할_실행기는_종료_코드별_처리와_역할별_대체_경로를_정한다(self):
        """역할 실행기 호출은 Source directory 줄을 쓰고 종료 코드 0, 2, 3, 4를 처리하며 역할마다 대체 경로를 정한다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        section = " ".join(text.split("## Role runner", 1)[1].split("## Investigation", 1)[0].split())

        # Then
        self.assertIn(
            "python3 <Source directory>/scripts/role_runner.py <scout|researcher|reviewer|worker> --assignment <file> "
            "--result <file>",
            section,
        )
        self.assertIn("where `<Source directory>` is the line in the session context", section)
        self.assertIn("Never run `cd` before it.", section)
        self.assertIn(
            "Add `--model <id>` only for `reviewer` and `--add-dir <dir>` only for `worker`, a writing capability, or a `write` agent.",
            section,
        )
        for row in (
            "| 0 | Accept the result file. |",
            "| 2 | Fix the call and run it again. |",
            "| 3 or 4 | Read no result file and use the fallback below. |",
            "| `scout` | `hei5enbug-agent-setup:scout` |",
            "| `researcher` | `hei5enbug-agent-setup:scout`, only when public search and fetch tools are available |",
            "| `reviewer` for a skill review role | `hei5enbug-agent-setup:reviewer` |",
            "| `reviewer` for independent validation | None. Report that independent validation was not performed. |",
            "| `worker` | Inspect the partial diff, then `hei5enbug-agent-setup:worker` |",
        ):
            self.assertIn(row, section)

    def test_조사는_scout_역할과_investigation_기능_경로로_실행한다(self):
        """범위가 한정된 조사는 scout 역할, 공개 조사는 investigation 기능 경로로 실행하고 결과는 단서로만 쓴다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        investigation = " ".join(text.split("## Investigation", 1)[1].split("## Skill workers", 1)[0].split())

        # Then
        for phrase in (
            "run the `scout` role. Give each scout one question and one narrow search scope.",
            "Require file paths, code symbols, and concrete evidence in its results.",
            "Treat results as leads.",
            "use the `investigation` capability's route in the capability table.",
            "Its Claude fallback is the `scout` agent, which has web search and fetch tools.",
        ):
            self.assertIn(phrase, investigation)
        self.assertNotIn("codex exec", investigation)

    def test_내장_서브에이전트는_예외_둘을_빼고_금지하고_차단_훅을_가리킨다(self):
        """내장 서브에이전트 이름과 fork는 금지하되 claude-code-guide와 statusline-setup만 예외로 두고, 종류를 비우는 호출도 막는다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        built_in = " ".join(text.split("## Built-in subagents", 1)[1].split("## Investigation", 1)[0].split())

        # Then
        forbidden, exceptions = built_in.split("The exceptions are", 1)
        for name in ("`general-purpose`", "`Explore`", "`Plan`", "`claude`", "a fork"):
            self.assertIn(name, forbidden)
        for name in ("`claude-code-guide`", "`statusline-setup`"):
            self.assertNotIn(name, forbidden)
            self.assertIn(name, exceptions.split("Always name", 1)[0])
        self.assertIn("Always name the subagent type, because an omitted type runs `general-purpose`.", built_in)
        self.assertIn(
            "The plugin's agent guard hook denies an omitted type and every built-in type except those two exceptions",
            built_in,
        )

    def test_스킬_검토와_독립_검증은_검토_모델_줄의_reviewer를_쓴다(self):
        """스킬 검토 역할은 Review model 줄의 모델로 reviewer 역할을 실행하고, 독립 검증은 승인 뒤 같은 역할로 실행한다."""
        # Given
        text = CLAUDE_AGENTS.read_text(encoding="utf-8")

        # When
        skill_workers = " ".join(text.split("## Skill workers", 1)[1].split("## Implementation", 1)[0].split())

        # Then
        self.assertIn("A skill review role is read-only judgment work", skill_workers)
        self.assertIn(
            'Run the `reviewer` role with `--model` set to the model in the session line "Review model".',
            skill_workers,
        )
        self.assertIn(
            "Independent validation, once its confirmation gate passes under independent model validation, runs the "
            "`reviewer` role with `--model` set to the reviewer that file selects.",
            skill_workers,
        )
        self.assertIn("Send a local-evidence research ticket or bounded public research through the `investigation` capability.", skill_workers)
        self.assertIn("Do not use `scout` for a review role.", skill_workers)
        self.assertIn("trial execution and other non-review participants use the host's upper model", skill_workers)
        self.assertIn("run a separate `claude -p` process with the", skill_workers)
        self.assertNotIn("findings only", skill_workers.lower())
        self.assertNotIn("review round", skill_workers)

    def test_공유_라우팅을_먼저_읽고_GPT_전환_설명은_공유_라우팅에만_둔다(self):
        """공유 라우팅을 필요한 호출 전에 읽게 하고, 메인 모델 전환 설명은 공유 라우팅 한 곳에만 둔다."""
        # Given
        text = " ".join(CLAUDE_AGENTS.read_text(encoding="utf-8").split())
        routing = " ".join((REPO_ROOT / "instructions/model-routing.md").read_text(encoding="utf-8").split())

        # When
        reads_routing = "Read [shared model routing](model-routing.md) before dispatching" in text

        # Then
        self.assertTrue(reads_routing)
        self.assertIn("Other dispatches need only this file.", text)
        self.assertNotIn("Selecting GPT as Claude Code's main model", text)

    def test_대체는_다른_계열이고_호스트_밖이면_역할_실행기로_가며_옛_대체_고정은_남기지_않는다(self):
        """Claude Code 대체 절은 좁힌 대체 규칙과 agent 모드 명령을 알리고, 같은 계열 대체 핀과 빈 대체 거부 문구를 남기지 않는다."""
        # Given
        narrowed = (
            "Every fallback is the other model family; a fallback that needs the other host's model runs through the role "
            "runner, and one the current host can run in-host uses the named agent."
        )
        text = " ".join(CLAUDE_AGENTS.read_text(encoding="utf-8").split())
        routing = " ".join((REPO_ROOT / "instructions/model-routing.md").read_text(encoding="utf-8").split())
        readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())

        # When
        fallback = text.split("## Fallback", 1)[1].split("## Investigation", 1)[0]

        # Then
        self.assertIn(narrowed, fallback)
        self.assertIn(narrowed, routing)
        self.assertIn(narrowed, readme)
        self.assertIn("`role_runner.py agent --name <name> --fallback`", fallback)
        self.assertIn("On runner exit 3 or 4, continue in the main conversation.", fallback)
        self.assertIn("is denied once, naming the runner fallback command", text)
        self.assertNotIn("fallback pin", text)
        self.assertNotIn("is denied when there is none", text)


if __name__ == "__main__":
    unittest.main()
