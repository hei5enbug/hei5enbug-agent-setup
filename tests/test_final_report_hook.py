"""Stop hook that blocks a final report after a change when no text review checked it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "final_report_hook.py"
sys.path.insert(0, str(SCRIPTS))
from text_review import report_digest  # noqa: E402

REPORT = "The change is done and the checks pass. " * 12
REVIEW = "python3 /home/test/plugin/scripts/text_review.py review --kind final-report --draft /tmp/work/report.md"
CHECK = "python3 /home/test/plugin/scripts/text_review.py check --kind final-report /tmp/work/report.md"


def entry(kind: str, message: dict, **extra) -> str:
    return json.dumps({"type": kind, "isSidechain": False, "message": message, **extra}, separators=(",", ":"))


def feedback_entry(reason: str) -> str:
    attachment = {"type": "hook_additional_context", "content": [reason], "hookName": "Stop", "hookEvent": "Stop"}
    return json.dumps({"type": "attachment", "attachment": attachment}, separators=(",", ":"))


def prompt(text: str = "do the task") -> str:
    return entry("user", {"role": "user", "content": text})


def assistant(*blocks: dict) -> str:
    return entry("assistant", {"id": "m1", "role": "assistant", "content": list(blocks)})


def tool(name: str, tool_id: str = "t1", **tool_input) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def edit() -> dict:
    return tool("Edit", file_path="/tmp/work/a.py", old_string="a", new_string="b")


def bash(command: str, tool_id: str = "t1") -> dict:
    return tool("Bash", tool_id, command=command)


def digest_output(draft: str, suffix: str = '\nexit=0') -> str:
    return json.dumps({"stage": "review", "findings": [], "final_report_sha256": report_digest(draft)}) + suffix


def result(tool_id: str, content) -> str:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    return entry("user", {"role": "user", "content": [block]})


class FinalReportHookTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.transcript = Path(directory.name) / "session.jsonl"

    def write(self, *lines: str) -> None:
        self.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_hook(self, stdin: str | None = None, env: dict | None = None, **event) -> subprocess.CompletedProcess:
        payload = {
            "hook_event_name": "Stop", "session_id": "s1", "transcript_path": str(self.transcript),
            "stop_hook_active": False, "last_assistant_message": REPORT, **event,
        }
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith(("HEI5ENBUG_", "ORCA_"))
        }
        environment.update(env or {})
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], input=json.dumps(payload) if stdin is None else stdin,
            capture_output=True, text=True, env=environment, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def assert_blocks(self, result: subprocess.CompletedProcess) -> dict:
        output = json.loads(result.stdout)
        self.assertNotIn("decision", output)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "Stop")
        return {"reason": specific["additionalContext"]}

    def assert_passes(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.stdout, "")

    def test_파일을_바꾼_턴이_검토_없이_긴_보고로_끝나면_한_번_막는다(self):
        # Given
        self.write(prompt(), assistant(edit()), assistant({"type": "text", "text": REPORT}))
        # When
        output = self.assert_blocks(self.run_hook())
        # Then
        self.assertIn("text_review.py review --kind final-report", output["reason"])
        self.assertIn("instructions/shared-text.md", output["reason"])
        self.assertLessEqual(output["reason"].count(". "), 3)

    def test_파이썬_heredoc으로_파일을_쓴_뒤_긴_보고를_보내면_막는다(self):
        # Given
        command = "python3 - <<'EOF'\nfrom pathlib import Path\nPath(\"notes/a.md\").write_text(\"# Demo\\n\")\nEOF"
        self.write(prompt(), assistant(bash(command)))
        # When
        output = self.assert_blocks(self.run_hook())
        # Then
        self.assertIn("text_review.py review --kind final-report", output["reason"])

    def test_커밋만_한_턴도_막는다(self):
        self.write(prompt(), assistant(bash("git -C /tmp/work commit -m 'fix: demo'")))
        self.assert_blocks(self.run_hook())

    def test_커밋이_아닌_명령만_실행한_턴은_통과한다(self):
        self.write(prompt(), assistant(bash("git status && echo commit")))
        self.assert_passes(self.run_hook())

    def test_턴이_최종_보고_검토를_실행했으면_통과한다(self):
        self.write(prompt(), assistant(edit()), assistant(bash(REVIEW)))
        self.assert_passes(self.run_hook())

    def test_다른_종류의_글만_검토하고_최종_보고는_검토하지_않았으면_막는다(self):
        # Given
        document = "python3 /home/test/plugin/scripts/text_review.py review --kind shared-document --draft README.md"
        self.write(prompt(), assistant(edit()), assistant(bash(document)))
        # When
        output = self.assert_blocks(self.run_hook())
        # Then
        self.assertIn("text_review.py review --kind final-report", output["reason"])

    def test_세션_기록에_읽을_수_없는_줄이_있으면_통과한다(self):
        self.write(prompt("earlier task"), assistant(edit()), '{"type": "user", "message": {"role": "user", "content": "lat')
        self.assert_passes(self.run_hook())

    def test_턴이_최종_보고_검사를_실행했으면_통과한다(self):
        self.write(prompt(), assistant(edit()), assistant(bash(CHECK)))
        self.assert_passes(self.run_hook())

    def test_다른_종류의_검사만_실행했으면_막는다(self):
        self.write(prompt(), assistant(edit()), assistant(bash(CHECK.replace("final-report", "other"))))
        self.assert_blocks(self.run_hook())

    def test_본문을_쓰는_셸_명령으로_문서를_만든_턴도_막는다(self):
        # Given
        command = "mkdir -p out; cat > out/wiki-page.md <<'EOF'\n# Demo page\n> quoted line\nbody line\nEOF"
        self.write(prompt(), assistant(bash(command)))
        # When
        output = self.assert_blocks(self.run_hook())
        # Then
        self.assertIn("with its own --kind", output["reason"])

    def test_셸이_파일을_쓰는_다른_방법도_막는다(self):
        commands = (
            "printf 'x' >> docs/notes.md",
            "echo x | tee out/a.txt",
            "echo x | tee -a out/a.txt > /dev/null",
            "sed -i '' 's/a/b/' README.md",
            "sed -i.bak -e 's/a/b/' README.md",
            "perl -pi -e 's/a/b/' README.md",
            "echo x 1> out/a.txt",
            "echo x >| out/a.txt",
            "echo x &> out/a.txt",
        )
        for command in commands:
            with self.subTest(command=command):
                self.write(prompt(), assistant(bash(command)))
                self.assert_blocks(self.run_hook())

    def test_변수나_임시_폴더에_쓰는_셸_명령은_통과한다(self):
        commands = (
            "D=$(mktemp -d)\ncat > \"$D/report.md\" <<'EOF'\nbody\nEOF",
            "git diff > /tmp/work/change.patch",
            "ls 2>&1 >/dev/null",
            "echo x | tee /dev/stderr",
            "echo x > ~/note.txt",
            "echo x | tee /private/tmp/a.txt",
            "echo x > /var/folders/ab/cd/a.txt",
            "D=$(mktemp -d)\ncat > \"$D/x.md\" <<EOF\n# Title\n> quoted line\nEOF",
            "cat <<-'EOF' > $D/x.md\n\t> quoted line\n\tEOF",
            "grep -c '>' README.md",
            "grep -n \"a > b\" README.md",
            "cat <<< 'a > b'",
            "sed 's/a/b/' README.md",
            "echo x # > out/a.txt",
            "echo 'unterminated > out/a.txt",
        )
        for command in commands:
            with self.subTest(command=command):
                self.write(prompt(), assistant(bash(command)))
                self.assert_passes(self.run_hook())

    def test_쓰기_하위_에이전트에_맡긴_턴도_막는다(self):
        for agent_input in ({"subagent_type": "demo-plugin:worker"}, {"subagent_type": "General-Purpose"}, {}):
            for name in ("Agent", "Task"):
                with self.subTest(name=name, agent_input=agent_input):
                    self.write(prompt(), assistant(tool(name, description="demo", prompt="do it", **agent_input)))
                    output = self.assert_blocks(self.run_hook())
                    self.assertIn("text_review.py review --kind final-report", output["reason"])

    def test_읽기_전용_하위_에이전트만_쓴_턴은_통과한다(self):
        for agent_type in ("demo-plugin:scout", "Explore", "demo-plugin:reviewer", "Plan", "claude-code-guide"):
            with self.subTest(agent_type=agent_type):
                self.write(prompt(), assistant(tool("Agent", prompt="look", subagent_type=agent_type)))
                self.assert_passes(self.run_hook())

    def test_쓰기_역할을_역할_실행기로_돌린_턴도_막는다(self):
        command = (
            "python3 /tmp/work/scripts/role_runner.py implementation --fallback --instructions a.md "
            "--assignment b.md --result c.json"
        )
        self.write(prompt(), assistant(bash(command)))
        self.assert_blocks(self.run_hook())

    def test_읽기_전용_역할을_역할_실행기로_돌린_턴은_통과한다(self):
        command = "python3 /tmp/work/scripts/role_runner.py reviewer --assignment a.md --result b.json"
        self.write(prompt(), assistant(bash(command)))
        self.assert_passes(self.run_hook())

    def test_질문으로_끝나면_통과한다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_passes(self.run_hook(last_assistant_message=REPORT + "\nShould I continue?"))

    def test_짧은_답이면_통과한다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_passes(self.run_hook(last_assistant_message="Done."))

    def test_진행_중인_백그라운드_작업이_있으면_통과한다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_passes(self.run_hook(background_tasks=[{"id": "b1"}]))

    def test_빈_백그라운드_작업_목록은_막는다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_blocks(self.run_hook(background_tasks=[]))

    def test_이번_턴에_같은_피드백을_이미_받았으면_통과한다(self):
        # Given
        told = feedback_entry("This turn changed files and ends with a final report that no text review checked.")
        self.write(prompt(), assistant(edit()), told)
        # When / Then
        self.assert_passes(self.run_hook(stop_hook_active=True))

    def test_다른_훅이_이어_간_정지에서도_검토가_없으면_한_번_이어_간다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_blocks(self.run_hook(stop_hook_active=True))

    def test_검토_요청으로_이어진_뒤_초안과_다른_보고를_보내면_한_번_더_이어_간다(self):
        # Given
        draft = "Reviewed draft of the report. " * 4
        told = feedback_entry("This turn changed files and ends with a final report that no text review checked.")
        self.write(prompt(), assistant(edit()), told, assistant(bash(REVIEW, "r1")), result("r1", digest_output(draft)))
        # When
        output = self.assert_blocks(self.run_hook(stop_hook_active=True, last_assistant_message=REPORT))
        # Then
        self.assertIn("differs from the draft", output["reason"])

    def test_초안과_다르다는_피드백을_이미_받았으면_통과한다(self):
        draft = "Reviewed draft of the report. " * 4
        told = feedback_entry("The final report differs from the draft that the last passing text review checked.")
        self.write(prompt(), assistant(edit()), assistant(bash(REVIEW, "r1")), result("r1", digest_output(draft)), told)
        self.assert_passes(self.run_hook(stop_hook_active=True, last_assistant_message=REPORT))

    def test_이전_턴의_피드백은_새_턴에_영향을_주지_않는다(self):
        told = feedback_entry("This turn changed files and ends with a final report that no text review checked.")
        self.write(prompt("earlier"), assistant(edit()), told, prompt("next task"), assistant(edit()))
        self.assert_blocks(self.run_hook())

    def test_하위_에이전트에서는_통과한다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_passes(self.run_hook(agent_id="agent-1"))

    def test_할당된_역할_세션에서는_통과한다(self):
        self.write(prompt(), assistant(edit()))
        self.assert_passes(self.run_hook(env={"HEI5ENBUG_ASSIGNED_ROLE": "worker"}))
        self.assert_passes(self.run_hook(env={"HEI5ENBUG_PARENT_SESSION": "parent-1"}))

    def test_이전_턴만_파일을_바꿨으면_통과한다(self):
        self.write(prompt("first"), assistant(edit()), prompt("second"), assistant({"type": "text", "text": REPORT}))
        self.assert_passes(self.run_hook())

    def test_이전_턴의_검토는_이번_턴의_변경을_가리지_않는다(self):
        self.write(prompt("first"), assistant(bash(REVIEW)), prompt("second"), assistant(edit()))
        self.assert_blocks(self.run_hook())

    def test_도구_결과_항목은_새_턴을_시작하지_않는다(self):
        result_block = {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}
        self.write(prompt(), assistant(edit()), entry("user", {"role": "user", "content": [result_block]}))
        self.assert_blocks(self.run_hook())

    def reviewed_turn(self, *results: tuple[str, str, object]) -> None:
        lines = [prompt(), assistant(edit())]
        for command, tool_id, content in results:
            lines += [assistant(bash(command, tool_id)), result(tool_id, content)]
        self.write(*lines)

    def test_인터프리터_스크립트로_파일을_쓴_턴도_막는다(self):
        commands = (
            "python3 - <<'EOF'\nfrom pathlib import Path\nPath(\"notes/a.md\").write_text(\"# Demo\\n\")\nEOF",
            "python3 -c \"open('out/x.txt','w').write('x')\"",
            "env FOO=1 python3.12 - <<EOF\nimport json\njson.dump({}, open('out/a.json', 'w'))\nEOF",
            "cat <<'EOF' | python3 -\nimport shutil\nshutil.copy('a.txt', 'out/b.txt')\nEOF",
            "node -e \"require('fs').writeFileSync('out/a.txt', 'x')\"",
            "ruby -e 'File.write(\"out/a.txt\", \"x\")'",
            "node <<'EOF'\nrequire('fs').appendFileSync('out/a.txt', 'x')\nEOF",
        )
        for command in commands:
            with self.subTest(command=command):
                self.write(prompt(), assistant(bash(command)))
                self.assert_blocks(self.run_hook())

    def test_인터프리터_스크립트가_읽고_출력만_하면_통과한다(self):
        commands = (
            "python3 - <<'EOF'\nfrom pathlib import Path\nprint(Path('notes/a.md').read_text())\nEOF",
            "python3 -c \"print(open('out/x.txt').read())\"",
            "python3 -c \"import sys; sys.stdout.write('x')\"",
            "python3 - <<'EOF'\nopen('out/x.txt', 'r').read()\nEOF",
            "cat <<'EOF' > $D/x.py\nPath('a').write_text('x')\nEOF",
            "grep -n 'write_text(' scripts/a.py",
            "python3 scripts/tool.py --note 'write_text('",
            "echo \"open('a.txt', 'w')\" | wc -c",
        )
        for command in commands:
            with self.subTest(command=command):
                self.write(prompt(), assistant(bash(command)))
                self.assert_passes(self.run_hook())

    def test_통과한_검토_뒤_짧은_보고가_초안과_다르면_막는다(self):
        # Given
        draft = "Reviewed draft of the report. " * 4
        sent = "Different short report after the review. " * 3
        self.assertLess(len(sent.strip()), 400)
        self.reviewed_turn((REVIEW, "r1", digest_output(draft)))
        # When
        output = self.assert_blocks(self.run_hook(last_assistant_message=sent))
        # Then
        self.assertIn("differs from the draft", output["reason"])

    def test_통과한_검토_뒤_짧은_보고가_초안과_같으면_통과한다(self):
        # Given
        draft = "Reviewed draft of the report. " * 4
        self.assertLess(len(draft.strip()), 400)
        self.reviewed_turn((REVIEW, "r1", digest_output(draft)))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=draft))

    def test_통과한_검토_뒤_짧은_질문은_통과한다(self):
        # Given
        self.reviewed_turn((REVIEW, "r1", digest_output(REPORT)))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message="Should I push the change?"))
        self.assert_passes(self.run_hook(last_assistant_message="변경을 푸시할까요？"))

    def test_검토가_없으면_짧은_보고는_통과한다(self):
        self.write(prompt(), assistant(bash("python3 -c \"open('out/x.txt','w').write('x')\"")))
        self.assert_passes(self.run_hook(last_assistant_message="Done, the file is written."))

    def test_통과한_검토의_초안과_보낸_보고가_다르면_막는다(self):
        # Given
        draft = REPORT + "Second paragraph.\n"
        self.reviewed_turn((REVIEW, "r1", digest_output(draft)))
        # When
        output = self.assert_blocks(self.run_hook(last_assistant_message=draft + "Added after the review.\n"))
        # Then
        self.assertIn("differs from the draft", output["reason"])
        self.assertLessEqual(output["reason"].count(". "), 3)

    def test_줄끝_공백과_빈_줄만_다른_보고는_통과한다(self):
        # Given
        draft = REPORT + "\n\nSecond paragraph.\n"
        self.reviewed_turn((REVIEW, "r1", digest_output(draft)))
        sent = "\n" + REPORT + "  \r\n\n\n\n\nSecond paragraph.   \n\n\n"
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=sent))

    def test_통과한_검사의_해시도_보낸_보고와_견준다(self):
        # Given
        self.reviewed_turn((CHECK, "c1", digest_output(REPORT)))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=REPORT))
        self.assert_blocks(self.run_hook(last_assistant_message=REPORT + "More."))

    def test_통과한_검토가_둘이면_나중_해시를_쓴다(self):
        # Given
        first, second = REPORT + "First.", REPORT + "Second."
        self.reviewed_turn((REVIEW, "r1", digest_output(first)), (REVIEW, "r2", digest_output(second)))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=second))
        self.assert_blocks(self.run_hook(last_assistant_message=first))

    def test_해시를_낸_실행이_없으면_보고가_달라도_막지_않는다(self):
        # Given
        failing = json.dumps({"stage": "review", "findings": [{"type": "removable"}]}) + "\nexit=1"
        self.reviewed_turn((REVIEW, "r1", failing))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=REPORT + "Different."))

    def test_도구_결과_내용이_텍스트_블록_목록이어도_해시를_읽는다(self):
        # Given
        blocks = [{"type": "text", "text": "ignored"}, {"type": "text", "text": digest_output(REPORT)}]
        self.reviewed_turn((REVIEW, "r1", blocks))
        # When / Then
        self.assert_blocks(self.run_hook(last_assistant_message=REPORT + "More."))

    def test_검토가_아닌_도구의_결과에_있는_해시는_무시한다(self):
        # Given
        self.write(
            prompt(), assistant(edit()), assistant(bash(REVIEW, "r1")),
            assistant(bash("cat /tmp/work/log.txt", "o1")), result("o1", digest_output(REPORT)),
        )
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=REPORT + "More."))

    def test_이전_턴의_해시는_이번_턴에_쓰지_않는다(self):
        # Given
        self.write(
            prompt("first"), assistant(bash(REVIEW, "r1")), result("r1", digest_output(REPORT)),
            prompt("second"), assistant(edit()), assistant(bash(REVIEW, "r2")),
        )
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=REPORT + "More."))

    def test_파일을_바꾸지_않은_턴은_해시가_달라도_통과한다(self):
        # Given
        self.write(prompt(), assistant(bash(REVIEW, "r1")), result("r1", digest_output(REPORT)))
        # When / Then
        self.assert_passes(self.run_hook(last_assistant_message=REPORT + "More."))

    def test_잘못된_입력과_없는_기록은_조용히_통과한다(self):
        self.assert_passes(self.run_hook(stdin="not json"))
        self.assert_passes(self.run_hook(stdin="[]"))
        self.assert_passes(self.run_hook(stdin=""))
        self.assert_passes(self.run_hook(transcript_path="/tmp/work/missing.jsonl"))
        self.assert_passes(self.run_hook(transcript_path=None))
        self.write("{broken", prompt(), assistant(edit()))
        self.assert_blocks(self.run_hook())


if __name__ == "__main__":
    unittest.main()
