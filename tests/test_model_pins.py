"""Model pin checks.

Runtime files name models only by the full IDs in PINS. Repository development refreshes unpinned families
to the newest generally available release. Explicit user selections keep their chosen release; these checks
report every mismatched runtime reference.
"""

from __future__ import annotations

import json
import re
from datetime import date
import subprocess
import tomllib
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

REGISTRY = json.loads((REPO_ROOT / "config" / "model-registry.json").read_text(encoding="utf-8"))
PINS = REGISTRY["pins"]

PINS_VERIFIED_ON = "2026-10-12"

MODEL_ID = re.compile(
    r"\b(?P<id>claude-(?P<claude>fable|opus|sonnet|haiku)-\d+(?:-\d+)*"
    r"|gpt-\d+(?:\.\d+)?-(?P<gpt>[a-z]+))\b"
)
DISPLAY_VERSION = re.compile(r"\b(?:Fable|Opus|Sonnet|Haiku) \d|\bGPT-\d")
RUNTIME_LOOKUP = re.compile(
    r"latest production|latest available|newest production|resolved at execution time|resolved for each run",
    re.IGNORECASE,
)
EXCLUDED_DIR = re.compile(r"(^|/)(tests|evals)/")
DEV_ONLY = {"AGENTS.md", "docs/ko/AGENTS.ko.md"}
TEXT_SUFFIXES = {".md", ".json", ".toml", ".py", ".mjs", ".js", ".sh", ".yml", ".yaml", ".html", ".txt"}


def runtime_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    return [
        REPO_ROOT / name
        for name in listed
        if Path(name).suffix in TEXT_SUFFIXES
        and name not in DEV_ONLY
        and not EXCLUDED_DIR.search(name)
        and (REPO_ROOT / name).is_file()
    ]


def lines_of(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        yield f"{path.relative_to(REPO_ROOT)}:{number}", line


def frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


ROUTING = REPO_ROOT / "instructions" / "model-routing.md"
CAPABILITY_HEADING = "## Capability pins"
TABLE_SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")


def registry_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from registry_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from registry_strings(item)
    elif isinstance(value, str):
        yield value


def agent_entries(section: str):
    for name, entry in REGISTRY[section].items():
        yield f"{section}.{name}", entry["model"], entry["effort"]
        if "fallback" in entry:
            yield f"{section}.{name}.fallback", entry["fallback"]["model"], entry["fallback"]["effort"]


def registry_entries():
    for capability, hosts in REGISTRY["capabilities"].items():
        for host, slots in hosts.items():
            for slot, entry in slots.items():
                yield f"capabilities.{capability}.{host}.{slot}", entry["model"], entry["effort"]
    yield from agent_entries("claude_agents")
    yield from agent_entries("codex_agents")
    yield "runner", REGISTRY["runner"]["role_model"], REGISTRY["runner"]["effort"]


def model_family(model: str) -> str:
    return "claude" if model.startswith("claude-") else "gpt"


def capability_cell(entry: dict) -> str:
    suffix = " (runner)" if entry["via"] == "runner" else ""
    if entry["via"] == "agent":
        suffix = f" (`{entry['agent'].split(':')[-1]}`)"
    return f"`{entry['model']}` / `{entry['effort']}`{suffix}"


def expected_capability_rows() -> list[list[str]]:
    header = ["Capability", "Claude Code primary", "Claude Code fallback", "Codex primary", "Codex fallback"]
    rows = [
        [
            name,
            capability_cell(hosts["claude"]["primary"]),
            capability_cell(hosts["claude"]["fallback"]),
            capability_cell(hosts["codex"]["primary"]),
            capability_cell(hosts["codex"]["fallback"]),
        ]
        for name, hosts in REGISTRY["capabilities"].items()
    ]
    return [header, *rows]


def capability_table_rows(text: str) -> list[list[str]]:
    section = text.split(CAPABILITY_HEADING, 1)[1].split("\n## ", 1)[0]
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in lines
        if not TABLE_SEPARATOR.fullmatch(line)
    ]


