"""A skill that a worker assignment names is loaded, listed in the result, and checked against the host record."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "scripts" / "verify_skill_load.py"
DELEGATION = REPO_ROOT / "instructions/implementation-delegation.md"
EXECUTION = REPO_ROOT / "instructions/implementation-execution.md"
ROLES = (REPO_ROOT / ".codex/agents/worker.toml", REPO_ROOT / "standalone-agents/codex-worker.toml")
CLAUDE_WORKERS = ("worker", "sonnet-worker")


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def section(text: str, heading: str) -> str:
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def claude_entry(*tool_uses: tuple[str, dict]) -> dict:
    content = [{"type": "tool_use", "id": f"t{index}", "name": name, "input": data} for index, (name, data) in enumerate(tool_uses)]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def codex_entry(command: str) -> dict:
    return {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": [command]})}}


class SkillLoadInstructionTest(unittest.TestCase):
    def test_위임_규칙은_이름_명시와_로드_의무와_결과_기재와_기록_확인을_정한다(self):
        """이름이 붙은 skill에 대해 할당이 이름과 로드를 지시하고, worker가 로드하고 결과에 적고 없으면 멈추며, 조정자가 기록으로 수용을 판단한다."""
        # Given
        text = " ".join(DELEGATION.read_text(encoding="utf-8").split())

        # When
        assignments = " ".join(section(DELEGATION.read_text(encoding="utf-8"), "Worker assignments").split())
        worker = " ".join(section(DELEGATION.read_text(encoding="utf-8"), "Assigned workers").split())
        review = " ".join(section(DELEGATION.read_text(encoding="utf-8"), "Review and integration").split())

        # Then
        self.assertIn("the assignment states the skill's name and tells the worker to load it", assignments)
        self.assertIn("An assignment that names no skill adds nothing about skills.", assignments)
        self.assertIn("load it first with the host's skill mechanism and follow it", worker)
        self.assertIn("make no edit the skill covers, and report the missing skill as a blocker", worker)
        self.assertIn("`Skills loaded:` line of the result", worker)
        self.assertIn("scripts/verify_skill_load.py", review)
        self.assertIn("do not accept the result", review)
        self.assertTrue(text.rstrip().endswith("remaining blockers."))

    def test_할당_필드는_이름이_붙은_skill을_포함한다(self):
        """할당 필드 목록에 작업이 이름 붙인 skill 항목이 있다."""
        # Given
        text = section(EXECUTION.read_text(encoding="utf-8"), "Assignment fields")

        # When
        rows = [line for line in text.splitlines() if line.startswith("- The skill the task names")]

        # Then
        self.assertEqual(1, len(rows))
        self.assertIn("which the worker loads first and lists as loaded in its result", rows[0])

    def test_Codex_worker_역할과_독립_정의는_skill_로드_의무를_말한다(self):
        """두 Codex worker 정의 중 하나라도 이름이 붙은 skill의 로드, 없으면 정지, 결과 기재를 빠뜨리면 실패한다."""
        for path in ROLES:
            with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                # When
                text = normalized(path)

                # Then
                self.assertIn("When the assignment names a skill, load it first with the host's skill mechanism", text)
                self.assertIn("make no edit the skill covers, and report the missing skill as a blocker", text)
                self.assertIn("`Skills loaded:` line", text)

    def test_Claude_worker_정의는_의무를_복사하지_않고_Assigned_workers를_가리킨다(self):
        """Claude worker 정의는 skill 의무를 복사하지 않고 Assigned workers 규칙을 가리킨다."""
        for name in CLAUDE_WORKERS:
            with self.subTest(name=name):
                # When
                text = normalized(REPO_ROOT / f"agents/{name}.md")

                # Then
                self.assertIn('Follow the "Assigned workers" rules', text)
                self.assertNotIn("Skills loaded", text)


class VerifySkillLoadTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def record(self, entries: list[dict]) -> Path:
        return self.write("record.jsonl", "\n".join(json.dumps(entry) for entry in entries) + "\n")

    def run_check(self, *skills: str, record: Path | None = None, result: Path | None = None):
        command = [sys.executable, str(VERIFY)]
        for skill in skills:
            command += ["--skill", skill]
        if record is not None:
            command += ["--record", str(record)]
        if result is not None:
            command += ["--result", str(result)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
        return completed.returncode, json.loads(completed.stdout.strip().splitlines()[-1])

    def test_셸_명령만_있고_로드가_없는_기록은_수용하지_않는다(self):
        """skill 이름이 붙은 할당의 기록에 셸 명령만 있고 로드가 없으면, 결과가 이름을 적었어도 종료 코드 4다."""
        # Given
        record = self.record([claude_entry(("Bash", {"command": "ls"})), codex_entry("grep -r demo src")])
        result = self.write("result.txt", "Done.\nSkills loaded: demo-skill\n")

        # When
        code, status = self.run_check("demo-skill", record=record, result=result)

        # Then
        self.assertEqual(4, code)
        self.assertEqual(["demo-skill"], status["no_load_in_record"])

    def test_Claude_기록에_Skill_호출이_있고_결과가_이름을_적으면_수용한다(self):
        """Claude 기록에 플러그인 접두사가 붙은 Skill 호출이 있고 결과의 Skills loaded 줄이 이름을 적으면 종료 코드 0이다."""
        # Given
        record = self.record([claude_entry(("Skill", {"skill": "demo-plugin:demo-skill"}), ("Bash", {"command": "ls"}))])
        result = self.write("result.txt", "Done.\nSkills loaded: `demo-skill`\n")

        # When
        code, status = self.run_check("demo-skill", record=record, result=result)

        # Then
        self.assertEqual((0, True), (code, status["accepted"]))

    def test_Codex_기록에서_SKILL_md_읽기는_로드로_인정한다(self):
        """Codex 기록에 해당 skill의 SKILL.md를 읽는 호출이 있으면 로드로 인정하고, 다른 skill의 SKILL.md는 인정하지 않는다."""
        # Given
        record = self.record([codex_entry("sed -n 1,80p /plugin/skills/demo-skill/SKILL.md"), codex_entry("cat /plugin/skills/other/SKILL.md")])
        result = self.write("result.txt", "Skills loaded: demo-skill, other-skill\n")

        # When
        code, status = self.run_check("demo-skill", "other-skill", record=record, result=result)

        # Then
        self.assertEqual((4, ["other-skill"]), (code, status["no_load_in_record"]))

    def test_기록에_로드가_있어도_결과가_나열하지_않으면_수용하지_않는다(self):
        """기록에 로드가 있어도 결과에 Skills loaded 줄이 없거나 이름을 빠뜨리면 종료 코드 4다."""
        # Given
        record = self.record([claude_entry(("Skill", {"skill": "demo-skill"}))])
        result = self.write("result.txt", "Done. I used demo-skill.\n")

        # When
        code, status = self.run_check("demo-skill", record=record, result=result)

        # Then
        self.assertEqual((4, ["demo-skill"]), (code, status["not_listed_in_result"]))

    def test_skill을_이름으로_부르지_않은_할당은_수용이_바뀌지_않는다(self):
        """skill 이름이 없으면 기록과 결과가 무엇이든 확인할 것이 없어 종료 코드 0이고, 결과에도 skill 줄을 요구하지 않는다."""
        # Given
        record = self.record([codex_entry("ls")])
        result = self.write("result.txt", "Done.\n")

        # When
        code, status = self.run_check(record=record, result=result)

        # Then
        self.assertEqual((0, []), (code, status["checked"]))

    def test_기록이_없는_호스트는_결과의_나열만_확인한다(self):
        """기록을 두지 않는 호스트에서는 기록 확인을 건너뛰되 결과가 이름을 나열하지 않으면 거부한다."""
        # Given
        listed = self.write("listed.txt", "Skills loaded: demo-skill\n")
        silent = self.write("silent.txt", "Done.\n")

        # When
        accepted = self.run_check("demo-skill", result=listed)
        rejected = self.run_check("demo-skill", result=silent)

        # Then
        self.assertEqual((0, 4), (accepted[0], rejected[0]))


if __name__ == "__main__":
    unittest.main()
