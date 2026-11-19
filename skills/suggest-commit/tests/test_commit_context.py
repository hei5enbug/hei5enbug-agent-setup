"""Behavior of scripts/commit_context.py on throwaway repositories: the context pass, scoped staging, one commit."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "commit_context.py"
SPEC = importlib.util.spec_from_file_location("commit_context", SCRIPT)
commit_context = importlib.util.module_from_spec(SPEC)
sys.modules["commit_context"] = commit_context
SPEC.loader.exec_module(commit_context)

GIT_ENV = {"GIT_AUTHOR_NAME": "Demo Dev", "GIT_AUTHOR_EMAIL": "dev@example.com", "GIT_COMMITTER_NAME": "Demo Dev",
           "GIT_COMMITTER_EMAIL": "dev@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
SUBJECT = "fix: handle empty names"
SECRET_VALUE = "demo-secret-4471"


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.new_repo("repo")

    def new_repo(self, name: str) -> None:
        self.repo = self.root / name
        self.repo.mkdir()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=self.repo, check=True,
                              capture_output=True, text=True).stdout

    def write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def init(self, history: bool = True) -> None:
        self.git("init", "-q", "-b", "main")
        if history:
            self.write("src/demo.py", "def greet(name):\n    return 'hi ' + name\n")
            self.write("README.md", "# Demo\n")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "feat: add greet")

    def run_script(self, *args: str, cwd: Path | None = None) -> tuple[int, dict]:
        completed = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or self.repo, capture_output=True,
                                   text=True, check=False)
        return completed.returncode, json.loads(completed.stdout)

    def head_files(self) -> list[str]:
        return self.git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD").split()

    def commit_count(self) -> int:
        return int(self.git("rev-list", "--count", "HEAD").strip())

    def mixed_state(self) -> None:
        self.init()
        self.write("src/demo.py", "def greet(name):\n    return 'hi ' + (name or 'you')\n")
        self.git("add", "src/demo.py")
        self.write("README.md", "# Demo\n\nUsage notes.\n")
        self.write(".env", f"TOKEN={SECRET_VALUE}\n")


class ContextTest(RepoCase):
    def test_기본_범위_문맥은_상태_diff_로그_규약을_구역별_JSON으로_낸다(self):
        """기본 범위의 문맥은 추적 변경과 미추적 파일, 최근 로그, 문서화된 커밋 규약 줄을 담는다."""
        # Given
        self.mixed_state()
        self.write("AGENTS.md", "# Rules\n\n- Commit message format: `<type>: [ABC-123] <description>`\n")

        # When
        code, context = self.run_script("context")

        # Then
        self.assertEqual(code, 0)
        self.assertEqual((context["scope"], context["has_head"], context["index_empty"]), ("default", True, False))
        self.assertIn("M  src/demo.py", context["status"])
        self.assertIn("M\tsrc/demo.py", context["diff_name_status"])
        self.assertIn("M\tREADME.md", context["diff_name_status"])
        self.assertEqual(context["log"][0].split(" ", 1)[1], "feat: add greet")
        self.assertIn(".env", context["untracked"])
        self.assertTrue(context["convention"][0].startswith("AGENTS.md:3:"))

    def test_스테이징만_범위는_스테이징_안_된_변경을_diff에서_뺀다(self):
        """--staged-only 문맥의 diff에는 스테이징한 파일만 나온다."""
        # Given
        self.mixed_state()

        # When
        _, context = self.run_script("context", "--staged-only")

        # Then
        self.assertEqual(context["diff_name_status"], ["M\tsrc/demo.py"])
        self.assertEqual(context["scope"], "staged")

    def test_경로_범위는_지정한_경로의_변경만_diff에_담는다(self):
        """--path로 이름 붙인 범위의 diff는 그 경로 밖의 변경을 담지 않는다."""
        # Given
        self.mixed_state()

        # When
        _, context = self.run_script("context", "--path", "README.md")

        # Then
        self.assertEqual(context["diff_name_status"], ["M\tREADME.md"])
        self.assertEqual(context["scope"], "paths")

    def test_로그는_최근_스무_개까지만_담는다(self):
        """스물다섯 개 커밋이 있어도 로그 구역은 스무 줄이다."""
        # Given
        self.init()
        for number in range(24):
            self.git("commit", "-q", "--allow-empty", "-m", f"chore: step {number}")

        # When
        _, context = self.run_script("context")

        # Then
        self.assertEqual(len(context["log"]), 20)

    def test_HEAD가_없는_저장소도_상태와_diff를_내고_로그는_비어_있다(self):
        """커밋이 하나도 없으면 has_head가 false이고 스테이징 및 미스테이징 변경이 diff에 나오며 로그는 빈 목록이다."""
        # Given
        self.init(history=False)
        self.write("a.py", "print('a')\n")
        self.git("add", "a.py")
        self.write("b.py", "print('b')\n")

        # When
        code, context = self.run_script("context")

        # Then
        self.assertEqual(code, 0)
        self.assertFalse(context["has_head"])
        self.assertEqual(context["log"], [])
        self.assertEqual(context["diff_name_status"], ["A\ta.py"])
        self.assertEqual(context["untracked"], ["b.py"])

    def test_하위_폴더에서_불러도_저장소_루트_기준_경로를_쓴다(self):
        """저장소 하위 폴더에서 --repo로 부르고 상대 경로를 주면 그 경로의 변경만 문맥에 담긴다."""
        # Given
        self.mixed_state()

        # When
        _, context = self.run_script("--repo", str(self.repo / "src"), "context", "--path", "demo.py")

        # Then
        self.assertEqual(context["diff_name_status"], ["M\tsrc/demo.py"])


class CommitScopeTest(RepoCase):
    def test_스테이징한_파일만_커밋하고_나머지는_범위_밖으로_알린다(self):
        """스테이징된 src/demo.py만 커밋하고 README.md는 범위 밖, 미추적 .env는 비밀 파일로 남겨 알리며 메시지는 제목뿐이다."""
        # Given
        self.mixed_state()

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual(code, 0)
        self.assertEqual(self.head_files(), ["src/demo.py"])
        self.assertEqual(self.git("log", "-1", "--format=%B").strip(), SUBJECT)
        self.assertEqual((report["status"], report["file_count"], report["message_has_extra_lines"]),
                         ("committed", 1, False))
        self.assertEqual(report["files_outside_scope"], ["README.md"])
        self.assertEqual(report["files_left_out"], [".env"])
        self.assertEqual(report["scope"], "staged")

    def test_인덱스가_비면_추적_변경과_지정한_관련_미추적_파일을_함께_커밋하고_비밀은_남긴다(self):
        """스테이징이 없을 때 기본 범위는 수정된 src/demo.py와 --include 한 src/demo_util.py를 커밋하고 .env는 남겨 알린다."""
        # Given
        self.init()
        self.write("src/demo.py", "def greet(name):\n    return 'hello ' + name\n")
        self.write("src/demo_util.py", "def shout(text):\n    return text.upper()\n")
        self.write(".env", f"TOKEN={SECRET_VALUE}\n")

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT, "--include", "src/demo_util.py")

        # Then
        self.assertEqual(code, 0)
        self.assertEqual(sorted(self.head_files()), ["src/demo.py", "src/demo_util.py"])
        self.assertEqual(report["files_left_out"], [".env"])
        self.assertEqual(report["scope"], "default")
        self.assertNotIn(SECRET_VALUE, self.git("log", "-p", "--all"))

    def test_관련이_없다고_표시하지_않은_미추적_파일은_기본_범위에_들어가지_않는다(self):
        """--include가 없으면 미추적 파일은 커밋되지 않고 범위 밖 목록에 남는다."""
        # Given
        self.init()
        self.write("src/demo.py", "def greet(name):\n    return 'hello ' + name\n")
        self.write("notes.txt", "scratch\n")

        # When
        _, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual(self.head_files(), ["src/demo.py"])
        self.assertEqual(report["files_outside_scope"], ["notes.txt"])

    def test_이름_붙인_경로_범위는_그_경로만_스테이징해_커밋한다(self):
        """--path README.md는 README.md만 커밋하고 다른 수정은 범위 밖으로 남긴다."""
        # Given
        self.init()
        self.write("src/demo.py", "def greet(name):\n    return 'hello ' + name\n")
        self.write("README.md", "# Demo\n\nUsage notes.\n")

        # When
        code, report = self.run_script("commit", "--subject", "docs: add usage notes", "--path", "README.md")

        # Then
        self.assertEqual(code, 0)
        self.assertEqual(self.head_files(), ["README.md"])
        self.assertEqual(report["files_outside_scope"], ["src/demo.py"])

    def test_이름_붙인_경로_밖에_스테이징한_변경이_있으면_쓰기_전에_멈춘다(self):
        """인덱스에 지정 경로 밖 변경이 있으면 그것까지 커밋하지 않도록 아무것도 쓰지 않고 멈춘다."""
        # Given
        self.mixed_state()
        before = self.git("rev-parse", "HEAD")

        # When
        code, report = self.run_script("commit", "--subject", "docs: add usage notes", "--path", "README.md")

        # Then
        self.assertEqual((code, report["code"]), (3, "staged_outside_scope"))
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["src/demo.py"])

    def test_스테이징된_비밀_파일은_인덱스에서_빼고_나머지만_커밋한다(self):
        """스테이징된 .env는 커밋에 들어가지 않고 목록에 남으며 다른 스테이징 파일은 커밋된다."""
        # Given
        self.mixed_state()
        self.git("add", "-f", ".env")

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual(code, 0)
        self.assertEqual(self.head_files(), ["src/demo.py"])
        self.assertEqual(report["files_left_out"], [".env"])
        self.assertNotIn(SECRET_VALUE, self.git("log", "-p", "--all"))

    def test_HEAD가_없는_저장소에서는_스테이징한_파일로_첫_커밋을_만든다(self):
        """기록이 없는 저장소에서도 스테이징한 파일만 루트 커밋이 되고 나머지는 범위 밖이다."""
        # Given
        self.init(history=False)
        self.write("a.py", "print('a')\n")
        self.write("b.py", "print('b')\n")
        self.git("add", "a.py")

        # When
        code, report = self.run_script("commit", "--subject", "feat: add a")

        # Then
        self.assertEqual(code, 0)
        self.assertEqual(self.head_files(), ["a.py"])
        self.assertEqual(report["files_outside_scope"], ["b.py"])

    def test_변경이_없으면_이유와_함께_멈추고_아무것도_쓰지_않는다(self):
        """범위에 변경이 없으면 코드 no_changes로 멈추고 커밋 수가 그대로다."""
        # Given
        self.init()

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual((code, report["status"], report["code"]), (3, "stopped", "no_changes"))
        self.assertEqual(self.commit_count(), 1)

    def test_스테이징만_범위에서_스테이징이_없으면_다른_변경이_있어도_멈춘다(self):
        """--staged-only인데 인덱스가 비어 있으면 수정된 파일이 있어도 커밋하지 않는다."""
        # Given
        self.init()
        self.write("README.md", "# Demo\n\nUsage notes.\n")

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT, "--staged-only")

        # Then
        self.assertEqual((code, report["code"]), (3, "no_changes"))
        self.assertEqual(self.commit_count(), 1)

    def test_여러_줄이거나_트레일러를_담은_제목은_쓰기_전에_거절한다(self):
        """줄바꿈이 있는 제목과 Co-Authored-By를 담은 제목은 사용법 오류로 끝나고 커밋하지 않는다."""
        # Given
        self.mixed_state()

        for subject in ("fix: a\n\nbody", "fix: a Co-Authored-By: Demo <d@example.com>", "  "):
            with self.subTest(subject=subject):
                # When
                code, report = self.run_script("commit", "--subject", subject)

                # Then
                self.assertEqual((code, report["code"]), (2, "subject_invalid"))
                self.assertEqual(self.commit_count(), 1)

    def test_저장소가_아니면_사용법_오류로_멈춘다(self):
        """Git 작업 트리가 아닌 폴더에서는 코드 not_a_repository로 끝난다."""
        # Given
        outside = self.root / "plain"
        outside.mkdir()

        # When
        code, report = self.run_script("context", cwd=outside)

        # Then
        self.assertEqual((code, report["code"]), (2, "not_a_repository"))


class StopAndHookTest(RepoCase):
    def test_리베이스가_진행_중이면_이유를_알리고_아무것도_쓰지_않는다(self):
        """충돌로 멈춘 리베이스 중에는 코드 in_progress로 멈추고 HEAD와 인덱스가 그대로다."""
        # Given
        self.init()
        self.git("checkout", "-q", "-b", "topic")
        self.write("README.md", "# Topic\n")
        self.git("commit", "-q", "-am", "docs: topic readme")
        self.git("checkout", "-q", "main")
        self.write("README.md", "# Main\n")
        self.git("commit", "-q", "-am", "docs: main readme")
        self.git("checkout", "-q", "topic")
        subprocess.run(["git", "rebase", "main"], cwd=self.repo, capture_output=True, text=True, check=False)
        head, index = self.git("rev-parse", "HEAD"), self.git("ls-files", "-s")

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual((code, report["code"], "rebase" in report["reason"]), (3, "in_progress", True))
        self.assertEqual((self.git("rev-parse", "HEAD"), self.git("ls-files", "-s")), (head, index))

    def test_해결하지_않은_충돌이_있으면_충돌_파일을_알리고_멈춘다(self):
        """리베이스 중이 아니어도 스태시 복원이 남긴 충돌 파일이 있으면 코드 conflicts로 멈춘다."""
        # Given
        self.init()
        self.write("README.md", "# Mine\n")
        self.git("stash", "-q")
        self.write("README.md", "# Theirs\n")
        self.git("commit", "-q", "-am", "docs: theirs")
        subprocess.run(["git", "stash", "pop"], cwd=self.repo, capture_output=True, text=True, check=False)

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual((code, report["code"]), (3, "conflicts"))
        self.assertIn("README.md", report["reason"])

    def test_커밋_훅이_거절하면_메시지를_알리고_스테이징을_그대로_두며_다시_시도하지_않는다(self):
        """commit-msg 훅이 실패하면 코드 4와 훅 메시지를 내고 스테이징이 남으며 커밋 시도는 한 번뿐이다."""
        # Given
        self.mixed_state()
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\necho 'subject needs a ticket' >&2\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        recorded: list[tuple[str, ...]] = []
        real_run = subprocess.run

        def spy(command, *args, **kwargs):
            recorded.append(tuple(command))
            return real_run(command, *args, **kwargs)

        # When
        output = io.StringIO()
        with mock.patch.object(commit_context.subprocess, "run", spy), contextlib.redirect_stdout(output):
            code = commit_context.main(["--repo", str(self.repo), "commit", "--subject", SUBJECT])

        # Then
        report = json.loads(output.getvalue())
        self.assertEqual((code, report["code"]), (4, "rejected"))
        self.assertIn("subject needs a ticket", report["reason"])
        self.assertEqual(self.git("diff", "--cached", "--name-only").split(), ["src/demo.py"])
        self.assertEqual(self.commit_count(), 1)
        self.assertEqual(sum(1 for command in recorded if "commit" in command), 1)

    def test_훅이_메시지에_줄을_덧붙이면_보고하고_amend하지_않는다(self):
        """commit-msg 훅이 트레일러를 붙이면 message_has_extra_lines가 true이고 amend 없이 커밋이 하나만 늘어난다."""
        # Given
        self.mixed_state()
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\nprintf '\\nSigned-off-by: Hook <h@example.com>\\n' >> \"$1\"\n", encoding="utf-8")
        hook.chmod(0o755)

        # When
        code, report = self.run_script("commit", "--subject", SUBJECT)

        # Then
        self.assertEqual(code, 0)
        self.assertTrue(report["message_has_extra_lines"])
        self.assertEqual(self.commit_count(), 2)


class GitCommandAuditTest(RepoCase):
    FORBIDDEN = ("--no-verify", "--amend", "--allow-empty", "--signoff", "--trailer", "-a", "--all", "-A", "-s", "-n")

    def audited_commands(self, *args: str) -> list[tuple[str, ...]]:
        recorded: list[tuple[str, ...]] = []
        real_run = subprocess.run

        def spy(command, *spy_args, **kwargs):
            recorded.append(tuple(command))
            return real_run(command, *spy_args, **kwargs)

        with mock.patch.object(commit_context.subprocess, "run", spy), contextlib.redirect_stdout(io.StringIO()):
            commit_context.main(["--repo", str(self.repo), *args])
        return recorded

    def test_스크립트가_실행하는_모든_git_명령에는_금지_옵션이_없다(self):
        """기본, 경로, 스테이징 범위 커밋이 실행한 모든 git 명령에 우회, amend, 빈 커밋, 서명, 트레일러, 전체 스테이징 옵션이 없다."""
        # Given
        scenarios = (("commit", "--subject", SUBJECT), ("commit", "--subject", SUBJECT, "--path", "README.md"),
                     ("commit", "--subject", SUBJECT, "--include", "notes.txt"), ("context",))
        for number, scenario in enumerate(scenarios):
            with self.subTest(scenario=scenario):
                self.new_repo(f"audit{number}")
                self.mixed_state()
                self.write("notes.txt", "scratch\n")

                # When
                commands = self.audited_commands(*scenario)

                # Then
                used = {argument for command in commands for argument in command}
                self.assertEqual(used & set(self.FORBIDDEN), set())
                self.assertNotIn(".", {argument for command in commands if "add" in command for argument in command})

    def test_커밋_명령은_하나의_m과_제목만_쓰고_스테이징은_경로를_하나씩_넘긴다(self):
        """git commit은 정확히 `commit -m <제목>`이고, git add는 -- 뒤에 구체적인 경로만 받는다."""
        # Given
        self.init()
        self.write("src/demo.py", "def greet(name):\n    return 'hello ' + name\n")
        self.write("src/demo_util.py", "def shout(text):\n    return text.upper()\n")

        # When
        commands = self.audited_commands("commit", "--subject", SUBJECT, "--include", "src/demo_util.py")

        # Then
        commits = [command for command in commands if "commit" in command]
        adds = [command for command in commands if "add" in command]
        self.assertEqual([command[-3:] for command in commits], [("commit", "-m", SUBJECT)])
        self.assertEqual([command[command.index("add"):] for command in adds],
                         [("add", "--", "src/demo.py", "src/demo_util.py")])

    def test_금지_인자는_실행기에서_예외로_막힌다(self):
        """run_git은 금지 인자를 받으면 git을 실행하지 않고 예외를 낸다."""
        # Given
        self.init()

        # When / Then
        with self.assertRaises(ValueError):
            commit_context.run_git(self.repo, "commit", "-m", "x", "--no-verify")


if __name__ == "__main__":
    unittest.main()
