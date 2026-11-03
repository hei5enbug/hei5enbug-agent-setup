"""Plugin-level public boundary hook: scope and stdin checks for writes that name their target or body indirectly.

Pushes to an explicit destination, variable and git-directory targets, repository-selection paths, and bodies read
from stdin through a pipeline. Every case runs in the sandbox that `test_public_boundary_plugin.py` defines.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_public_boundary_plugin import (
    HOME_PATH,
    OTHER_REPO,
    PUBLIC_ORIGIN,
    PUBLIC_REPO,
    PluginSandbox,
)


class ScopeHardeningTests(PluginSandbox):
    def public_with_leak(self) -> Path:
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        identity = {**self.env, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com",
                    "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", f"fix: see {HOME_PATH}"], cwd=checkout,
                       check=True, capture_output=True, env=identity)
        return checkout

    def create(self, repo_word: str, prefix: str = "") -> str:
        return f'{prefix}gh issue create --repo {repo_word} --title t --body "see {HOME_PATH}"'

    def test_셸_변수로_이름_붙인_gh_대상_저장소도_보호_대상이면_검사한다(self) -> None:
        """앞서 대입한 변수를 --repo나 GH_REPO에 쓰면 확장한 값으로 판단한다."""
        # given
        commands = [
            self.create('"$R"', f"R={PUBLIC_REPO}; "),
            self.create("${R}", f"R={PUBLIC_REPO}; "),
            self.create("", f"R={PUBLIC_REPO}; GH_REPO=$R "),
            self.create('"$O/demo-public"', "O=demo-owner; "),
        ]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2, 2, 2, 2], [result.returncode for result in results])

    def test_확장하지_못하는_gh_대상은_보호_대상으로_보고_검사한다(self) -> None:
        """값을 알 수 없는 변수나 명령 치환이면 보호 대상으로 보고 내용이 깨끗할 때만 통과시킨다."""
        # given
        leaking = [self.create('"$UNKNOWN_REPO"'), self.create('"$(echo x/y)"'), self.create("justname")]
        clean = 'gh issue create --repo "$UNKNOWN_REPO" --title t --body "a clean body"'

        # when
        blocked = [self.run_hook(command) for command in leaking]
        passed = self.run_hook(clean)

        # then
        self.assertEqual([2, 2, 2], [result.returncode for result in blocked])
        self.assertEqual(0, passed.returncode, passed.stderr)

    def test_보호_대상이_아닌_변수_저장소는_통과한다(self) -> None:
        """변수가 보호 대상이 아닌 저장소로 확장되면 검사하지 않는다."""
        # given
        command = self.create('"$R"', f"R={OTHER_REPO}; ")

        # when
        result = self.run_hook(command)

        # then
        self.assertEqual((0, ""), (result.returncode, result.stdout))

    def test_다른_체크아웃에서도_GIT_DIR이_가리키는_저장소를_검사한다(self) -> None:
        """인라인, export, 앞선 대입, --git-dir 모두 현재 폴더가 아니라 그 git 디렉터리의 저장소로 판단한다."""
        # given
        checkout = self.public_with_leak()
        git_dir = f"{checkout}/.git"
        commands = [
            f"GIT_DIR={git_dir} git push origin main",
            f"export GIT_DIR={git_dir}; git push origin main",
            f"D={git_dir}; GIT_DIR=$D git push origin main",
            f"git --git-dir={git_dir} push origin main",
            f"git --git-dir {git_dir} push origin main",
        ]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2] * 5, [result.returncode for result in results])
        self.assertTrue(all("home-path" in result.stderr for result in results))

    def test_GIT_DIR이_보호되지_않은_저장소를_가리키면_현재_체크아웃_때문에_막지_않는다(self) -> None:
        """보호 체크아웃 안에서도 GIT_DIR이 다른 저장소를 가리키면 그 저장소를 기준으로 통과시킨다."""
        # given
        checkout = self.public_with_leak()
        plain = self.make_repo(self.base / "work" / "plain-clone", "https://github.com/demo-owner/demo-x.git")

        # when
        result = self.run_hook(f"GIT_DIR={plain}/.git git push origin main", cwd=checkout)

        # then
        self.assertEqual((0, ""), (result.returncode, result.stdout))

    def test_GIT_DIR을_확장하지_못하면_보호_대상으로_보고_막는다(self) -> None:
        """값을 알 수 없는 GIT_DIR은 현재 체크아웃을 대신 검사하지 않고 확인하지 못했다며 막는다."""
        # given
        commands = ["GIT_DIR=$(git rev-parse --git-dir) git push origin main", 'git --git-dir="$UNKNOWN_DIR" push origin main']

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])
        self.assertTrue(all("could not be checked, so it is blocked" in result.stderr for result in results))

    def leaking_session(self) -> Path:
        identity = {**self.env, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com",
                    "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", f"fix: see {HOME_PATH}"], cwd=self.session,
                       check=True, capture_output=True, env=identity)
        return self.session

    def git_config(self, *args: str) -> None:
        subprocess.run(["git", "config", *args], cwd=self.session, check=True, capture_output=True, env=self.env)

    def test_보호_대상_저장소를_직접_가리키는_push는_보호되지_않은_체크아웃에서도_검사한다(self) -> None:
        """URL, 원격 이름의 pushurl과 url, 현재 브랜치의 push 원격 모두 실제 목적지로 판단한다."""
        # given
        self.leaking_session()
        self.git_config("remote.upstream.url", "https://github.com/demo-owner/demo-x.git")
        self.git_config("remote.upstream.pushurl", PUBLIC_ORIGIN)
        self.git_config("remote.viaurl.url", "git@github.com:demo-owner/demo-public.git")
        self.git_config("remote.plain.url", "https://github.com/demo-owner/demo-x.git")
        self.git_config("remote.pushDefault", "viaurl")
        commands = [
            f"git push {PUBLIC_ORIGIN} HEAD",
            "git push git@github.com:demo-owner/demo-public.git main",
            "git push upstream main",
            "git push viaurl main",
            "git push",
            "git push --repo=viaurl",
            "git -c remote.cfg.url=https://github.com/demo-owner/demo-public.git push cfg main",
        ]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2] * len(commands), [result.returncode for result in results], [r.stderr for r in results])
        self.assertTrue(all("home-path" in result.stderr for result in results))

    def test_보호되지_않은_목적지로_가는_push는_검사하지_않는다(self) -> None:
        """origin과 다른 원격 이름, URL이 모두 보호 대상이 아니면 아직 올리지 않은 커밋이 있어도 통과한다."""
        # given
        self.leaking_session()
        self.git_config("remote.plain.url", "https://github.com/demo-owner/demo-x.git")
        commands = ["git push origin main", "git push plain main", "git push https://github.com/demo-owner/demo-x.git HEAD"]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([(0, "")] * 3, [(result.returncode, result.stdout) for result in results])

    def test_목적지를_확장하지_못하는_push는_보호_대상으로_보고_검사한다(self) -> None:
        """알 수 없는 변수가 목적지면 아직 올리지 않은 커밋 메시지를 검사해 막는다."""
        # given
        self.leaking_session()

        # when
        result = self.run_hook('git push "$UNKNOWN_REMOTE" HEAD')

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("home-path", result.stderr)

    def selected_checkout(self) -> Path:
        checkout = self.make_repo(self.base / "home" / HOME_PATH.split("/")[2] / "project", PUBLIC_ORIGIN)
        self.assertIn(HOME_PATH.removesuffix("project"), str(checkout))
        return checkout

    def commit_selecting(self, checkout: Path, command: str, env: dict[str, str] | None = None):
        identity = {**(env or self.env), "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com",
                    "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}
        return self.run_hook(command, cwd=self.session, env=identity)

    def test_저장소를_고르는_경로만_홈_경로라서_막지는_않는다(self) -> None:
        """--git-dir, --work-tree, GIT_DIR, GIT_WORK_TREE 값은 옵션, 인라인, 대입, export 어느 쪽이든 로컬 입력이다."""
        # given
        checkout = self.selected_checkout()
        env = {**self.env, "HOME": str(checkout.parent)}
        git_dir, tree = f"{checkout}/.git", str(checkout)
        commands = [
            f'git --git-dir="{git_dir}" --work-tree="{tree}" commit --allow-empty -m x',
            f"git --git-dir={git_dir} --work-tree {tree} commit --allow-empty -m x",
            f'git --git-dir="$HOME/project/.git" --work-tree="$HOME/project" commit --allow-empty -m x',
            f"GIT_DIR={git_dir} GIT_WORK_TREE={tree} git commit --allow-empty -m x",
            f"env GIT_DIR={git_dir} git commit --allow-empty -m x",
            f"export GIT_DIR={git_dir} GIT_WORK_TREE={tree}; git commit --allow-empty -m x",
        ]

        # when
        results = [self.commit_selecting(checkout, command, env) for command in commands]

        # then
        self.assertEqual([0] * len(commands), [result.returncode for result in results], [r.stderr for r in results])

    def test_저장소를_고르는_경로를_걸러도_메시지의_홈_경로는_계속_막는다(self) -> None:
        """선택 경로 면제는 그 값에만 적용하고 같은 명령의 다른 홈 경로는 찾는다."""
        # given
        checkout = self.selected_checkout()
        git_dir = f"{checkout}/.git"
        commands = [
            f'git --git-dir="{git_dir}" commit --allow-empty -m "see {HOME_PATH}"',
            f'GIT_DIR={git_dir} git commit --allow-empty -m "see {HOME_PATH}"',
        ]

        # when
        results = [self.commit_selecting(checkout, command) for command in commands]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])
        self.assertTrue(all("command:1: home-path" in result.stderr for result in results))


class StdinBodyTests(PluginSandbox):
    def piped(self, producer: str, option: str = "--body-file -") -> str:
        return f"{producer} | gh issue create -R {PUBLIC_REPO} --title t {option}"

    def test_파이프로_넘긴_본문도_검사한다(self) -> None:
        """표준 입력을 읽는 옵션 모두에서 앞선 구간의 글자와 cat이나 리다이렉트가 읽는 파일을 검사한다."""
        # given
        (self.session / "body.md").write_text(f"see {HOME_PATH}\n", encoding="utf-8")
        commands = [
            self.piped(f"printf 'see {HOME_PATH}'"),
            self.piped(f"echo 'see {HOME_PATH}'", "-F -"),
            self.piped(f"echo 'see {HOME_PATH}'", "--body-file=-"),
            self.piped("cat body.md"),
            self.piped("cat < body.md"),
            self.piped("cat -n -- body.md"),
            f"gh issue create -R {PUBLIC_REPO} --title t --body-file - < body.md",
        ]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2] * 7, [result.returncode for result in results])
        self.assertTrue(all("home-path" in result.stderr for result in results))

    def test_표준_입력_본문이_깨끗하면_통과하고_정적으로_읽을_수_없으면_막는다(self) -> None:
        """깨끗한 정적 본문은 통과하고, 출력을 미리 알 수 없는 생산자는 확인하지 못해 막는다."""
        # given
        (self.session / "clean.md").write_text("a clean body\n", encoding="utf-8")
        clean = [self.piped("echo hello"), self.piped("cat clean.md"), self.piped("cat <<EOF\nhello\nEOF")]
        opaque = [self.piped("curl -s https://example.com/body"), self.piped("jq -r .body data.json")]

        # when
        passed = [self.run_hook(command) for command in clean]
        blocked = [self.run_hook(command) for command in opaque]

        # then
        self.assertEqual([0] * 3, [r.returncode for r in passed])
        self.assertEqual([2, 2], [r.returncode for r in blocked])
        self.assertTrue(all("output cannot be checked" in r.stderr for r in blocked))

    def test_git_commit이_표준_입력에서_읽는_메시지도_검사한다(self) -> None:
        """보호 체크아웃의 git commit -F - 도 같은 규칙으로 앞선 구간을 검사한다."""
        # given
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        command = f"echo 'fix: see {HOME_PATH}' | git commit --allow-empty -F -"

        # when
        result = self.run_hook(command, cwd=checkout)

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("home-path", result.stderr)

    def test_같은_구간의_heredoc_본문은_기존처럼_검사한다(self) -> None:
        """heredoc 본문은 구간 글자에 들어 있어 계속 검사하고, 깨끗하면 통과한다."""
        # given
        leaking = f"gh issue create -R {PUBLIC_REPO} --title t --body-file - <<'EOF'\nsee {HOME_PATH}\nEOF"
        clean = f"gh issue create -R {PUBLIC_REPO} --title t --body-file - <<'EOF'\nhello\nEOF"

        # when
        blocked = self.run_hook(leaking)
        passed = self.run_hook(clean)

        # then
        self.assertEqual([2, 0], [blocked.returncode, passed.returncode])

    def test_줄_끝_파이프_다음_줄도_같은_파이프라인이다(self) -> None:
        """줄 끝의 |, |&, 줄 이음 뒤 개행은 앞 구간의 파일을 다음 줄의 쓰기에 이어 준다."""
        # given
        (self.session / "body.md").write_text(f"see {HOME_PATH}\n", encoding="utf-8")
        write = f"gh issue create -R {PUBLIC_REPO} --title t --body-file -"
        commands = [f"cat body.md |\n{write}", f"cat body.md |&\n  {write}", f"cat body.md | \\\n{write}",
                    f"cat body.md |  \n\n{write}"]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2] * 4, [result.returncode for result in results], [r.stderr for r in results])
        self.assertTrue(all("home-path" in result.stderr for result in results))

    def test_파이프가_없는_앞줄의_cat은_다음_줄_쓰기의_입력이_아니다(self) -> None:
        """개행으로 끝난 앞 구간은 파이프라인을 잇지 않으므로 그 파일을 읽지 않는다."""
        # given
        (self.session / "body.md").write_text(f"see {HOME_PATH}\n", encoding="utf-8")
        command = f"cat body.md\ngh issue create -R {PUBLIC_REPO} --title t --body-file - < /dev/null"

        # when
        result = self.run_hook(command)

        # then
        self.assertEqual(0, result.returncode, result.stderr)

    def test_와일드카드로_이름_붙인_생산자_파일도_셸처럼_펼쳐_검사한다(self) -> None:
        """*, ?, [ 패턴은 작업 폴더 기준으로 일치하는 모든 파일을 검사하고, 일치가 없으면 건너뛴다."""
        # given
        (self.session / "body1.md").write_text("a clean body\n", encoding="utf-8")
        (self.session / "body2.md").write_text(f"see {HOME_PATH}\n", encoding="utf-8")
        leaking = [self.piped("cat body*.md"), self.piped("cat body?.md"), self.piped("cat body[12].md")]
        unmatched = self.piped("cat nothing*.md")

        # when
        blocked = [self.run_hook(command) for command in leaking]
        passed = self.run_hook(unmatched)

        # then
        self.assertEqual([2] * 3, [result.returncode for result in blocked])
        self.assertTrue(all("home-path" in result.stderr for result in blocked))
        self.assertEqual(0, passed.returncode, passed.stderr)
