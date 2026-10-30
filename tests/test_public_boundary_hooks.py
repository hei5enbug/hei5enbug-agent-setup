"""Hooks that block a commit, push, tag, or GitHub write before it runs when it breaks the public boundary.

Every case runs in temporary repositories with fake hook input. No test reaches a remote or calls gh.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".githooks"
sys.path.insert(0, str(HOOKS_DIR))

import boundary_agent  # noqa: E402
import boundary_shell  # noqa: E402
import public_boundary  # noqa: E402

WORDS_ENV = "HEI5ENBUG_PUBLIC_BOUNDARY_WORDS"
OWN_REPO = "example-owner/example-repo"
OWN_ORIGIN = f"https://github.com/{OWN_REPO}.git"
OTHER_ORIGIN = "https://github.com/example-owner/other-repo.git"
REAL_HOME = "/Users/" + "jdoe"
SECRET = "ghp" + "_" + "a" * 24
PRIVATE_WORD = "Acme" + "Internal"
ZERO_SHA = "0" * 40


class SandboxCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = {
            **{key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "HEI5ENBUG_"))},
            "HOME": str(self.root / "h"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.com",
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.com",
        }
        (self.root / "h").mkdir()
        self.repo = self.make_repo(self.root / "repo", OWN_ORIGIN, with_hooks=True)
        self.other = self.make_repo(self.root / "other", OTHER_ORIGIN)
        self.script = self.repo / ".githooks" / "public_boundary.py"

    def make_repo(self, path: Path, origin: str, with_hooks: bool = False) -> Path:
        path.mkdir(parents=True)
        self.git(path, "init", "-q")
        self.git(path, "remote", "add", "origin", origin)
        if with_hooks:
            shutil.copytree(HOOKS_DIR, path / ".githooks", ignore=shutil.ignore_patterns("__pycache__"))
        return path

    def git(self, cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
        done = subprocess.run(
            ["git", *args], cwd=cwd, env=env or self.env, check=True, capture_output=True, text=True
        )
        return done.stdout.strip()

    def stage(self, name: str, content: str, repo: Path | None = None) -> None:
        target = repo or self.repo
        (target / name).write_text(content, encoding="utf-8")
        self.git(target, "add", name)

    def commit(self, message: str) -> str:
        self.git(self.repo, "commit", "-q", "--no-verify", "-m", message)
        return self.git(self.repo, "rev-parse", "HEAD")

    def spawn(
        self, argv: list[str], text: str = "", cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv, input=text, cwd=cwd or self.root, env=env or self.env, capture_output=True, text=True
        )

    def raw_hook(self, text: str, script: Path | None = None) -> subprocess.CompletedProcess[str]:
        return self.spawn([sys.executable, str(script or self.script), "agent-hook"], text)

    def hook(
        self,
        command: str,
        cwd: Path | None = None,
        tool: str = "Bash",
        env: dict[str, str] | None = None,
        script: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd or self.repo)}
        argv = [sys.executable, str(script or self.script), "agent-hook"]
        return self.spawn(argv, json.dumps(payload), env=env)

    def git_commit(self, message: str) -> subprocess.CompletedProcess[str]:
        return self.spawn(["git", "commit", "-q", "-m", message], cwd=self.repo)

    def mode(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return self.spawn([sys.executable, str(self.script), *args], stdin, cwd=self.repo)

    def words_env(self, words: list[str]) -> dict[str, str]:
        path = self.root / "outside-words.txt"
        path.write_text("# private names\n\n" + "\n".join(words) + "\n", encoding="utf-8")
        return {**self.env, WORDS_ENV: str(path)}


class StagedCommitTests(SandboxCase):
    def test_홈_경로가_든_스테이징_내용의_커밋을_훅이_만들기_전에_막는다(self) -> None:
        """git commit 명령을 실행하기 전에 파일 이름과 종류를 알리며 막아야 한다."""
        # given
        self.stage("notes.txt", f"see {REAL_HOME}/work\n")

        # when
        result = self.hook('git commit -m "docs: add notes"')

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("notes.txt:1: home-path", result.stderr)
        self.assertNotIn("jdoe", result.stderr)

    def test_pre_commit_모드도_같은_홈_경로를_막는다(self) -> None:
        """pre-commit 모드는 스테이징된 파일의 홈 경로를 파일 이름과 종류로 보고하고 1로 끝나야 한다."""
        # given
        self.stage("notes.txt", f"see {REAL_HOME}/work\n")

        # when
        result = self.mode("pre-commit")

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn("notes.txt:1: home-path", result.stderr)
        self.assertNotIn("jdoe", result.stderr)

    def test_가상_값은_커밋을_막지_않는다(self) -> None:
        """/home/test, /tmp/work, example.com, ABC-123은 통과해야 한다."""
        # given
        self.stage("notes.txt", "/home/test /tmp/work me@example.com ABC-123\n")

        # when
        result = self.hook('git commit -m "docs: fix ABC-123 in /tmp/work for /home/test via me@example.com"')

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_옵션_커밋은_추적_파일의_작업_사본_변경도_검사한다(self) -> None:
        """git commit -am은 아직 스테이징하지 않은 추적 파일의 변경도 막아야 한다."""
        # given
        self.stage("notes.txt", "clean\n")
        self.commit("first")
        (self.repo / "notes.txt").write_text(f"{SECRET}\n", encoding="utf-8")

        # when
        result = self.hook('git commit -am "docs: update notes"')

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("notes.txt:1: github-token", result.stderr)

    def test_작성자_이름의_비밀_값은_막고_실제_이메일은_막지_않는다(self) -> None:
        """작성자와 커미터 정보에는 이메일 규칙을 적용하지 않지만 비밀 값 형태는 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        real_email = "jdoe" + "@corp.io"
        env = {**self.env, "GIT_AUTHOR_EMAIL": real_email}
        clean = self.hook('git commit -m "docs: a"', env=env)
        leaky = {**env, "GIT_COMMITTER_NAME": SECRET}

        # when
        blocked = self.hook('git commit -m "docs: a"', env=leaky)

        # then
        self.assertEqual(0, clean.returncode, clean.stderr)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("committer identity:1: github-token", blocked.stderr)