class ModelPinTest(unittest.TestCase):
    def test_최신_모델_확인일은_미래가_아닌_ISO_날짜다(self):
        """마지막 최신 모델 확인일은 ISO 형식이고 오늘보다 늦지 않다."""
        # Given
        value = PINS_VERIFIED_ON

        # When
        verified = date.fromisoformat(value)

        # Then
        self.assertLessEqual(verified, date.today())

    def test_실행_파일의_모델_ID는_모두_고정값과_같다(self):
        """테스트와 평가 입력을 뺀 모든 추적 파일의 모델 ID는 계열별 고정값과 정확히 같다."""
        # Given
        files = runtime_files()

        # When
        stale = []
        for path in files:
            for where, line in lines_of(path):
                for match in MODEL_ID.finditer(line):
                    family = f"claude-{match['claude']}" if match["claude"] else f"gpt-{match['gpt']}"
                    if PINS.get(family) != match["id"]:
                        stale.append(f"{where}: {match['id']} (pin: {PINS.get(family, 'none')})")

        # Then
        self.assertEqual([], stale)

    def test_모든_고정값은_실행_파일에서_쓰인다(self):
        """사용하지 않는 계열이 고정값 목록에 남아 있지 않다."""
        # Given
        text = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files())

        # When
        unused = [model for model in PINS.values() if model not in text]

        # Then
        self.assertEqual([], unused)

    def test_실행_파일은_표시_이름으로_모델_버전을_지정하지_않는다(self):
        """버전은 전체 모델 ID로만 적고 Sonnet 5 같은 표시 이름 버전을 쓰지 않는다."""
        # Given
        files = runtime_files()

        # When
        found = [where for path in files for where, line in lines_of(path) if DISPLAY_VERSION.search(line)]

        # Then
        self.assertEqual([], found)

    def test_실행_파일은_실행_시점의_최신_모델_조회를_요구하지_않는다(self):
        """실행 규칙은 고정 ID만 쓰고 실행할 때 최신 모델을 다시 찾지 않는다."""
        # Given
        files = runtime_files()

        # When
        found = [where for path in files for where, line in lines_of(path) if RUNTIME_LOOKUP.search(line)]

        # Then
        self.assertEqual([], found)

    def test_Claude_에이전트_정의는_전체_모델_ID를_고정한다(self):
        """플러그인 에이전트 정의는 별칭이 아니라 고정된 전체 모델 ID를 쓴다."""
        # Given
        definitions = sorted((REPO_ROOT / "agents").glob("*.md"))

        # When
        models = {path.name: frontmatter(path)["model"] for path in definitions}

        # Then
        self.assertEqual(
            {
                "scout.md": PINS["claude-sonnet"],
                "worker.md": PINS["claude-haiku"],
                "sonnet-worker.md": PINS["claude-sonnet"],
                "designer.md": PINS["claude-opus"],
                "reviewer.md": PINS["claude-opus"],
            },
            models,
        )

    def test_Codex_역할_파일은_모델을_지정하지_않는다(self):
        """훅은 설치된 역할 파일을 덮어쓰지 않으므로, 고정 모델은 지침이 생성할 때마다 넘기고 역할 파일에는 두지 않는다."""
        # Given
        rules = " ".join((REPO_ROOT / "instructions/codex-agents.md").read_text(encoding="utf-8").split())
        expected = {
            "codex-scout.toml": ("scout", "xhigh", f"Pass `{PINS['gpt-luna']}` and `xhigh` explicitly on every spawn."),
            "codex-worker.toml": ("worker", "xhigh", f"pass the pinned `{PINS['gpt-luna']}` and `xhigh` explicitly on every spawn."),
            "codex-designer.toml": (
                "designer", "xhigh",
                f"the plugin `designer` role with `{PINS['gpt-astra']}` and `xhigh` passed explicitly",
            ),
            "codex-reviewer.toml": (
                "reviewer", "xhigh",
                f"spawn the plugin `reviewer` role with `{PINS['gpt-sol']}` and `xhigh` passed explicitly.",
            ),
        }

        for bundled, (name, effort, spawn_rule) in expected.items():
            with self.subTest(bundled=bundled):
                # When
                definition = tomllib.loads((REPO_ROOT / "standalone-agents" / bundled).read_text(encoding="utf-8"))

                # Then
                self.assertEqual(name, definition["name"])
                self.assertNotIn("model", definition)
                self.assertEqual(effort, definition["model_reasoning_effort"])
                self.assertIn(spawn_rule, rules)

    def test_레지스트리의_모델_ID는_모두_pins_값이다(self):
        """레지스트리 안의 모든 모델 ID는 pins의 값과 정확히 같다."""
        # Given
        values = set(PINS.values())

        # When
        unknown = sorted({text for text in registry_strings(REGISTRY) if MODEL_ID.fullmatch(text) and text not in values})

        # Then
        self.assertEqual([], unknown)

    def test_레지스트리의_사고_강도는_모두_efforts_안에_있다(self):
        """capability, Claude 에이전트, 실행기와 효과 규칙의 사고 강도는 모두 efforts에 있다."""
        # Given
        efforts = set(REGISTRY["efforts"])
        used = [(where, effort) for where, _, effort in registry_entries()]
        used += [
            (f"effort_rules.{model}", effort)
            for model, allowed in REGISTRY["effort_rules"].items()
            for effort in allowed
        ]

        # When
        unknown = [f"{where}: {effort}" for where, effort in used if effort not in efforts]

        # Then
        self.assertEqual([], unknown)

    def test_효과_규칙은_capability_에이전트_실행기_항목에서_지켜진다(self):
        """효과 규칙이 있는 모델은 모든 항목에서 규칙에 허용된 사고 강도만 쓴다."""
        # Given
        rules = REGISTRY["effort_rules"]

        # When
        violations = [
            f"{where}: {model} / {effort}"
            for where, model, effort in registry_entries()
            if model in rules and effort not in rules[model]
        ]

        # Then
        self.assertEqual([], violations)

    def test_Claude_에이전트_정의는_레지스트리의_claude_agents와_같다(self):
        """agents 폴더의 정의마다 claude_agents 항목이 있고 model과 effort가 그 항목과 같다."""
        # Given
        definitions = sorted((REPO_ROOT / "agents").glob("*.md"))

        # When
        observed = {}
        for path in definitions:
            meta = frontmatter(path)
            observed[f"hei5enbug-agent-setup:{path.stem}"] = (meta["model"], meta["effort"])
        expected = {name: (entry["model"], entry["effort"]) for name, entry in REGISTRY["claude_agents"].items()}

        # Then
        self.assertEqual(expected, observed)

    def test_모델_라우팅의_기능별_고정값_표는_레지스트리와_같다(self):
        """model-routing.md의 Capability pins 표는 레지스트리 capabilities와 행마다 같다."""
        # Given
        text = ROUTING.read_text(encoding="utf-8")

        # When
        rows = capability_table_rows(text)

        # Then
        self.assertEqual(expected_capability_rows(), rows)

    def test_agent로_실행하는_기능_항목은_가리킨_pin의_모델과_effort와_같다(self):
        """via가 agent인 기능 항목은 같은 호스트의 에이전트를 가리키고, pin이 고른 모델과 effort가 항목과 같다."""
        # Given
        agents = {"claude": REGISTRY["claude_agents"], "codex": REGISTRY["codex_agents"]}
        entries = [
            (f"capabilities.{capability}.{host}.{slot}", host, entry)
            for capability, hosts in REGISTRY["capabilities"].items()
            for host, slots in hosts.items()
            for slot, entry in slots.items()
            if entry["via"] == "agent"
        ]

        # When
        problems = []
        for where, host, entry in entries:
            agent = agents[host].get(entry.get("agent"))
            if agent is None:
                problems.append(f"{where}: unknown agent {entry.get('agent')!r}")
                continue
            pin = {"primary": agent, "fallback": agent.get("fallback")}.get(entry.get("pin"))
            if pin is None or (pin["model"], pin["effort"]) != (entry["model"], entry["effort"]):
                problems.append(f"{where}: {entry.get('agent')} {entry.get('pin')} does not match")

        # Then
        self.assertEqual([], problems)

    def test_모든_대체_항목은_기본과_다른_모델_계열이다(self):
        """에이전트와 기능의 fallback은 기본 항목과 다른 계열(claude-와 gpt-)의 모델만 쓴다."""
        # Given
        pairs = [
            (f"claude_agents.{name}", entry["model"], entry["fallback"]["model"])
            for name, entry in REGISTRY["claude_agents"].items()
        ] + [
            (f"codex_agents.{name}", entry["model"], entry["fallback"]["model"])
            for name, entry in REGISTRY["codex_agents"].items()
            if "fallback" in entry
        ] + [
            (f"capabilities.{capability}.{host}", slots["primary"]["model"], slots["fallback"]["model"])
            for capability, hosts in REGISTRY["capabilities"].items()
            for host, slots in hosts.items()
        ]

        # When
        same_family = [where for where, primary, fallback in pairs if model_family(primary) == model_family(fallback)]

        # Then
        self.assertEqual([], same_family)

    def test_에이전트의_access는_read_또는_write이다(self):
        """Claude와 Codex 에이전트의 access는 read 또는 write 가운데 하나다."""
        # Given
        entries = {**REGISTRY["claude_agents"], **REGISTRY["codex_agents"]}

        # When
        invalid = [name for name, entry in entries.items() if entry.get("access") not in {"read", "write"}]

        # Then
        self.assertEqual([], invalid)

    def test_에이전트의_대체_항목은_모두_역할_실행기로_기록된다(self):
        """에이전트의 fallback은 모두 via가 runner인 항목이다."""
        # Given
        fallbacks = [
            entry["fallback"]
            for entry in [*REGISTRY["claude_agents"].values(), *REGISTRY["codex_agents"].values()]
            if "fallback" in entry
        ]

        # When
        vias = [fallback.get("via") for fallback in fallbacks]

        # Then
        self.assertEqual(["runner"] * len(fallbacks), vias)

    def test_토론_상대는_대체_항목이_없다(self):
        """tiki-taka 상대 항목은 fallback이 없어서 상대가 실패하면 토론이 멈춘다."""
        # Given
        opponents = REGISTRY["opponents"]

        # When
        with_fallback = [name for name, entry in opponents.items() if isinstance(entry, dict) and "fallback" in entry]

        # Then
        self.assertEqual([], with_fallback)


if __name__ == "__main__":
    unittest.main()
