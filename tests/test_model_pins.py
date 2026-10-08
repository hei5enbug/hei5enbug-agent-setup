"""Model pin checks.

Runtime files name models only by the full IDs in PINS. Repository development updates PINS to each family's
newest generally available release, and these checks then report every stale runtime reference.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

PINS = {
    "claude-fable": "claude-fable-5-1",
    "claude-opus": "claude-opus-5-5",
    "claude-sonnet": "claude-sonnet-5-5",
    "claude-haiku": "claude-haiku-5-5",
    "gpt-astra": "gpt-6-astra",
    "gpt-luna": "gpt-6-luna",
    "gpt-sol": "gpt-6.1-sol",
}

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
DEV_ONLY = {"AGENTS.md", "AGENTS.ko.md", "CLAUDE.md", "CLAUDE.ko.md"}
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


class ModelPinTest(unittest.TestCase):
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
                "researcher.md": PINS["claude-haiku"],
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
            "codex-researcher.toml": (
                "researcher", "xhigh",
                f"Pass `{PINS['gpt-luna']}` and `xhigh` explicitly on every researcher spawn;",
            ),
            "codex-designer.toml": (
                "designer", "xhigh",
                f"spawn the plugin `designer` role with `{PINS['gpt-astra']}` and `xhigh` instead.",
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


if __name__ == "__main__":
    unittest.main()
