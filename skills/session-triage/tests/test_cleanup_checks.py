#!/usr/bin/env python3
"""정리 검사 스크립트가 세션 워크트리의 검사를 검사마다 pass, fail, unreadable로 똑같이 보고하는지 검사한다."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("cleanup_checks_under_test", SCRIPTS / "cleanup_checks.py")
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)

HANDLE = "term_demo-a"
PANE = "tab-a:leaf-a"
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
    "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def sh(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout


def commit(path: Path, name: str, text: str) -> None:
    (path / name).write_text(text, encoding="utf-8")
    sh(path, "add", name)
    sh(path, "commit", "-q", "-m", f"change {name}")


def ok(result: dict) -> tuple[int, str, str]:
    return 0, json.dumps({"ok": True, "result": result}), ""


class Rig:
    """A throwaway repository with a `feature` branch checked out, and a fake `orca`, `lsof`, and `ps` around it."""

    def __init__(self, root: Path, current: str | None = None, other_terminals: list[str] | None = None) -> None:
        self.root = root
        self.path = root / "work"
        self.origin = root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=GIT_ENV)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.path)], check=True, capture_output=True, env=GIT_ENV)
        sh(self.path, "checkout", "-q", "-b", "main")
        commit(self.path, "a.txt", "a\n")
        sh(self.path, "push", "-q", "-u", "origin", "main")
        sh(self.path, "checkout", "-q", "-b", "feature")
        commit(self.path, "b.txt", "b\n")
        self.worktree_id = f"repo-1::{self.path}"
        self.current = current
        self.terminals = [HANDLE, *(other_terminals or [])]
        self.ports: list[dict] = []
        self.lsof = ""
        self.ps = ""
        self.failing: set[str] = set()
        self.agent_row = True

    def merge_feature_into_main(self, squash: bool = False) -> None:
        sh(self.path, "checkout", "-q", "main")
        sh(self.path, "merge", "-q", *(["--squash"] if squash else []), "feature")
        if squash:
            sh(self.path, "commit", "-q", "-m", "squash feature")
        sh(self.path, "checkout", "-q", "feature")

    def row(self) -> dict:
        return {
            "worktreeId": self.worktree_id, "repo": "demo-repo", "path": str(self.path), "branch": "refs/heads/feature",
            "displayName": "work", "workspaceStatus": "in-progress", "comment": "", "isMainWorktree": False,
            "parentWorktreeId": None, "childWorktreeIds": [], "liveTerminalCount": len(self.terminals),
            "agents": [{"paneKey": PANE, "agentType": "claude", "state": "done", "stateStartedAt": 0,
                        "lastAssistantMessage": "done", "prompt": "p", "interrupted": False}] if self.agent_row else [],
        }

    def terminal_rows(self) -> list[dict]:
        rows = [{"handle": handle, "tabId": "tab-a" if index == 0 else f"tab-{index}",
                 "leafId": "leaf-a" if index == 0 else f"leaf-{index}", "worktreeId": self.worktree_id}
                for index, handle in enumerate(self.terminals)]
        return rows

    def __call__(self, argv):
        if argv[0] == "git":
            return checks.overview.subprocess_runner(argv)
        if argv[0] == "lsof":
            return (0, self.lsof, "")
        if argv[0] == "ps":
            return (0, self.ps, "")
        key = (argv[1], argv[2])
        if argv[1] in self.failing:
            return 1, "", "orca could not answer"
        if key == ("worktree", "ps"):
            return ok({"worktrees": [self.row()]})
        if key == ("terminal", "list"):
            return ok({"terminals": self.terminal_rows()})
        if key == ("diagnostics", "memory"):
            return ok({"host": {}, "worktrees": []})
        if key == ("worktree", "list"):
            return ok({"worktrees": []})
        if argv[1] == "ports":
            return ok({"ports": self.ports})
        raise AssertionError(f"unexpected call {argv}")

    def run(self, *flags: str, ref: str = "main") -> tuple[int, dict | None]:
        env = {"ORCA_TERMINAL_HANDLE": self.current} if self.current else {}
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = checks.main(["--worktree-id", self.worktree_id, "--base-ref", ref, *flags], runner=self, env=env)
        return code, (json.loads(out.getvalue()) if out.getvalue() else None)


def statuses(report: dict) -> dict[str, str]:
    return {name: check["status"] for name, check in report["checks"].items()}


class CleanupChecksCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rig = Rig(Path(self.temp.name))

    def test_병합되고_깨끗하고_혼자인_세션은_두_번의_실행이_모두_종료_코드_0이고_모든_항목이_pass다(self) -> None:
        """끝난 세션의 워크트리가 병합됐고 변경이 없고 터미널이 하나뿐이면 종료 전후 실행이 모두 0이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.lsof = f"p500\nn{self.rig.path}\n"
        self.rig.ps = "500 1 -zsh\n"
        # when
        first_code, first = self.rig.run()
        self.rig.agent_row = False
        second_code, second = self.rig.run("--after-exit")
        # then
        self.assertEqual((0, 0), (first_code, second_code))
        self.assertEqual({"not_main", "no_children", "not_current", "only_terminal", "status_clean", "base_merged"},
                         {name for name, status in statuses(first).items() if status == "pass"})
        self.assertEqual({"no_ports", "no_processes"}, set(statuses(second)) - set(statuses(first)))
        self.assertEqual(first["checks"], {name: second["checks"][name] for name in first["checks"]})
        self.assertEqual(["pass", "pass"], [statuses(second)["no_ports"], statuses(second)["no_processes"]])

    def test_수정한_추적_파일이_있으면_status_clean만_fail이고_나머지_항목도_보고한다(self) -> None:
        """추적 파일이 수정되면 status_clean이 fail이고 종료 코드 1이며 다른 항목은 그대로 보고된다."""
        # given
        self.rig.merge_feature_into_main()
        (self.rig.path / "b.txt").write_text("edited\n", encoding="utf-8")
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual(1, code)
        self.assertEqual("fail", statuses(report)["status_clean"])
        self.assertEqual("pass", statuses(report)["base_merged"])
        self.assertEqual([" M b.txt"], report["checks"]["status_clean"]["value"])

    def test_무시된_build_폴더만_있으면_status_clean은_pass이고_ignored에_나온다(self) -> None:
        """무시된 build 폴더는 변경이 아니므로 pass이고, 사람이 판단하도록 ignored 목록에 담는다."""
        # given
        self.rig.merge_feature_into_main()
        commit(self.rig.path, ".gitignore", "build/\n")
        sh(self.rig.path, "checkout", "-q", "main")
        sh(self.rig.path, "merge", "-q", "feature")
        sh(self.rig.path, "checkout", "-q", "feature")
        (self.rig.path / "build").mkdir()
        (self.rig.path / "build" / "out.o").write_text("x", encoding="utf-8")
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual((0, "pass", ["build/"]), (code, statuses(report)["status_clean"], report["ignored"]))

    def test_스쿼시_병합된_브랜치는_base_merged가_fail이고_squash_possible은_pass다(self) -> None:
        """커밋은 기준 ref에 없지만 바뀐 파일 내용이 모두 같으면 squash_possible이 pass이고 종료 코드는 1이다."""
        # given
        self.rig.merge_feature_into_main(squash=True)
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual(1, code)
        self.assertEqual(("fail", "pass"), (statuses(report)["base_merged"], statuses(report)["squash_possible"]))

    def test_기준_ref에_없는_변경이_있으면_base_merged와_squash_possible이_모두_fail이다(self) -> None:
        """브랜치에만 있는 파일 변경이 있으면 스쿼시 병합으로 볼 수 없어 둘 다 fail이다."""
        # given
        self.rig.merge_feature_into_main(squash=True)
        commit(self.rig.path, "c.txt", "only on the branch\n")
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual(1, code)
        self.assertEqual(("fail", "fail"), (statuses(report)["base_merged"], statuses(report)["squash_possible"]))

    def test_에이전트_없는_워크트리는_푸시하지_않은_커밋_수로_base_merged를_판단한다(self) -> None:
        """--no-agent에서 upstream 앞선 커밋이 둘이면 base_merged는 fail이고 값이 2다."""
        # given
        self.rig.agent_row = False
        sh(self.rig.path, "push", "-q", "-u", "origin", "feature")
        commit(self.rig.path, "c.txt", "one\n")
        commit(self.rig.path, "d.txt", "two\n")
        # when
        code, report = self.rig.run("--no-agent")
        # then
        self.assertEqual(1, code)
        self.assertEqual(("fail", 2), (statuses(report)["base_merged"], report["checks"]["base_merged"]["value"]))
        self.assertIn("no_shared_worktree", report["checks"])

    def test_upstream이_없는_브랜치는_no_agent에서_base_merged가_fail이다(self) -> None:
        """upstream이 없으면 원격에 작업이 있다고 볼 수 없으므로 fail이다."""
        # given
        self.rig.agent_row = False
        # when
        code, report = self.rig.run("--no-agent")
        # then
        self.assertEqual((1, "fail"), (code, statuses(report)["base_merged"]))

    def test_다른_터미널이_같은_워크트리에_있으면_only_terminal이_fail이다(self) -> None:
        """한 워크트리를 터미널 둘이 쓰면 그 체크아웃을 지우면 안 되므로 only_terminal이 fail이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.terminals.append("term_demo-b")
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual((1, "fail"), (code, statuses(report)["only_terminal"]))

    def test_현재_세션의_워크트리면_not_current가_fail이다(self) -> None:
        """현재 터미널이 그 워크트리에 있으면 자기 자신의 체크아웃을 지우게 되므로 fail이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.current = HANDLE
        # when
        code, report = self.rig.run()
        # then
        self.assertEqual((1, "fail"), (code, statuses(report)["not_current"]))

    def test_열린_포트와_실행_중인_프로세스가_있으면_no_ports와_no_processes가_fail이다(self) -> None:
        """종료 뒤에도 포트가 열려 있거나 셸이 아닌 프로세스의 작업 디렉터리가 안에 있으면 둘 다 fail이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.ports = [{"port": 3000, "pid": 700}]
        self.rig.lsof = f"p500\nn{self.rig.path}\np700\nn{self.rig.path}/sub\n"
        self.rig.ps = "500 1 -zsh\n700 1 node server.js\n"
        # when
        code, report = self.rig.run("--after-exit")
        # then
        self.assertEqual(1, code)
        self.assertEqual(("fail", "fail"), (statuses(report)["no_ports"], statuses(report)["no_processes"]))
        self.assertEqual(["700 node server.js"], report["checks"]["no_processes"]["value"])

    def test_자식이_있는_셸은_유휴_셸로_보지_않는다(self) -> None:
        """셸이 빌드를 돌리는 중이면 그 셸도 실행 중으로 세어 no_processes가 fail이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.lsof = f"p500\nn{self.rig.path}\n"
        self.rig.ps = "500 1 bash\n900 500 make\n"
        # when
        code, report = self.rig.run("--after-exit")
        # then
        self.assertEqual((1, "fail"), (code, statuses(report)["no_processes"]))

    def test_오르카_명령이_오류를_내면_그_항목만_unreadable이고_종료_코드_3이다(self) -> None:
        """orca ports가 오류를 내고 나머지는 모두 pass면 그 항목만 unreadable이며 종료 코드는 3이다."""
        # given
        self.rig.merge_feature_into_main()
        self.rig.lsof = f"p500\nn{self.rig.path}\n"
        self.rig.ps = "500 1 -zsh\n"
        self.rig.failing = {"ports"}
        # when
        code, report = self.rig.run("--after-exit")
        # then
        self.assertEqual(3, code)
        self.assertEqual("unreadable", statuses(report)["no_ports"])
        self.assertEqual("pass", statuses(report)["no_processes"])


class SkillTextCase(unittest.TestCase):
    def test_SKILL은_두_스크립트_호출을_담고_여섯_명령을_단계로_풀어쓰지_않는다(self) -> None:
        """clean up 단계가 cleanup_checks.py 두 호출로 바뀌어 모델이 검사 명령을 다시 쓰지 않는다."""
        # given
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        # when
        calls = re.findall(r"cleanup_checks\.py --worktree-id", text)
        written_out = [command for command in ("status --porcelain", "merge-base --is-ancestor", "rev-list --count",
                                               "orca ports", "lsof -d cwd", "orca terminal list --worktree") if command in text]
        # then
        self.assertEqual(2, len(calls), "the plain run and the --after-exit run")
        self.assertIn("--after-exit", text)
        self.assertEqual([], written_out)


if __name__ == "__main__":
    unittest.main()