class MessageTests(SandboxCase):
    def test_m_옵션_커밋_메시지의_비밀_값을_막는다(self) -> None:
        """-m으로 준 커밋 메시지에 키 형태의 비밀 값이 있으면 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")

        # when
        result = self.hook(f'git commit -m "fix: rotate {SECRET}"')

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("github-token", result.stderr)
        self.assertNotIn(SECRET, result.stderr)

    def test_heredoc_커밋_메시지의_비밀_값을_막는다(self) -> None:
        """heredoc으로 준 커밋 메시지 본문의 비밀 값도 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        command = f"git commit -F - <<'EOF'\nfix: subject\n\nbody {SECRET}\nEOF"

        # when
        result = self.hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("command:4: github-token", result.stderr)

    def test_command_substitution_heredoc_메시지도_막는다(self) -> None:
        """-m 인자 안의 $(cat <<EOF ...) 본문도 명령 문자열로 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        command = f'git commit -m "$(cat <<\'EOF\'\nfix: subject\n\n{SECRET}\nEOF\n)"'

        # when
        result = self.hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("github-token", result.stderr)

    def test_F_옵션으로_읽는_메시지_파일의_비밀_값을_막는다(self) -> None:
        """-F로 지정한 파일의 내용도 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        (self.repo / "msg.txt").write_text(f"fix: x\n\n{SECRET}\n", encoding="utf-8")

        # when
        result = self.hook("git commit -F msg.txt")

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("msg.txt:3: github-token", result.stderr)

    def test_commit_msg_모드는_메시지_파일의_비밀_값을_막는다(self) -> None:
        """commit-msg 모드는 메시지 파일의 비밀 값을 보고하고 1로 끝나야 한다."""
        # given
        message = self.root / "COMMIT_EDITMSG"
        message.write_text(f"fix: x\n\n{SECRET}\n", encoding="utf-8")

        # when
        result = self.mode("commit-msg", str(message))

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn("github-token", result.stderr)
        self.assertNotIn(SECRET, result.stderr)

    def test_commit_msg_모드는_주석_줄을_무시한다(self) -> None:
        """# 로 시작하는 줄은 커밋에 들어가지 않으므로 검사하지 않아야 한다."""
        # given
        message = self.root / "COMMIT_EDITMSG"
        message.write_text(f"fix: x\n# {SECRET}\n", encoding="utf-8")

        # when
        result = self.mode("commit-msg", str(message))

        # then
        self.assertEqual(0, result.returncode, result.stderr)

