"""Plugin-level public boundary hook: GitHub and git writes to a declared public repository are checked from any project.

Every case uses temporary directories: a fake Claude Code config folder, a fake Codex cache, a copy of the hook
and scanner as the running plugin, and a session folder outside any protected repository. No test reaches a
remote or calls gh.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SOURCE = REPO_ROOT / "scripts" / "public_boundary_hook.py"
LAUNCHER = REPO_ROOT / "scripts" / "hook_python.sh"
sys.path.insert(0, str(REPO_ROOT / ".githooks"))

import boundary_plugins  # noqa: E402

PUBLIC_REPO = "demo-owner/demo-public"
PUBLIC_ORIGIN = f"https://github.com/{PUBLIC_REPO}.git"
OTHER_REPO = "demo-owner/demo-other"
PRIVATE_WORD = "example" + "-corp"
HOME_PATH = "/home/" + "jdoe" + "/project"
WORDS_ENV = "HEI5ENBUG_PUBLIC_BOUNDARY_WORDS"
PRIVATE_BODY = f"we use {PRIVATE_WORD} internally"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def target(location: str, **changes: object) -> dict:
    return {"version": 1, "tracker": {"kind": "github", "location": location}, "public": True, **changes}


class PluginSandbox(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.claude = self.base / "claude"
        self.codex = self.base / "codex"
        self.own = self.make_own_plugin()
        self.session = self.make_repo(self.base / "work" / "demo-a", "https://github.com/demo-owner/demo-a.git")
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "HEI5ENBUG_", "CLAUDE_", "CODEX_"))},
            "HOME": str(self.base / "h"),
            "XDG_STATE_HOME": str(self.base / "state"),
            "CLAUDE_CONFIG_DIR": str(self.claude),
            "CODEX_HOME": str(self.codex),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Demo Sandbox",
            "GIT_AUTHOR_EMAIL": "sandbox@example.com",
            "GIT_COMMITTER_NAME": "Demo Sandbox",
            "GIT_COMMITTER_EMAIL": "sandbox@example.com",
        }

    def make_own_plugin(self) -> Path:
        root = self.base / "own"
        (root / "scripts").mkdir(parents=True)
        shutil.copy(HOOK_SOURCE, root / "scripts" / "public_boundary_hook.py")
        shutil.copytree(REPO_ROOT / ".githooks", root / ".githooks", ignore=shutil.ignore_patterns("__pycache__"))
        write_json(root / "issue-target.json", target(PUBLIC_REPO))
        return root

    def make_repo(self, path: Path, origin: str) -> Path:
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True, capture_output=True)
        return path

    def install_claude(self, name: str, files: dict[str, object] | None = None) -> Path:
        root = self.base / "installs" / name
        write_json(root / ".claude-plugin" / "plugin.json", {"name": name})
        for relative, content in (files or {}).items():
            if isinstance(content, str):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text(content, encoding="utf-8")
            else:
                write_json(root / relative, content)
        path = self.claude / "plugins" / "installed_plugins.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 2, "plugins": {}}
        current["plugins"][f"{name}@demo-market"] = [{"scope": "user", "installPath": str(root)}]
        write_json(path, current)
        return root

    def install_private_words(self, words: list[str], name: str = "demo-private") -> Path:
        files = {
            "public-boundary.json": {"version": 1, "private_words_file": "config/words.txt"},
            "config/words.txt": "# names\n" + "\n".join(words) + "\n",
        }
        return self.install_claude(name, files)

    def run_hook(self, command: str, cwd: Path | None = None, env: dict[str, str] | None = None,
                 tool: str = "Bash") -> subprocess.CompletedProcess[str]:
        payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(cwd or self.session)}
        argv = [sys.executable, str(self.own / "scripts" / "public_boundary_hook.py")]
        return subprocess.run(argv, input=json.dumps(payload), text=True, capture_output=True,
                              cwd=self.base, env=env or self.env)

    def issue(self, body: str, repo: str = PUBLIC_REPO) -> str:
        return f'gh issue create --repo {repo} --title t --body "{body}"'


class WordListBlockTests(PluginSandbox):
    def test_다른_프로젝트_세션이_설치된_플러그인의_단어를_담아_공개_저장소에_이슈를_쓰면_막는다(self) -> None:
        """기준 1: 프로젝트 밖 세션의 gh issue create --repo 본문에 설치된 플러그인 목록의 단어가 있으면 실행 전에 막는다."""
        # given
        self.install_private_words([PRIVATE_WORD])

        # when
        result = self.run_hook(self.issue(PRIVATE_BODY))

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("command:1: private-word", result.stderr)
        self.assertNotIn(PRIVATE_WORD, result.stderr.lower())
        self.assertNotIn(PRIVATE_WORD, result.stdout.lower())

    def test_codex_캐시의_최신_버전이_선언한_단어_목록도_읽는다(self) -> None:
        """Codex 캐시에서는 플러그인마다 가장 새 버전의 선언만 읽는다."""
        # given
        for version, words in (("1.2.0", [PRIVATE_WORD]), ("1.10.0", ["unrelated-name"])):
            root = self.codex / "plugins" / "cache" / "demo-market" / "demo-private" / version
            write_json(root / "public-boundary.json", {"version": 1, "private_words_file": "words.txt"})
            (root / "words.txt").write_text("\n".join(words), encoding="utf-8")
        newest_hit = self.run_hook(self.issue("unrelated-name here"))

        # when
        older_hit = self.run_hook(self.issue(PRIVATE_BODY))

        # then
        self.assertEqual(2, newest_hit.returncode, newest_hit.stderr)
        self.assertEqual(0, older_hit.returncode, older_hit.stderr)

    def test_환경_변수_목록과_선언_목록을_함께_읽는다(self) -> None:
        """환경 변수의 목록과 설치된 플러그인의 목록이 둘 다 적용된다."""
        # given
        self.install_private_words([PRIVATE_WORD])
        outside = self.base / "outside-words.txt"
        outside.write_text("second-name\n", encoding="utf-8")
        env = {**self.env, WORDS_ENV: str(outside)}

        # when
        first = self.run_hook(self.issue(PRIVATE_BODY), env=env)
        second = self.run_hook(self.issue("second-name"), env=env)

        # then
        self.assertEqual([2, 2], [first.returncode, second.returncode])

    def test_목록을_읽었으면_깨끗한_본문은_출력_없이_통과한다(self) -> None:
        """목록이 있으면 목록 없음 안내를 내지 않는다."""
        # given
        self.install_private_words([PRIVATE_WORD])

        # when
        result = self.run_hook(self.issue("a clean body"))

        # then
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)


class JsonWordListTests(PluginSandbox):
    def install_json_list(self, content: object) -> Path:
        files = {
            "public-boundary.json": {"version": 1, "private_words_file": "config/words.json"},
            "config/words.json": content,
        }
        return self.install_claude("demo-private", files)

    def test_JSON_목록의_단어와_패턴이_모두_적용된다(self) -> None:
        """JSON 단어 파일은 words의 단어와 patterns의 정규식을 모두 검사한다."""
        # given
        self.install_json_list({"words": [PRIVATE_WORD], "patterns": [{"label": "key", "regex": r"\bZZQ-\d+\b"}]})

        # when
        by_word = self.run_hook(self.issue(PRIVATE_BODY))
        by_pattern = self.run_hook(self.issue("see ZZQ-42 for details"))
        clean = self.run_hook(self.issue("nothing private here"))

        # then
        self.assertEqual([2, 2, 0], [by_word.returncode, by_pattern.returncode, clean.returncode])
        self.assertIn("private-word", by_pattern.stderr)
        self.assertNotIn("ZZQ-42", by_pattern.stderr)

    def test_대소문자_무시_패턴은_ignore_case가_참일_때만_적용된다(self) -> None:
        """패턴은 기본적으로 대소문자를 구분하고, ignore_case가 참이면 무시한다."""
        # given
        self.install_json_list({"words": [], "patterns": [{"regex": "zzq-svc"}, {"regex": "yyw-db", "ignore_case": True}]})

        # when
        strict = self.run_hook(self.issue("ZZQ-SVC runs"))
        loose = self.run_hook(self.issue("YYW-DB runs"))

        # then
        self.assertEqual([0, 2], [strict.returncode, loose.returncode])

    def test_허용된_신원_이메일은_신원_검사에서만_빠지고_이름은_계속_검사한다(self) -> None:
        """allowed_identity_emails에 있는 작성자 이메일은 단어와 겹쳐도 통과하고, 같은 단어가 이름에 있으면 막는다."""
        # given
        email = "ops@zzq-mail.example.com"
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        command = 'git commit --allow-empty -m "feat: change"'

        def identity(name: str) -> dict[str, str]:
            return {**self.env, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                    "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}

        self.install_json_list({"words": ["zzq-mail"], "allowed_identity_emails": [email.upper()]})

        # when
        allowed = self.run_hook(command, cwd=checkout, env=identity("Demo Owner"))
        named = self.run_hook(command, cwd=checkout, env=identity("zzq-mail bot"))

        # then
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        self.assertEqual(2, named.returncode, named.stderr)
        self.assertIn("identity", named.stderr)

    def test_허용_목록이_없으면_단어와_겹치는_신원_이메일을_막는다(self) -> None:
        """allowed_identity_emails가 없으면 작성자 이메일도 비공개 단어로 검사한다."""
        # given
        email = "ops@zzq-mail.example.com"
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        env = {**self.env, "GIT_AUTHOR_NAME": "Demo Owner", "GIT_AUTHOR_EMAIL": email,
               "GIT_COMMITTER_NAME": "Demo Owner", "GIT_COMMITTER_EMAIL": email}
        self.install_json_list({"words": ["zzq-mail"]})

        # when
        result = self.run_hook('git commit --allow-empty -m "feat: change"', cwd=checkout, env=env)

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("identity", result.stderr)

    def test_형식이_틀린_JSON_목록은_플러그인_이름과_이유로_막는다(self) -> None:
        """words가 문자열 목록이 아니거나 정규식이 틀리면 단어를 싣지 않고 막는다."""
        # given
        self.install_json_list({"words": "not-a-list"})

        # when
        result = self.run_hook(self.issue("nothing private here"))

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("demo-private: the word file is not a valid word list", result.stderr)


class NoListNoticeTests(PluginSandbox):
    def test_목록이_없으면_일반_검사만_하고_통과하며_결과가_목록이_없다고_알린다(self) -> None:
        """기준 2: 목록이 없을 때 같은 본문이 통과하고 사용자용 메시지와 모델용 문맥이 목록이 없다고 말한다."""
        # given
        command = self.issue(PRIVATE_BODY)

        # when
        result = self.run_hook(command)

        # then
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        notice = boundary_plugins.NO_LIST_NOTICE
        self.assertEqual(notice, output["systemMessage"])
        self.assertEqual({"hookEventName": "PreToolUse", "additionalContext": notice}, output["hookSpecificOutput"])
        self.assertNotIn("permissionDecision", json.dumps(output))
        self.assertIn("no private word list was found", notice)

    def test_차단할_때도_표준_오류에_같은_안내를_더한다(self) -> None:
        """목록이 없고 일반 검사에 걸리면 막으면서 같은 문장을 stderr에 더한다."""
        # given
        command = self.issue(f"see {HOME_PATH}")

        # when
        result = self.run_hook(command)

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("command:1: home-path", result.stderr)
        self.assertIn(boundary_plugins.NO_LIST_NOTICE, result.stderr)
        self.assertNotIn("jdoe", result.stderr)

    def test_홈_경로가_든_본문은_어느_프로젝트에서든_막는다(self) -> None:
        """기준 3: 프로젝트 밖 세션과 일반 폴더 세션 모두에서 홈 경로 본문을 막는다."""
        # given
        plain = self.base / "plain"
        plain.mkdir()
        command = self.issue(f"see {HOME_PATH}")

        # when
        results = [self.run_hook(command, cwd=cwd) for cwd in (self.session, plain)]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])


class OutOfScopeTests(PluginSandbox):
    def test_다른_저장소를_향한_명령은_출력_없이_통과한다(self) -> None:
        """기준 4: --repo가 선언되지 않은 저장소면 단어와 홈 경로가 있어도 영향이 없다."""
        # given
        self.install_private_words([PRIVATE_WORD])
        command = self.issue(f"{PRIVATE_BODY} {HOME_PATH}", repo=OTHER_REPO)

        # when
        result = self.run_hook(command)

        # then
        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))

    def test_읽기_전용_git_과_gh_명령은_출력_없이_통과한다(self) -> None:
        """기준 4: 공개 저장소를 향해도 읽기 전용 명령은 검사하지 않는다."""
        # given
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        commands = [
            f"gh issue list --repo {PUBLIC_REPO}",
            f"gh issue view 1 --repo {PUBLIC_REPO}",
            "git status",
            "git log --oneline",
        ]

        # when
        results = [self.run_hook(command, cwd=checkout) for command in commands]

        # then
        self.assertEqual([(0, "", "")] * 4, [(r.returncode, r.stdout, r.stderr) for r in results])

    def test_git_이_아닌_명령은_선언을_읽지_않고_통과한다(self) -> None:
        """git이나 gh 단어가 없으면 설치 선언이 깨져 있어도 읽지 않는다."""
        # given
        write_json(self.claude / "plugins" / "installed_plugins.json", ["not", "an", "object"])

        # when
        result = self.run_hook("ls -la")

        # then
        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))

    def test_셸_도구가_아닌_호출은_통과한다(self) -> None:
        """Bash가 아닌 도구 이름은 검사하지 않는다."""
        # given
        command = self.issue(f"see {HOME_PATH}")

        # when
        result = self.run_hook(command, tool="Read")

        # then
        self.assertEqual((0, ""), (result.returncode, result.stdout))


class GitWriteTests(PluginSandbox):
    def test_공개_저장소_원격을_가진_체크아웃의_커밋_메시지를_다른_폴더_세션에서도_막는다(self) -> None:
        """git 쓰기는 origin이 선언된 저장소로 정규화되는 체크아웃에서만 검사한다."""
        # given
        self.install_private_words([PRIVATE_WORD])
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        elsewhere = self.make_repo(self.base / "work" / "plain-clone", "https://github.com/demo-owner/demo-x.git")
        command = f'git commit --allow-empty -m "feat: {PRIVATE_WORD}"'

        # when
        blocked = self.run_hook(command, cwd=checkout)
        passed = self.run_hook(command, cwd=elsewhere)

        # then
        self.assertEqual(2, blocked.returncode, blocked.stderr)
        self.assertIn("private-word", blocked.stderr)
        self.assertNotIn(PRIVATE_WORD, blocked.stderr.lower())
        self.assertEqual((0, ""), (passed.returncode, passed.stdout))

    def test_origin_없이_gh_를_쓰면_작업_폴더의_origin으로_판단한다(self) -> None:
        """--repo가 없는 gh 쓰기는 작업 폴더 origin이 선언된 저장소일 때만 검사한다."""
        # given
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        command = f'gh pr comment 1 --body "see {HOME_PATH}"'

        # when
        inside = self.run_hook(command, cwd=checkout)
        outside = self.run_hook(command, cwd=self.session)

        # then
        self.assertEqual([2, 0], [inside.returncode, outside.returncode])


class InlineVariableTests(PluginSandbox):
    def gh_create(self, prefix: str = "", options: str = "") -> str:
        return f'{prefix}gh issue create {options}--title t --body "see {HOME_PATH}"'

    def test_인라인_GH_REPO가_공개_저장소면_프로젝트_밖_세션에서도_막는다(self) -> None:
        """줄 앞 대입과 env 래퍼 뒤 대입 모두 그 세그먼트의 gh 대상 저장소가 된다."""
        # given
        commands = [self.gh_create(f"GH_REPO={PUBLIC_REPO} "), self.gh_create(f"env GH_REPO={PUBLIC_REPO} ")]

        # when
        results = [self.run_hook(command) for command in commands]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])
        self.assertTrue(all("command:1: home-path" in result.stderr for result in results))

    def test_앞서_export한_GH_REPO와_훅_프로세스_환경의_GH_REPO도_대상이_된다(self) -> None:
        """같은 명령의 export와 훅 환경의 GH_REPO는 --repo가 없는 gh 쓰기의 대상이다."""
        # given
        exported = f"export GH_REPO={PUBLIC_REPO}; " + self.gh_create()
        command = self.gh_create()

        # when
        from_export = self.run_hook(exported)
        from_environment = self.run_hook(command, env={**self.env, "GH_REPO": PUBLIC_REPO})

        # then
        self.assertEqual([2, 2], [from_export.returncode, from_environment.returncode])

    def test_다른_저장소를_가리키는_GH_REPO는_통과한다(self) -> None:
        """GH_REPO가 보호 대상이 아니면 작업 폴더나 다른 구간 때문에 검사하지 않는다."""
        # given
        command = self.gh_create(f"GH_REPO={OTHER_REPO} ")

        # when
        result = self.run_hook(command, cwd=self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN))

        # then
        self.assertEqual((0, "", ""), (result.returncode, result.stdout, result.stderr))

    def test_인라인_대입은_그_구간에만_적용되고_repo_옵션이_우선한다(self) -> None:
        """다음 구간으로 넘어가지 않고, --repo가 있으면 GH_REPO보다 먼저 쓴다."""
        # given
        later = f"GH_REPO={PUBLIC_REPO} gh issue list; " + self.gh_create()
        override = self.gh_create(f"GH_REPO={PUBLIC_REPO} ", f"--repo {OTHER_REPO} ")

        # when
        results = [self.run_hook(later), self.run_hook(override)]

        # then
        self.assertEqual([(0, ""), (0, "")], [(r.returncode, r.stdout) for r in results])

    def test_인라인_GIT_DIR이_붙은_push도_보호_체크아웃이면_검사한다(self) -> None:
        """git 쓰기 앞의 인라인 대입을 무시하지 않고 아직 올리지 않은 커밋 메시지를 검사한다."""
        # given
        checkout = self.make_repo(self.base / "work" / "public-clone", PUBLIC_ORIGIN)
        identity = {**self.env, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.com",
                    "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.com"}
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", f"fix: see {HOME_PATH}"], cwd=checkout,
                       check=True, capture_output=True, env=identity)

        # when
        result = self.run_hook(f"GIT_DIR={checkout}/.git git push origin main", cwd=checkout)

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("home-path", result.stderr)
        self.assertNotIn("jdoe", result.stderr)


class DeclarationTests(PluginSandbox):
    def test_잘못된_선언은_플러그인_이름과_이유로_알리고_막지만_단어는_싣지_않는다(self) -> None:
        """무효한 선언이나 읽을 수 없는 파일은 단어가 아니라 문제로 보고하고, 확인하지 못한 쓰기는 막는다."""
        # given
        cases = {
            "extra-key": {"version": 1, "private_words_file": "w.txt", "other": 1},
            "wrong-version": {"version": 2, "private_words_file": "w.txt"},
            "absolute": {"version": 1, "private_words_file": str(self.base / "w.txt")},
            "escapes": {"version": 1, "private_words_file": "../w.txt"},
            "missing-file": {"version": 1, "private_words_file": "nope.txt"},
            "not-text": "not json",
        }
        for name, declaration in cases.items():
            self.install_claude(name, {"public-boundary.json": declaration, "w.txt": PRIVATE_WORD})
        (self.base / "installs" / "w.txt").write_text(PRIVATE_WORD, encoding="utf-8")

        # when
        result = self.run_hook(self.issue("a clean body"))

        # then
        self.assertEqual(2, result.returncode)
        for name in cases:
            with self.subTest(plugin=name):
                self.assertRegex(result.stderr, rf"could not be checked, so it is blocked: {name}: ")
        self.assertNotIn(PRIVATE_WORD, result.stderr.lower())

    def test_다른_플러그인이_공개로_선언한_저장소도_보호한다(self) -> None:
        """설치된 플러그인의 issue-target.json이 public이고 github이면 그 저장소도 검사 대상이다."""
        # given
        extra = target(OTHER_REPO)
        self.install_claude("demo-extra", {"issue-target.json": extra})
        self.install_claude("demo-private-repo", {"issue-target.json": target("demo-owner/demo-closed", public=False)})
        self.install_claude("demo-gitlab", {"issue-target.json": {**extra, "tracker": {"kind": "gitlab", "location": "a/b"}}})

        # when
        declared = self.run_hook(self.issue(f"see {HOME_PATH}", repo=OTHER_REPO))
        closed = self.run_hook(self.issue(f"see {HOME_PATH}", repo="demo-owner/demo-closed"))
        gitlab = self.run_hook(self.issue(f"see {HOME_PATH}", repo="a/b"))

        # then
        self.assertEqual([2, 0, 0], [declared.returncode, closed.returncode, gitlab.returncode])

    def test_실행_중인_플러그인의_루트_선언은_설치_없이도_보호한다(self) -> None:
        """CLAUDE_PLUGIN_ROOT나 PLUGIN_ROOT가 가리키는 루트도 설치된 것으로 센다."""
        # given
        running = self.base / "running"
        write_json(running / "issue-target.json", target("demo-owner/demo-running"))
        command = self.issue(f"see {HOME_PATH}", repo="demo-owner/demo-running")

        # when
        results = [self.run_hook(command, env={**self.env, name: str(running)}) for name in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")]

        # then
        self.assertEqual([2, 2], [result.returncode for result in results])

    def test_스캐너가_없으면_검사하지_못했으므로_막는다(self) -> None:
        """플러그인에 .githooks가 없으면 조용히 통과하지 않고 이유를 내며 차단 종료 코드로 끝난다."""
        # given
        shutil.rmtree(self.own / ".githooks")

        # when
        result = self.run_hook(self.issue("a clean body"))

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("scanner folder is missing", result.stderr)
        self.assertIn("blocked because it could not be checked", result.stderr)

    def test_스캐너가_예외를_내면_검사하지_못했으므로_막는다(self) -> None:
        """스캐너 실행 중 예외가 나도 쓰기를 통과시키지 않고 차단 종료 코드로 끝난다."""
        # given
        (self.own / ".githooks" / "boundary_agent.py").write_text(
            "def run(*args, **kwargs):\n    raise RuntimeError('broken')\n", encoding="utf-8"
        )

        # when
        result = self.run_hook(self.issue("a clean body"))

        # then
        self.assertEqual(2, result.returncode)
        self.assertIn("RuntimeError", result.stderr)
        self.assertIn("blocked because it could not be checked", result.stderr)

    def test_런처를_거친_저장소의_훅도_자체_선언으로_홈_경로를_막는다(self) -> None:
        """hook_python.sh로 실행해도 이 저장소의 선언만으로 프로젝트 밖 세션의 쓰기를 막는다."""
        # given
        payload = {"tool_name": "Bash", "tool_input": {"command": self.issue(f"see {HOME_PATH}", repo="hei5enbug/hei5enbug-agent-setup")},
                   "cwd": str(self.session)}

        # when
        result = subprocess.run(["sh", str(LAUNCHER), "public_boundary_hook.py"], input=json.dumps(payload), text=True,
                                capture_output=True, cwd=self.base, env=self.env)

        # then
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("home-path", result.stderr)


class DiscoveryUnitTests(PluginSandbox):
    def test_선언을_검증한다(self) -> None:
        """public이 true이고 github이며 owner/repo 형태일 때만 소문자로 정규화해 돌려준다."""
        # given
        root = self.base / "unit"
        cases = [
            (target("Demo-Owner/Demo-A"), "demo-owner/demo-a"),
            (target("demo/a", public=False), None),
            (target("demo"), None),
            ({**target("demo/a"), "tracker": {"kind": "jira", "location": "demo/a"}}, None),
        ]

        # when
        found = []
        for declaration, _expected in cases:
            write_json(root / "issue-target.json", declaration)
            found.append(boundary_plugins.declared_repository(root))

        # then
        self.assertEqual([expected for _declaration, expected in cases], found)

    def test_저장소_안에_추적된_파일은_비공개_이름을_담지_않는다(self) -> None:
        """기준 5: 추적 파일과 새 파일 어디에도 비공개 이름이 글자 그대로 없다."""
        # given
        listing = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=REPO_ROOT, check=True,
                                 capture_output=True).stdout.split(b"\0")

        # when
        hits = []
        for raw in filter(None, listing):
            path = REPO_ROOT / raw.decode("utf-8", "surrogateescape")
            if path.is_file() and not path.is_symlink() and PRIVATE_WORD.encode() in path.read_bytes().lower():
                hits.append(str(path.relative_to(REPO_ROOT)))

        # then
        self.assertEqual([], hits)


if __name__ == "__main__":
    unittest.main()
