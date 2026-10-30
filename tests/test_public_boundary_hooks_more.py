"""Public boundary hooks: every pushed blob version and variables expanded in a command."""

from __future__ import annotations

from test_public_boundary_hooks import (
    OWN_ORIGIN,
    SECRET,
    ZERO_SHA,
    SandboxCase,
)


class RangeBlobTests(SandboxCase):
    def outgoing_range(self) -> tuple[str, str, str]:
        self.stage("a.txt", "clean\n")
        base = self.commit("first")
        self.stage("a.txt", f"key {SECRET}\n")
        leaking = self.commit("second")
        self.stage("a.txt", "clean again\n")
        return base, leaking, self.commit("third")

    def test_범위_안_커밋이_넣고_뒤_커밋이_지운_비밀_값도_pre_push가_막는다(self) -> None:
        """tip에서는 사라진 값도 중간 커밋에 있으면 막고, 걸린 경로와 짧은 커밋을 알려야 한다."""
        # given
        base, leaking, head = self.outgoing_range()
        line = f"refs/heads/main {head} refs/heads/main {base}\n"

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=line)

        # then
        self.assertEqual(1, result.returncode)
        self.assertIn(f"commit {leaking[:12]} a.txt:1: github-token", result.stderr)
        self.assertNotIn(SECRET, result.stderr)

    def test_범위_안_커밋이_넣고_뒤_커밋이_지운_비밀_값도_git_push_훅이_막는다(self) -> None:
        """에이전트 훅의 push 검사도 중간 커밋의 값을 막아야 한다."""
        # given
        self.outgoing_range()

        # when
        result = self.hook("git push origin main")

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("a.txt:1: github-token", result.stderr)

    def test_깨끗한_범위는_통과한다(self) -> None:
        """모든 커밋의 모든 버전이 깨끗하면 pre-push가 0으로 끝나야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        self.commit("first")
        self.stage("a.txt", "clean again\n")
        head = self.commit("second")
        line = f"refs/heads/main {head} refs/heads/main {ZERO_SHA}\n"

        # when
        result = self.mode("pre-push", "origin", OWN_ORIGIN, stdin=line)

        # then
        self.assertEqual(0, result.returncode, result.stderr)


class VariableExpansionTests(SandboxCase):
    def test_앞에서_대입한_변수로_넘긴_비밀_본문을_막는다(self) -> None:
        """대입 형태와 export 형태 모두 본문 변수를 풀어서 검사해야 한다."""
        # given
        commands = [
            f'BODY="{SECRET}"; gh issue create --title t --body "$BODY"',
            f'export BODY="{SECRET}"; gh issue create --title t --body "${{BODY}}"',
        ]

        # when
        results = [self.hook(command) for command in commands]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])
        self.assertTrue(all("github-token" in result.stderr for result in results))
        self.assertTrue(all(SECRET not in result.stderr for result in results))

    def test_환경변수가_가리키는_홈_경로_본문을_막는다(self) -> None:
        """셸이 풀어서 올릴 환경변수 값이 홈 경로면 본문에서도 막아야 한다."""
        # given
        env = {**self.env, "HOME": "/home/" + "jdoe"}

        # when
        result = self.hook('gh issue create --title t --body "dir $HOME/x"', env=env)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("home-path", result.stderr)

    def test_알_수_없는_변수를_든_본문은_통과한다(self) -> None:
        """풀 수 없는 변수는 쓴 그대로 두고 검사하므로 값이 없으면 통과해야 한다."""
        # given
        command = 'gh issue create --title t --body "see $UNKNOWN_BODY_VAR"'

        # when
        result = self.hook(command)

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_홈_변수로_준_작업_폴더_인자는_막지_않는다(self) -> None:
        """git -C 인자의 $HOME이 홈 경로 모양으로 풀려도 디렉터리 인자는 보고하지 않아야 한다."""
        # given
        home = self.root / "home" / "jdoe"
        repo = self.make_repo(home / "repo", OWN_ORIGIN, with_hooks=True)
        self.stage("a.txt", "clean\n", repo=repo)
        env = {**self.env, "HOME": str(home)}
        script = repo / ".githooks" / "public_boundary.py"

        # when
        result = self.hook('git -C "$HOME/repo" commit -m ok', cwd=self.root, env=env, script=script)

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_변수로_준_작업_폴더의_저장소_명령도_검사한다(self) -> None:
        """git -C 인자가 변수여도 풀어서 이 저장소로 판단하고 메시지의 비밀 값을 막아야 한다."""
        # given
        self.stage("a.txt", "clean\n")
        command = f'D={self.repo}; git -C "$D" commit -m "fix: {SECRET}"'

        # when
        result = self.hook(command, cwd=self.root)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("github-token", result.stderr)