class TagTests(SandboxCase):
    def test_주석_태그_메시지의_비밀_값을_막는다(self) -> None:
        """git tag -a v9 -m 으로 만드는 태그 메시지의 비밀 값을 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        self.commit("first")

        # when
        result = self.hook(f'git tag -a v9 -m "release {SECRET}"')

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("github-token", result.stderr)

    def test_태그를_만들지_않는_명령은_통과한다(self) -> None:
        """목록, 삭제, 이름 없는 git tag는 읽기 전용이거나 로컬 삭제이므로 통과해야 한다."""
        # given
        commands = ["git tag", "git tag -l", "git tag --list 'v*'", "git tag -d v1", "git tag --contains HEAD"]

        # when
        codes = [self.hook(command).returncode for command in commands]

        # then
        self.assertEqual([0] * len(commands), codes)

    def test_이름만_준_태그_생성도_태거_정보를_검사한다(self) -> None:
        """이름 인자가 있으면 태그를 만드는 명령이므로 태거 정보의 비밀 값을 막아야 한다."""
        # given
        env = {**self.env, "GIT_COMMITTER_NAME": SECRET}

        # when
        result = self.hook("git tag v1", env=env)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("committer identity:1: github-token", result.stderr)


class GhWriteTests(SandboxCase):
    def test_이슈_본문의_비밀_값을_막는다(self) -> None:
        """gh issue create의 --body에 비밀 값이 있으면 막아야 한다."""
        # given
        command = f'gh issue create --title t --body "token {SECRET}"'

        # when
        result = self.hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("github-token", result.stderr)
        self.assertNotIn(SECRET, result.stderr)

    def test_body_file의_비밀_값을_막는다(self) -> None:
        """--body-file로 준 파일 내용의 비밀 값도 막고 파일 이름을 알려야 한다."""
        # given
        (self.repo / "body.md").write_text(f"one\n{SECRET}\n", encoding="utf-8")

        # when
        result = self.hook("gh issue create --title t --body-file body.md")

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("body.md:2: github-token", result.stderr)

    def test_표준_입력_본문은_명령_문자열에서_검사한다(self) -> None:
        """--body-file -와 heredoc으로 준 본문도 명령 문자열에서 막아야 한다."""
        # given
        command = f"gh pr create --title t --body-file - <<'EOF'\nbody {SECRET}\nEOF"

        # when
        result = self.hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("command:2: github-token", result.stderr)

    def test_쓰기_명령_종류를_모두_검사한다(self) -> None:
        """issue, pr, release, api의 쓰기 명령은 모두 같은 본문 검사를 받아야 한다."""
        # given
        commands = [
            f'gh issue comment 1 --body "{SECRET}"',
            f'gh issue edit 1 --body "{SECRET}"',
            f'gh pr comment 1 --body "{SECRET}"',
            f'gh pr review 1 --comment --body "{SECRET}"',
            f'gh pr edit 1 --body "{SECRET}"',
            f'gh release create v1 --notes "{SECRET}"',
            f'gh release edit v1 --notes "{SECRET}"',
            f'gh api repos/{OWN_REPO}/issues -f body="{SECRET}"',
            f'gh api -X PATCH repos/{OWN_REPO}/issues/1 --raw-field body="{SECRET}"',
        ]

        # when
        codes = [self.hook(command).returncode for command in commands]

        # then
        self.assertEqual([2] * len(commands), codes)

    def test_api_필드_파일과_notes_file과_input을_검사한다(self) -> None:
        """field=@file, --notes-file, --input으로 읽는 파일도 검사해야 한다."""
        # given
        (self.repo / "f.txt").write_text(f"{SECRET}\n", encoding="utf-8")
        commands = [
            f"gh api repos/{OWN_REPO}/issues -F body=@f.txt",
            "gh release create v1 --notes-file f.txt",
            f"gh api repos/{OWN_REPO}/issues --input f.txt",
        ]

        # when
        results = [self.hook(command) for command in commands]

        # then
        self.assertEqual([2, 2, 2], [item.returncode for item in results])
        self.assertTrue(all("f.txt:1: github-token" in item.stderr for item in results))

    def test_비공개_단어_목록의_단어는_막고_목록이_없으면_통과한다(self) -> None:
        """환경 변수로 준 목록의 단어가 이슈 본문에 있으면 막고, 목록이 없으면 같은 본문이 통과해야 한다."""
        # given
        command = f'gh issue create --title t --body "we use {PRIVATE_WORD.lower()} here"'
        without = self.hook(command)

        # when
        with_words = self.hook(command, env=self.words_env([PRIVATE_WORD]))

        # then
        self.assertEqual(0, without.returncode, without.stderr)
        self.assertEqual(2, with_words.returncode)
        self.assertIn("command:1: private-word", with_words.stderr)
        self.assertNotIn(PRIVATE_WORD.lower(), with_words.stderr.lower())

    def test_저장소_안의_단어_목록은_무시하고_한_줄로_알린다(self) -> None:
        """저장소 안을 가리키는 목록 경로는 읽지 않고 stderr에 한 줄 안내만 남겨야 한다."""
        # given
        inside = self.repo / "words.txt"
        inside.write_text(PRIVATE_WORD + "\n", encoding="utf-8")
        env = {**self.env, WORDS_ENV: str(inside)}

        # when
        result = self.hook(f'gh issue create --title t --body "{PRIVATE_WORD}"', env=env)

        # then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(result.stderr.strip().splitlines()))
        self.assertNotIn(PRIVATE_WORD, result.stderr)


class OutOfScopeTests(SandboxCase):
    def test_다른_저장소의_명령은_영향받지_않는다(self) -> None:
        """다른 저장소 작업 폴더, cd, git -C, gh -R의 쓰기 명령은 비밀 값이 있어도 통과해야 한다."""
        # given
        self.stage("a.txt", "clean\n", repo=self.other)
        message = f"fix: {SECRET}"
        cases = [
            (f'git commit -m "{message}"', self.other),
            (f'cd {self.other} && git commit -m "{message}"', self.repo),
            (f'git -C {self.other} commit -m "{message}"', self.repo),
            (f'gh issue create -R other/repo --title t --body "{SECRET}"', self.repo),
            (f'gh issue create --title t --body "{SECRET}"', self.other),
            (f'gh api repos/other/repo/issues -f body="{SECRET}"', self.repo),
        ]

        # when
        codes = [self.hook(command, cwd=cwd).returncode for command, cwd in cases]

        # then
        self.assertEqual([0] * len(cases), codes)

    def test_이_저장소로_다시_돌아오는_명령은_검사한다(self) -> None:
        """cd나 git -C가 이 저장소를 가리키면 다른 폴더에서 시작해도 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        message = f"fix: {SECRET}"
        commands = [
            f'cd {self.repo} && git commit -m "{message}"',
            f'git -C {self.repo} commit -m "{message}"',
            f'gh issue create -R {OWN_REPO} --title t --body "{SECRET}"',
        ]

        # when
        codes = [self.hook(command, cwd=self.other).returncode for command in commands]

        # then
        self.assertEqual([2] * len(commands), codes)

    def test_읽기_전용_명령은_영향받지_않는다(self) -> None:
        """status, log, tag -l, gh issue view, 읽기 api는 비밀 값 문자열이 있어도 통과해야 한다."""
        # given
        commands = [
            "git status",
            f"git log --grep {SECRET}",
            "git tag -l",
            f"gh issue view 1 --comments # {SECRET}",
            "gh api repos/o/r",
            f"gh api -X GET repos/{OWN_REPO}/issues -f state=open",
        ]

        # when
        codes = [self.hook(command).returncode for command in commands]

        # then
        self.assertEqual([0] * len(commands), codes)

    def test_홈_경로_모양의_작업_폴더_인자는_무시한다(self) -> None:
        """cd와 git -C의 디렉터리 인자에 든 홈 경로는 보고하지 않아야 한다."""
        # given
        home_like = self.make_repo(self.root / "home" / "jdoe" / "repo", OWN_ORIGIN, with_hooks=True)
        self.stage("a.txt", "clean\n", repo=home_like)
        script = home_like / ".githooks" / "public_boundary.py"
        commands = [f"cd {home_like} && git commit -m ok", f"git -C {home_like} commit -m ok"]

        # when
        codes = [self.hook(command, cwd=self.root, script=script).returncode for command in commands]

        # then
        self.assertEqual([0, 0], codes)

    def test_이_저장소의_홈_경로_cd_뒤_읽기_명령은_통과한다(self) -> None:
        """cd <홈 경로> && git status 는 검사 대상이 아니므로 통과해야 한다."""
        # given
        command = f"cd {REAL_HOME}/proj && git status"

        # when
        result = self.hook(command)

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_셸_도구가_아니거나_git_gh가_없는_명령은_git을_실행하지_않는다(self) -> None:
        """빠른 경로는 git 프로세스를 띄우지 않고 0으로 끝나야 한다."""
        # given
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        marker = self.root / "git-ran"
        fake_git = fake_bin / "git"
        fake_git.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n", encoding="utf-8")
        fake_git.chmod(0o755)
        env = {**self.env, "PATH": f"{fake_bin}{os.pathsep}{self.env['PATH']}"}

        # when
        codes = [
            self.hook("echo hello", env=env).returncode,
            self.hook("git commit -m x", tool="Read", env=env).returncode,
            self.hook("ls -la", env=env).returncode,
        ]

        # then
        self.assertEqual([0, 0, 0], codes)
        self.assertFalse(marker.exists())

    def test_해석할_수_없는_입력은_통과한다(self) -> None:
        """JSON이 아니거나 명령이 없는 입력은 막지 않아야 한다."""
        # given
        inputs = ["not json", "{}", json.dumps({"tool_name": "Bash", "tool_input": {}})]

        # when
        codes = [self.raw_hook(text).returncode for text in inputs]

        # then
        self.assertEqual([0, 0, 0], codes)

    def test_검사할_수_없는_대상_명령은_이유와_함께_막는다(self) -> None:
        """읽을 수 없는 본문 파일이 있는 gh 쓰기 명령은 검사하지 못했다는 이유로 막아야 한다."""
        # given
        command = "gh issue create --title t --body-file missing.md"

        # when
        result = self.hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("could not be checked", result.stderr)


class PrePushTests(SandboxCase):
    def push_line(self, sha: str, remote_sha: str = ZERO_SHA) -> str:
        return f"refs/heads/main {sha} refs/heads/main {remote_sha}\n"

    def test_비밀_값이_든_메시지의_새_커밋이_있으면_막는다(self) -> None:
        """pre-push 모드는 올라갈 새 커밋의 메시지를 검사해 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        sha = self.commit(f"fix: {SECRET}")

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=self.push_line(sha))

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn(f"commit {sha[:12]} message:1: github-token", result.stderr)
        self.assertNotIn(SECRET, result.stderr)

    def test_깨끗한_새_커밋은_통과한다(self) -> None:
        """비밀 값이 없는 새 커밋만 올라가면 0으로 끝나야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        sha = self.commit("fix: clean")

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=self.push_line(sha))

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_새_커밋이_바꾼_파일의_홈_경로를_막는다(self) -> None:
        """새 커밋이 바꾼 파일 내용도 푸시 전에 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        base = self.commit("first")
        self.stage("a.txt", f"path {REAL_HOME}/x\n")
        head = self.commit("second")

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=self.push_line(head, base))

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn("a.txt:1: home-path", result.stderr)

    def test_이미_올라간_범위의_커밋은_검사하지_않는다(self) -> None:
        """원격 sha까지의 커밋은 건너뛰고 그 뒤의 새 커밋만 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        old = self.commit(f"fix: {SECRET}")
        self.stage("a.txt", "clean two\n")
        head = self.commit("fix: clean")

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=self.push_line(head, old))

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_주석_태그_메시지와_태거를_검사한다(self) -> None:
        """태그 ref가 주석 태그면 태그 메시지의 비밀 값을 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        self.commit("fix: clean")
        self.git(self.repo, "tag", "-a", "v1", "-m", f"note {SECRET}")
        tag_sha = self.git(self.repo, "rev-parse", "v1")
        line = f"refs/tags/v1 {tag_sha} refs/tags/v1 {ZERO_SHA}\n"

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=line)

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn("tag v1 message:1: github-token", result.stderr)

    def test_git_push_명령은_원격에_없는_커밋과_주석_태그를_검사한다(self) -> None:
        """에이전트 훅은 git push 전에 HEAD의 새 커밋과 --tags의 주석 태그를 검사해야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        self.commit(f"fix: {SECRET}")

        # when
        result = self.hook("git push origin main")

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("message:1: github-token", result.stderr)

    def test_git_push_tags는_모든_주석_태그를_검사한다(self) -> None:
        """--tags로 올라가는 주석 태그의 메시지도 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        self.commit("fix: clean")
        self.git(self.repo, "tag", "-a", "v1", "-m", f"note {SECRET}")

        # when
        result = self.hook("git push --tags origin")

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("tag v1 message:1: github-token", result.stderr)


class HookWrapperTests(SandboxCase):
    def enable(self) -> None:
        self.git(self.repo, "config", "core.hooksPath", ".githooks")

    def test_pre_commit_래퍼가_실제_커밋을_막는다(self) -> None:
        """core.hooksPath를 켠 저장소에서 홈 경로가 든 스테이징은 커밋이 만들어지지 않아야 한다."""
        # given
        self.enable()
        self.stage("notes.txt", f"see {REAL_HOME}/work\n")

        # when
        result = self.git_commit("docs: notes")

        # then
        self.assertNotEqual(0, result.returncode)
        self.assertIn("notes.txt:1: home-path", result.stderr)
        self.assertEqual("", subprocess.run(
            ["git", "log", "--oneline"], cwd=self.repo, env=self.env, capture_output=True, text=True
        ).stdout)

    def test_commit_msg_래퍼가_비밀_값이_든_메시지를_막는다(self) -> None:
        """core.hooksPath를 켠 저장소에서 비밀 값이 든 메시지의 커밋은 만들어지지 않아야 한다."""
        # given
        self.enable()
        self.stage("a.txt", "clean\n")

        # when
        result = self.git_commit(f"fix: {SECRET}")

        # then
        self.assertNotEqual(0, result.returncode)
        self.assertIn("github-token", result.stderr)

class ShellParsingTests(unittest.TestCase):
    def kind(self, command: str) -> str | None:
        for segment in boundary_agent.iter_segments(command):
            target = boundary_shell.classify(list(segment.tokens))
            if target is not None:
                return target.kind
        return None

    def test_따옴표와_연결자를_구분해_세그먼트로_나눈다(self) -> None:
        """따옴표 안의 && 는 나누지 않고 바깥의 연결자만 나눠야 한다."""
        # given
        command = 'echo "a && b"; git commit -m x && ls | wc\nls'

        # when
        segments = boundary_shell.split_segments(command)

        # then
        self.assertEqual(
            [("echo", "a && b"), ("git", "commit", "-m", "x"), ("ls",), ("wc",), ("ls",)],
            [segment.tokens for segment in segments],
        )

    def test_heredoc_본문은_여는_세그먼트에_속한다(self) -> None:
        """heredoc 본문의 연결자와 git 단어는 새 세그먼트를 만들지 않아야 한다."""
        # given
        command = "cat <<'EOF'\ngit push && git commit\nEOF\ngit status"

        # when
        segments = boundary_shell.split_segments(command)

        # then
        self.assertEqual(2, len(segments))
        self.assertIn("git push && git commit", segments[0].text)
        self.assertEqual(("git", "status"), segments[1].tokens)
        self.assertEqual(4, segments[1].line)

    def test_대상_명령의_종류를_분류한다(self) -> None:
        """커밋, 푸시, 태그 생성, gh 쓰기 명령은 종류로 분류해야 한다."""
        # given
        commands = [
            "git commit -m x",
            "git -C /x -c user.name=a push origin main",
            "FOO=1 git tag -a v1 -m x",
            "git tag v1",
            "gh issue create --title t",
            "gh pr review 1 --approve",
            "gh release edit v1",
            "gh api repos/o/r/issues -f a=b",
            "gh api -X POST repos/o/r/issues",
            "gh api --method=PUT repos/o/r/x",
        ]

        # when
        kinds = [self.kind(command) for command in commands]

        # then
        self.assertEqual(
            ["commit", "push", "tag", "tag", "gh-write", "gh-write", "gh-write", "gh-write", "gh-write", "gh-write"],
            kinds,
        )

    def test_읽기_전용_명령은_분류하지_않는다(self) -> None:
        """읽기 전용 git과 gh 명령은 대상이 아니다."""
        # given
        commands = [
            "git status",
            "git log -1",
            "git tag",
            "git tag -l",
            "git tag -d v1",
            "git tag --contains HEAD",
            "gh issue view 1",
            "gh pr list",
            "gh api repos/o/r",
            "gh api -X DELETE repos/o/r/x",
            "echo git commit",
        ]

        # when
        kinds = [self.kind(command) for command in commands]

        # then
        self.assertEqual([None] * len(commands), kinds)

    def test_bash_c_안의_명령도_찾는다(self) -> None:
        """bash -c 로 감싼 git commit도 대상으로 찾아야 한다."""
        # given
        command = "bash -lc 'git commit -m x'"

        # when
        kind = self.kind(command)

        # then
        self.assertEqual("commit", kind)

    def test_디렉터리_변경_명령의_대상을_읽는다(self) -> None:
        """cd와 pushd의 디렉터리 인자를 읽어야 한다."""
        # given
        commands = ["cd /tmp/work", "pushd -- /tmp/work", "cd", "ls /tmp/work"]

        # when
        targets = [boundary_shell.change_dir(shlex.split(command)) for command in commands]

        # then
        self.assertEqual(["/tmp/work", "/tmp/work", None, None], targets)


class PrivateWordTests(unittest.TestCase):
    def test_단어는_대소문자를_가리지_않고_단어_단위로만_맞춘다(self) -> None:
        """부분 문자열은 맞추지 않고 값 없이 위치와 종류만 보고해야 한다."""
        # given
        words = public_boundary.compile_private_words(["Acme Corp", "zeta"])
        text = "we met ACME  corp today\nzetas and Zeta-1 and azeta\nnothing"

        # when
        findings = public_boundary.scan_text("f", text, words=words)

        # then
        self.assertEqual(["f:1: private-word", "f:2: private-word"], findings)

if __name__ == "__main__":
    unittest.main()
